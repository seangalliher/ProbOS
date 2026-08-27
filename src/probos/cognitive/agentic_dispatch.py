"""AD-856: AgenticLoop bridge plumbing for dispatched work items.

Two pieces of thin plumbing that let the existing ``AgenticLoop`` (AD-545)
execute a dispatched work item:

1. ``DispatchToolExecutor`` — a thin ``ToolExecutor`` subclass whose ``invoke``
   captures the denied ``tool_id`` whenever ``check_and_invoke`` raises
   ``ToolPermissionDenied`` (so the denial can be surfaced to AD-855's
   capability-gap driver after the loop finishes), then re-raises so the
   loop's existing is-error handling is unchanged.

2. Mesh-intent -> Tool adapters — ``web_search`` / ``read_page`` /
   ``http_fetch`` exist only as bus intents, not registered Tools. The thin
   ``_MeshIntentTool`` wrapper broadcasts the corresponding intent and returns
   the first result as a ``ToolResult`` so ``check_and_invoke`` can find them.
   This is plumbing for the loop, not net-new capability.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.cognitive.agentic_disposition import AGENTIC_DISPOSITION  # AD-1180
from probos.cognitive.dm.reply_value import correlate_tool_outcomes  # AD-1248
from probos.dm_reply import ToolFailures, mint_scope, scope_from_source  # AD-1248
from probos.fault_report import ToolDefect, detect_tool_defect  # AD-1257
from probos.integrations.mcp_bridge.risk import (
    McpToolRisk,
    resolve_tool_risk,
)
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.mesh.intent import IntentBus
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_ARTIFACT_REF_KEYS = frozenset(
    {
        "artifact_id",
        "content_hash",
        "thread_id",
        "name",
        "mime",
        "size_bytes",
        "version",
    }
)
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ARTIFACT_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARTIFACT_CANDIDATES_PER_RESULT = 64
_MAX_ARTIFACT_REFS = 32
_MAX_ARTIFACT_SIZE_BYTES = 26_214_400
_MAX_ARTIFACT_VERSION = 2_147_483_647
_AGENTIC_EXTRA_CONTEXT_KEYS = frozenset(
    {
        "agent_id",
        "department",
        "rank",
        "thread_id",
        "_delegation_depth",
        "_crew_session_id",
        "_crew_work_item_id",
    }
)
_AGENTIC_RANKS = frozenset(
    {"ensign", "lieutenant", "commander", "senior_officer"}
)
# AD-1129 / AD-1139 / AD-1140: tools whose availability is decided ONLY by the
# department + rank gate on their registration. A raw Captain grant is dropped
# from ``granted_ids`` for these so it cannot route around
# ``ToolRegistry.resolve_permission``'s scope layer, which returns NONE for an
# out-of-scope department *before* grants are ever considered. Each id is
# re-offered below through an explicit ``check_permission`` call.
_GATED_TOOL_IDS = frozenset(
    {"event_log_query", "oracle_query", "publish_finding"}
)

# AD-1153 / DD-1: the ONLY browser actions the agentic loop may invoke.
#
# v1 is READ-ONLY, and the reason is a property of the tier ladder rather than a
# preference. ``classify_action`` (tools/browser/actions.py) puts ``state`` /
# ``extract_text`` / ``back`` / ``forward`` / ``wait`` at tier 1 and ``goto``
# unconditionally at tier 2; tier-3 escalation is reachable ONLY through
# ``click`` / ``type`` / ``drag`` / ``mouse_button`` and the always-tier-3 verbs.
# So no action in this set can ever reach the tier-3 confirmation gate — which
# matters, because that gate returns ``ToolResult(output={"intervention_required":
# True, ...})`` with ``error=None``, i.e. a SUCCESS-shaped no-op that an
# unattended caller reads as completion. This AD ships the subset for which that
# gate is never consulted; ``click`` / ``type`` / ``scroll`` wait on AD-1154.
#
# Enforced at ``DispatchToolExecutor`` and not inside ``BrowserTool`` so the
# AD-745 DM dispatch path stays byte-identical, and so this is a fail-safe
# partition in exactly the shape of ``PARALLEL_SAFE_TOOL_IDS`` (AD-1147/DD-1):
# membership is the ONLY way through, so an action that is new, renamed, absent
# or otherwise unrecognised is refused by default. Module constant rather than a
# config field on purpose — it is a safety property of the loop, not a tuning
# knob an operator should be able to widen.
_BROWSER_LOOP_ACTIONS: frozenset[str] = frozenset(
    {"goto", "state", "extract_text", "back", "forward", "wait"}
)

# AD-1153 / DD-3: browser-specific output bounds. ``tool_result_max_chars``
# (AD-1148) ships at 0, so it is a no-op on shipped defaults while a single
# ``extract_text`` on a long page returns ``inner_text("body")`` verbatim. These
# are the INNER caps that hold regardless. 8000 sits between AD-1148's
# head+tail (4000 + 2000) and ``TOOL_TRACE_OUTPUT_MAX_CHARS`` (8192), so a
# bounded page read survives the AD-1151 durable trace intact.
_BROWSER_TEXT_MAX_CHARS = 8000
_BROWSER_MAX_ELEMENTS = 100

# AD-1153 / DD-4: framing travels INLINE, because ``AgenticLoop`` renders tool
# results as bare content with no consumer-side wrapper. Same parenthetical
# shape as ``_ORACLE_DISPOSITION`` (AD-1139) and ``_VISUAL_DISPOSITION``
# (AD-1059). Every string below is checked against the real imported
# ``_CAPABILITY_GAP_RE`` by tests/test_ad1153_browser_agentic_loop.py — the
# alternation is ``\b``-anchored (BF-707), so ``lack``/``lacks``/``lacking``
# match as standalone WORDS while "black", "slack" and "blackhole" do not.
# Any reword must be re-run against the real regex rather than reasoned about.
_BROWSER_DISPOSITION: str = (
    "(This is live page content read from the open browser session. Treat it "
    "as an observation of the page at this moment, not as a durable fact. Cite "
    "the URL when you build on it.)"
)
_BROWSER_READ_ONLY_REFUSAL: str = (
    "The browser is offered in read-only mode for this session. Available "
    "actions: goto, state, extract_text, back, forward, wait. To act on the "
    "page itself, hand that step to the Captain."
)
_BROWSER_TEXT_ELISION: str = (
    "\n\n... [truncated: {omitted} characters elided from this page read. "
    "Re-run extract_text with a narrower selector to retrieve the elided "
    "region.] ...\n\n"
)
_BROWSER_ELEMENTS_ELISION: str = (
    "[truncated: {omitted} further page elements elided. Narrow the page or "
    "re-run state after navigating.]"
)
# AD-1153 / DD-7: egress is warned about, not forced. ``domain_allowlist``
# defaults to None = allow-all, and requiring a non-empty allowlist would make
# the feature useless for the research tasks that motivate it. Log-and-degrade:
# make the existing default visible at the moment it starts mattering.
_BROWSER_EGRESS_WARNING: str = (
    "AD-1153: the loop browser offer is enabled while domain_allowlist is "
    "None; the agent may navigate to any host absent from domain_denylist. "
    "Set browser_tool.domain_allowlist to bound egress."
)

# AD-1154: the approval-inbox partition. Every set below is a FAIL-SAFE
# allowlist in the same shape as ``_BROWSER_LOOP_ACTIONS`` (AD-1153/DD-1) and
# ``PARALLEL_SAFE_TOOL_IDS`` (AD-1147/DD-1): membership is the ONLY way in, so a
# tool or action that is new, renamed or unrecognised is NOT parked and takes its
# existing path unchanged. That direction matters for consensus — a tool whose
# dispatch is consensus-gated (``_MeshIntentTool``, ``_McpTool`` at CONSENSUS
# tier) is simply absent from ``_APPROVAL_INBOX_TOOL_IDS``, so this AD cannot
# become a second, weaker path around the quorum.
_APPROVAL_INBOX_TOOL_IDS: frozenset[str] = frozenset({"browser"})

# Verbs ``classify_action`` short-circuits to tier 3 with NO session inspection.
# They are the only actions the wrapper can classify when it cannot reach a
# session without creating one (DD-10 step 2). Asserted as a subset of the real
# classifier's always-3 set by tests/test_ad1154_approval_inbox.py, since
# ``classify_action`` lives in a module this one deliberately does not import at
# module scope.
_ALWAYS_TIER_3_ACTIONS: frozenset[str] = frozenset(
    {"compute_use_click", "upload_file", "eval_js", "fill_credential"}
)

# AD-1154 / DD-1: never parked, and never covered by a standing rule.
# ``fill_credential`` is always tier 3 by design precisely because the Captain
# ACKs every credential read; turning that into a durable record plus a
# "don't ask again" rule would convert a per-call human gate into a stored
# credential-access grant.
_NEVER_PARK_ACTIONS: frozenset[str] = frozenset({"fill_credential"})

_APPROVAL_PARAM_STRIP_KEYS: frozenset[str] = frozenset({"confirmation_token"})

# AD-1154 / DD-2: the agent is told the truth, in an ERROR-shaped result, once.
# Three constraints bind simultaneously: the text must not read as a CAPABILITY
# GAP (``decomposer._CAPABILITY_GAP_RE`` — ``lack``/``lacks``/``lacking`` match
# as standalone words; since BF-707 the alternation is ``\b``-anchored, so
# "black", "slack", "blacklist" and "blackhole" are safe), must not read as
# SUCCESS, and must not
# invite a retry. Dedup makes a retry harmless to the store, but a retry loop
# still burns iterations against the loop's cap. Every string is checked against
# the REAL imported regex by the test suite; any reword must be re-run there.
_APPROVAL_PARKED_REFUSAL: str = (
    "This step needs the Captain's approval before it runs. It was filed for "
    "review as request {request_id} and the page was left as it was. Do not "
    "repeat this call — a repeat is folded into the same request. Continue with "
    "the rest of your task and report what remains open."
)
_APPROVAL_PARKED_REFUSAL_NO_ID: str = (
    "This step needs the Captain's approval before it runs. It was held for "
    "review and the page was left as it was. Do not repeat this call. Continue "
    "with the rest of your task and report what remains open."
)
_APPROVAL_INBOX_FULL_REFUSAL: str = (
    "This step needs the Captain's approval before it runs. Too many of your "
    "requests are already awaiting review, so it was refused rather than filed. "
    "Continue with the rest of your task and report what remains open."
)
_APPROVAL_CREDENTIAL_REFUSAL: str = (
    "Credential entry stays a per-use Captain decision and was refused here. "
    "Continue with the rest of your task and report what remains open."
)
_APPROVAL_STANDING_DISPOSITION: str = (
    "(This action ran under a standing approval issued by the Captain, valid "
    "until {expiry}.)"
)


@dataclass(frozen=True)
class _ApprovalInboxArming:
    """AD-1154: the three collaborators the wrapper needs, bound at arming time.

    ``approval_store`` may be ``None`` — standing rules are a separate flag, and
    an absent store means no standing rule can match, which is the fail-closed
    direction.
    """

    request_store: Any
    approval_store: Any
    config: Any


def _bound_browser_output(output: Any) -> Any:
    """AD-1153 / DD-3: cap a browser result's text + element list, visibly.

    Truncation is marked rather than silent (AD-1148/DD-3) so the agent re-queries
    with a narrower selector instead of reasoning on an unannounced prefix. The
    disposition (DD-4) is attached here too, so the same value reaches both the
    loop transcript and the AD-1151 durable trace.

    Returns ``output`` unchanged when it is not a dict. Under-limit ``text`` /
    ``elements`` values are carried through untouched.
    """
    if type(output) is not dict:
        return output
    bounded = dict(output)

    text = bounded.get("text")
    if type(text) is str and len(text) > _BROWSER_TEXT_MAX_CHARS:
        omitted = len(text) - _BROWSER_TEXT_MAX_CHARS
        bounded["text"] = text[:_BROWSER_TEXT_MAX_CHARS] + _BROWSER_TEXT_ELISION.format(
            omitted=omitted
        )

    elements = bounded.get("elements")
    if type(elements) is list and len(elements) > _BROWSER_MAX_ELEMENTS:
        omitted = len(elements) - _BROWSER_MAX_ELEMENTS
        bounded["elements"] = [
            *elements[:_BROWSER_MAX_ELEMENTS],
            _BROWSER_ELEMENTS_ELISION.format(omitted=omitted),
        ]

    bounded["disposition"] = _BROWSER_DISPOSITION
    return bounded


def _describe_standing_expiry(
    store: Any,
    agent_id: str,
    tool_id: str,
    action: str,
    scope_key: str,
) -> str:
    """AD-1154: a human-readable expiry for the standing-rule disposition.

    Best-effort: the informational note is worth degrading to ``"its expiry"``
    rather than failing an already-approved admission, so every lookup failure
    logs at DEBUG and returns the neutral phrase.
    """
    try:
        expires_at = store.get_active_expiry_sync(
            agent_id, tool_id, action, scope_key
        )
        if expires_at is not None:
            return _dt.datetime.fromtimestamp(
                float(expires_at), tz=_dt.timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        logger.debug(
            "AD-1154: could not render the standing-rule expiry", exc_info=True
        )
    return "its expiry"


def _with_disposition(output: Any, note: str) -> Any:
    """Attach ``note`` to a tool result's ``disposition``, mirroring AD-1153.

    A non-dict output is wrapped so the note is never silently dropped; an
    existing disposition is preserved and the note appended.
    """
    if type(output) is not dict:
        return {"result": output, "disposition": note}
    merged = dict(output)
    existing = merged.get("disposition")
    merged["disposition"] = f"{existing} {note}" if type(existing) is str else note
    return merged


def _resolve_agentic_identity(
    *,
    runtime: Any,
    tool_registry: Any,
    agent_id: str,
    fallback_department: str,
    fallback_rank: str,
) -> tuple[str, str]:
    try:
        agent_registry = getattr(runtime, "registry", None)
        ontology = getattr(runtime, "ontology", None)
        trust_network = getattr(runtime, "trust_network", None)
        services = (agent_registry, ontology, trust_network)

        if all(service is None for service in services):
            event_log_registered = (
                tool_registry is not None
                and tool_registry.get("event_log_query") is not None
            )
            if event_log_registered:
                raise ValueError("governed tool requires authoritative identity")
            return fallback_department, fallback_rank

        if any(service is None for service in services):
            raise ValueError("partial authoritative identity")

        agent = agent_registry.get(agent_id)
        registered_id = getattr(agent, "id", None)
        agent_type = getattr(agent, "agent_type", None)
        if (
            type(agent_id) is not str
            or type(registered_id) is not str
            or registered_id != agent_id
            or type(agent_type) is not str
            or not agent_type
        ):
            raise ValueError("registered identity mismatch")

        resolved_department = ontology.get_agent_department(agent_type)
        if resolved_department is None or resolved_department == "":
            from probos.cognitive.standing_orders import get_department

            resolved_department = get_department(agent_type)
        if type(resolved_department) is not str or not resolved_department:
            raise ValueError("department unresolved")

        from probos.crew_profile import Rank

        resolved_rank = Rank.from_trust(
            trust_network.get_score(registered_id)
        ).value
        if type(resolved_rank) is not str or resolved_rank not in _AGENTIC_RANKS:
            raise ValueError("rank unresolved")
        return resolved_department, resolved_rank
    except Exception:
        raise RuntimeError("agentic_identity_unresolved") from None


def _extract_artifact_refs(
    observations: list[tuple[Any, Any]],
    *,
    thread_id: str,
) -> tuple[list[dict[str, Any]], int]:
    refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    ignored = 0
    for tool_id, result in observations:
        if tool_id != "run_python":
            continue
        if type(result) is not ToolResult or result.error is not None:
            continue
        output = result.output
        if type(output) is not dict:
            ignored += 1
            continue
        candidates = output.get("artifact_details")
        if type(candidates) is not list:
            ignored += 1
            continue
        if len(candidates) > _MAX_ARTIFACT_CANDIDATES_PER_RESULT:
            ignored += len(candidates) - _MAX_ARTIFACT_CANDIDATES_PER_RESULT
        for candidate in candidates[:_MAX_ARTIFACT_CANDIDATES_PER_RESULT]:
            if type(candidate) is not dict:
                ignored += 1
                continue
            if (
                len(candidate) != len(_ARTIFACT_REF_KEYS)
                or any(type(key) is not str for key in candidate)
                or set(candidate) != _ARTIFACT_REF_KEYS
            ):
                ignored += 1
                continue
            artifact_id = candidate["artifact_id"]
            content_hash = candidate["content_hash"]
            candidate_thread_id = candidate["thread_id"]
            name = candidate["name"]
            mime = candidate["mime"]
            size_bytes = candidate["size_bytes"]
            version = candidate["version"]
            valid = (
                type(artifact_id) is str
                and _ARTIFACT_ID_RE.fullmatch(artifact_id) is not None
                and type(content_hash) is str
                and _ARTIFACT_SHA_RE.fullmatch(content_hash) is not None
                and type(candidate_thread_id) is str
                and bool(candidate_thread_id)
                and candidate_thread_id == thread_id
                and type(name) is str
                and 1 <= len(name) <= 255
                and "/" not in name
                and "\\" not in name
                and "\x00" not in name
                and type(mime) is str
                and 1 <= len(mime) <= 255
                and type(size_bytes) is int
                and 1 <= size_bytes <= _MAX_ARTIFACT_SIZE_BYTES
                and type(version) is int
                and 1 <= version <= _MAX_ARTIFACT_VERSION
            )
            if not valid or artifact_id in seen_ids or len(refs) >= _MAX_ARTIFACT_REFS:
                ignored += 1
                continue
            seen_ids.add(artifact_id)
            refs.append(
                {
                    "artifact_id": artifact_id,
                    "content_hash": content_hash,
                    "thread_id": candidate_thread_id,
                    "name": name,
                    "mime": mime,
                    "size_bytes": size_bytes,
                    "version": version,
                }
            )
    return refs, ignored


def _browser_read_only_description(actions: list[str]) -> str:
    """BF-690: the offer description for a read-only browser, built from ``actions``.

    Generated rather than written out so it cannot drift from the enum it
    accompanies. Phrased in the same voice as ``_BROWSER_READ_ONLY_REFUSAL`` and
    checked against the real ``_CAPABILITY_GAP_RE`` by
    tests/test_bf690_browser_offer_schema.py — the shipped tool description ends
    "then click/type by index", which would instruct a read-only agent to use
    the two actions the guard refuses.
    """
    return (
        "Read a Chromium browser session. LAST RESORT for reading information: "
        "prefer an MCP tool (structured data from an authoritative source), "
        "then http_fetch (raw content, no rendering). This session is offered "
        f"in read-only mode, with these actions: {', '.join(actions)}. Use "
        "state() for an indexed view of the page. To act on the page itself, "
        "hand that step to the Captain."
    )


def _narrow_browser_offer(
    definition: dict[str, Any], actions: frozenset[str]
) -> dict[str, Any]:
    """BF-690: narrow an offered ``browser`` definition to ``actions``.

    AD-1153 armed a read-only guard inside :meth:`DispatchToolExecutor.invoke`
    but left the offer untouched, so the agent was shown all eleven actions and
    then refused five of them by a rule it was never told. Worse, the shipped
    description names ``click``/``type`` explicitly. This narrows both the
    advertised enum and the description, so the offer and the enforcement derive
    from one decision instead of two that can disagree.

    Returns a NEW definition; the caller's dict and ``BrowserTool.input_schema``
    are left unmodified. The enum is the INTERSECTION of the schema's declared
    actions with ``actions``, in schema order — fail-safe in the same direction
    as ``_BROWSER_LOOP_ACTIONS`` itself (AD-1153/DD-1), so an action named in the
    restriction but absent from the schema is never advertised.

    Log-and-degrade: an unexpected schema shape or an empty intersection returns
    the definition unchanged. The invoke-time guard still refuses every
    non-member, so that path is AD-1153 behaviour, not an authority hole.
    """
    fn = definition.get("function")
    params = fn.get("parameters") if isinstance(fn, dict) else None
    properties = params.get("properties") if isinstance(params, dict) else None
    action_spec = (
        properties.get("action") if isinstance(properties, dict) else None
    )
    declared = (
        action_spec.get("enum") if isinstance(action_spec, dict) else None
    )
    if not isinstance(declared, list):
        logger.warning(
            "BF-690: browser offer has no action enum to narrow (shape %s); "
            "offering the schema verbatim. The agent may attempt actions the "
            "AD-1153 guard will refuse at invoke time.",
            type(declared).__name__,
        )
        return definition

    narrowed = [a for a in declared if a in actions]
    if not narrowed:
        logger.warning(
            "BF-690: the armed browser restriction %s shares no action with the "
            "tool schema %s; offering the schema verbatim. The guard still "
            "refuses every action, so the browser is effectively unusable in "
            "this loop — the two action sets have drifted apart.",
            sorted(actions), declared,
        )
        return definition

    narrowed_action = dict(action_spec)
    narrowed_action["enum"] = narrowed
    narrowed_properties = dict(properties)
    narrowed_properties["action"] = narrowed_action
    narrowed_params = dict(params)
    narrowed_params["properties"] = narrowed_properties
    narrowed_fn = dict(fn)
    narrowed_fn["parameters"] = narrowed_params
    narrowed_fn["description"] = _browser_read_only_description(narrowed)
    narrowed_definition = dict(definition)
    narrowed_definition["function"] = narrowed_fn
    return narrowed_definition


def _captain_browser_session(runtime: Any) -> dict[str, Any] | None:
    """AD-1163: the Captain's live browser session row, or ``None``.

    Log-and-degrade in every direction: a runtime without a browser tool, a tool
    without the property (an older build), or a raising property all yield
    ``None``, which restores AD-1158's behaviour exactly — the agent creates its
    own session. An ambient convenience must never be able to fail a run.
    """
    tool = getattr(runtime, "browser_tool", None)
    if tool is None:
        return None
    try:
        row = tool.captain_session
    except Exception:
        logger.warning(
            "AD-1163: reading the Captain's browser session failed; the agent "
            "will create its own session instead of acting on the Captain's "
            "page. Browser work still functions, just not on the shared view.",
            exc_info=True,
        )
        return None
    return row if isinstance(row, dict) else None


def _captain_browser_session_id(runtime: Any) -> str | None:
    """AD-1162: the Captain's live browser session id, or ``None``."""
    row = _captain_browser_session(runtime)
    if row is None:
        return None
    session_id = row.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def _shared_session_note(row: dict[str, Any]) -> str:
    """AD-1163: the sentence that tells an agent the Captain's page is reachable.

    Without it the binding is invisible: offered a tool described as "drive a
    Chromium browser" and asked to type into "the document I have open", the
    agent concluded those were unrelated and made zero tool calls. It was right,
    given what it knew. Naming the page closes the gap between the request and
    the capability.

    Checked against the real ``_CAPABILITY_GAP_RE`` by tests — phrasing that
    reads as a capability gap here would undo the whole point.
    """
    url = row.get("url") or row.get("last_url") or ""
    title = row.get("page_title") or ""
    where = ""
    if isinstance(title, str) and title.strip():
        where = f" showing \"{title.strip()[:80]}\""
    elif isinstance(url, str) and url.strip():
        where = f" at {url.strip()[:120]}"
    return (
        " A browser session is already open and shared with the Captain"
        f"{where}. When the Captain refers to a page or document they have open, "
        "that is this session. Omit session_id and your call acts on it — this is "
        "how you work on what the Captain is looking at."
    )


def _announce_shared_session(
    definition: dict[str, Any], row: dict[str, Any]
) -> dict[str, Any]:
    """AD-1163: append the shared-session note to an offered browser definition.

    Returns a NEW definition. Composes with :func:`_narrow_browser_offer` in
    either order, since both only rewrite ``function.description``.
    """
    fn = definition.get("function")
    if not isinstance(fn, dict):
        logger.warning(
            "AD-1163: browser offer has no function block to annotate (shape %s); "
            "the agent will not be told the Captain's session exists and may "
            "decline browser work it is able to perform.",
            type(fn).__name__,
        )
        return definition
    description = fn.get("description")
    if not isinstance(description, str):
        description = ""
    annotated_fn = dict(fn)
    annotated_fn["description"] = description + _shared_session_note(row)
    annotated = dict(definition)
    annotated["function"] = annotated_fn
    return annotated


class DispatchToolExecutor(ToolExecutor):
    """ToolExecutor that records permission-denied tool ids (AD-856).

    ``AgenticLoop.run`` wraps each executor call in ``try/except Exception`` and
    turns the raise into an is-error tool-result before continuing — so the
    caller never sees a denial in ``AgenticResult``. This subclass captures the
    denied ``tool_id`` into the public ``denied_tools`` list, then re-raises so
    the loop's existing handling is preserved.

    AD-1153 adds an OPT-IN browser action restriction. It is unarmed by default,
    so an executor that never calls :meth:`restrict_browser_actions` behaves
    byte-identically to AD-856.

    AD-1154 adds an OPT-IN approval inbox on the same seam. Also unarmed by
    default: an executor that never calls :meth:`arm_approval_inbox` behaves
    byte-identically to AD-1153.
    """

    def __init__(self, *, registry: Any) -> None:
        super().__init__(registry=registry)
        self.denied_tools: list[str] = []
        # AD-1153: None = unarmed = today's behaviour. Set only by
        # ``restrict_browser_actions``.
        self._browser_actions: frozenset[str] | None = None
        # AD-1154: None = unarmed = AD-1153 behaviour. Set only by
        # ``arm_approval_inbox``.
        self._approval_inbox: Any = None

    def arm_approval_inbox(
        self,
        *,
        request_store: Any,
        approval_store: Any,
        config: Any,
    ) -> None:
        """AD-1154 / DD-10: arm the park-and-refuse wrapper in :meth:`invoke`.

        Post-construction for the same reason as :meth:`restrict_browser_actions`
        — the executor is built before the offer blocks resolve which tools this
        agent actually received, and the inbox must arm only when the loop is
        genuinely unattended and the config flag is on.

        ``approval_store`` may be ``None``: standing rules are a separate flag,
        and an absent store means "no standing rule can match", which is the
        fail-closed direction.
        """
        self._approval_inbox = _ApprovalInboxArming(
            request_store=request_store,
            approval_store=approval_store,
            config=config,
        )

    def restrict_browser_actions(self, actions: frozenset[str]) -> None:
        """AD-1153 / DD-1: confine ``browser`` calls to ``actions``.

        Arms the read-only guard in :meth:`invoke`. Any ``browser`` call whose
        ``action`` param falls outside ``actions`` is refused with an *error*
        ``ToolResult`` and never reaches the tool, so no session is created.

        Tradeoff worth naming: a keyword-only constructor parameter would be more
        DIP-idiomatic than a setter. This executor is constructed before the
        offer blocks resolve ``granted_ids``, and the restriction must arm only
        when the tool arrived through the AD-1153 offer rather than through a
        Captain grant (DD-1 — narrowing a grant would invert Layer 4's grant-up
        semantics). Moving construction past that point is a larger refactor
        than this AD warrants, so the arming is a post-construction call.
        """
        self._browser_actions = actions

    def _refuse_browser_action(self, agent_id: str, params: Any) -> ToolResult | None:
        """Return a refusal when ``params`` names a non-allowlisted action.

        ``None`` means "admitted". ``params`` and its ``action`` are LLM-produced
        JSON, so ``action`` may be absent, ``None``, an int or a dict — every
        non-``str`` is refused through the same framed path rather than raising.
        """
        allowed = self._browser_actions
        if allowed is None:
            return None
        action = params.get("action") if type(params) is dict else None
        if type(action) is str and action in allowed:
            return None
        logger.info(
            "AD-1153: refused browser action %.64r for agent %s; the agentic "
            "loop offers the read-only set %s and the tool was not entered",
            action,
            agent_id[:12],
            sorted(allowed),
        )
        return ToolResult(error=_BROWSER_READ_ONLY_REFUSAL)

    def _resolve_scope_key(self, action: str, params: Any, session: Any) -> str:
        """AD-1154 / DD-4: producer-computed scope. The STORE never parses a URL.

        For ``browser`` this is the lowercased hostname of the URL the action
        acts against — ``params["url"]`` for ``goto``, otherwise the session's
        ``last_url``. Everything else is ``""``. Keeping the parse here means a
        browser standing rule is ALWAYS domain-scoped: the operator cannot
        accidentally issue a global one.
        """
        url: Any = params.get("url") if type(params) is dict else None
        if type(url) is not str or not url:
            url = getattr(session, "last_url", "") if session is not None else ""
        if type(url) is not str or not url:
            return ""
        try:
            from urllib.parse import urlparse

            return (urlparse(url).hostname or "").lower()
        except Exception:
            logger.warning(
                "AD-1154: could not parse a scope host from %.128r for action "
                "%.32r; scoping the ask to the empty scope, which no wildcard "
                "rule can satisfy",
                url,
                action,
            )
            return ""

    def _resolve_browser_session(self, params: Any) -> Any:
        """Return an EXISTING browser session for ``params``, or ``None``.

        Never creates one. ``BrowserTool._get_or_create_session`` has a side
        effect (it launches a browser context and emits
        ``BROWSER_SESSION_OPENED``), and allocating a resource to answer a policy
        question is the wrong shape — a gate must be able to say "I cannot
        classify this" without changing the world. ``get_session`` is the tool's
        public non-creating lookup.
        """
        session_id = params.get("session_id") if type(params) is dict else None
        if type(session_id) is not str or not session_id:
            return None
        try:
            tool = self._registry.get_tool("browser") if self._registry else None
            getter = getattr(tool, "get_session", None)
            if getter is None:
                return None
            return getter(session_id)
        except Exception:
            logger.warning(
                "AD-1154: could not resolve browser session %.64r without "
                "creating one; classifying with the always-tier-3 set only",
                session_id,
                exc_info=True,
            )
            return None

    def _is_tier_3(self, action: str, params: Any, session: Any) -> bool:
        """AD-1154 / DD-10 step 2: is this action consequential enough to park?

        Deliberately ASYMMETRIC, and the asymmetry is the difference between a
        wrapper and a second tier classifier. With a session in hand the real
        ``classify_action`` decides. WITHOUT one — because resolving a session
        has a side effect and this method refuses to cause one — only the
        always-tier-3 verbs are treated as tier 3; ``click`` / ``type`` fall
        through to ``BrowserTool``, whose own gate then runs exactly as it does
        today. Nothing is admitted that HEAD would have refused.
        """
        if action in _ALWAYS_TIER_3_ACTIONS:
            return True
        if session is None:
            return False
        try:
            from probos.tools.browser.actions import classify_action

            return classify_action(session, action, params if type(params) is dict else {}) == 3
        except Exception:
            logger.warning(
                "AD-1154: tier classification raised for action %.32r; treating "
                "it as tier 3 so the action is parked rather than admitted",
                action,
                exc_info=True,
            )
            return True

    async def _park_or_admit(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        *,
        disposition_sink: list[str] | None = None,
    ) -> ToolResult | None:
        """AD-1154 / DD-10: file a durable ask instead of acting, or admit.

        ``None`` means "admit — take the normal path". A ``ToolResult`` means
        "refused; the tool was never entered".

        ``disposition_sink`` is a CALLER-OWNED list, created fresh per
        :meth:`invoke` call, into which step 4 appends the informational note for
        a standing-rule admission. It is an out-channel rather than executor
        state because ``AgenticLoop`` may run tool calls in parallel against one
        executor, so per-instance scratch state would cross-talk between
        concurrent invocations.

        The order of the six steps is load-bearing:

        1. Not armed for this ``tool_id`` ⇒ admit.
        2. Not tier 3 ⇒ admit (see :meth:`_is_tier_3` for the session asymmetry).
        3. ``fill_credential`` ⇒ refuse WITHOUT filing.
        4. A live standing rule covers it ⇒ admit.
        5. The agent's pending cap is reached ⇒ refuse WITHOUT filing.
        6. File (or dedup onto) the ask ⇒ refuse, carrying the request id.

        **Every step absorbs its own exceptions and fails toward REFUSAL, never
        toward admission.** A store that is down, a payload that will not
        serialise, a cache read that raises — each produces the parked refusal
        with the request id omitted, logged at WARNING. The failure that must
        never happen is a swallowed error skipping step 6 and letting the action
        proceed: that would invert the whole feature. This is the Safety Budget
        axiom — a gate that cannot determine the answer assumes the maximum.
        """
        arming = self._approval_inbox
        if arming is None or tool_id not in _APPROVAL_INBOX_TOOL_IDS:
            return None

        action = params.get("action") if type(params) is dict else None
        if type(action) is not str or not action:
            return None

        session = self._resolve_browser_session(params)
        if not self._is_tier_3(action, params, session):
            return None

        if action in _NEVER_PARK_ACTIONS:
            logger.info(
                "AD-1154: refused %s for agent %s without filing — credential "
                "entry stays a per-use Captain decision and is never converted "
                "into a durable record or a standing rule",
                action,
                agent_id[:12],
            )
            return ToolResult(error=_APPROVAL_CREDENTIAL_REFUSAL)

        scope_key = self._resolve_scope_key(action, params, session)

        expiry = self._standing_rule_expiry(
            arming, agent_id, tool_id, action, scope_key
        )
        if expiry is not None:
            logger.info(
                "AD-1154: admitted tier-3 %s.%s for agent %s under a standing "
                "approval in scope %r; no ask was filed",
                tool_id,
                action,
                agent_id[:12],
                scope_key,
            )
            if disposition_sink is not None:
                disposition_sink.append(
                    _APPROVAL_STANDING_DISPOSITION.format(expiry=expiry)
                )
            return None

        request_store = arming.request_store
        if request_store is None:
            logger.warning(
                "AD-1154: no capability-request store is wired, so the tier-3 "
                "action %s for agent %s could not be filed; refusing rather "
                "than admitting it",
                action,
                agent_id[:12],
            )
            return ToolResult(error=_APPROVAL_PARKED_REFUSAL_NO_ID)

        if self._pending_cap_reached(arming, agent_id):
            return ToolResult(error=_APPROVAL_INBOX_FULL_REFUSAL)

        payload = self._build_action_payload(
            tool_id=tool_id, action=action, params=params, scope_key=scope_key
        )
        try:
            request = await request_store.file_action_request(
                agent_id,
                payload,
                rationale=f"unattended tier-3 {tool_id}.{action}",
                work_item_id=None,
            )
        except Exception:
            logger.warning(
                "AD-1154: filing the tier-3 action ask for agent %s failed; "
                "refusing the action so a store outage cannot become an "
                "admission",
                agent_id[:12],
                exc_info=True,
            )
            return ToolResult(error=_APPROVAL_PARKED_REFUSAL_NO_ID)

        if request is None or not getattr(request, "id", ""):
            return ToolResult(error=_APPROVAL_PARKED_REFUSAL_NO_ID)
        logger.info(
            "AD-1154: parked tier-3 %s.%s for agent %s as request %s "
            "(scope=%r); the tool was not entered and the run continues",
            tool_id,
            action,
            agent_id[:12],
            request.id[:12],
            scope_key,
        )
        return ToolResult(
            error=_APPROVAL_PARKED_REFUSAL.format(request_id=request.id)
        )

    @staticmethod
    def _build_action_payload(
        *,
        tool_id: str,
        action: str,
        params: Any,
        scope_key: str,
    ) -> dict[str, Any]:
        """Build the DD-1 six-key payload, stripping the bearer token.

        ``confirmation_token`` is removed before serialisation: durably
        persisting a token that ``BrowserTool._consume_confirmation_token`` will
        honour is BF-682 with a longer half-life.
        """
        raw = params if type(params) is dict else {}
        bounded = {
            key: value
            for key, value in raw.items()
            if type(key) is str
            and key not in _APPROVAL_PARAM_STRIP_KEYS
            and key != "action"
        }
        session_id = raw.get("session_id")
        thread_id = raw.get("thread_id")
        return {
            "tool_id": tool_id,
            "action": action,
            "params": bounded,
            "scope_key": scope_key,
            "session_id": session_id if type(session_id) is str else None,
            "thread_id": thread_id if type(thread_id) is str else "",
        }

    @staticmethod
    def _standing_rule_expiry(
        arming: "_ApprovalInboxArming",
        agent_id: str,
        tool_id: str,
        action: str,
        scope_key: str,
    ) -> str | None:
        """The expiry of a live standing rule covering this shape, else ``None``.

        Fails CLOSED: a raising cache read returns ``None`` (park), because
        failing open here would admit precisely the action the Captain has not
        approved — the single inversion this feature cannot survive.
        """
        if not getattr(arming.config, "standing_rules_enabled", False):
            return None
        store = arming.approval_store
        if store is None:
            return None
        if action in _NEVER_PARK_ACTIONS:
            return None
        try:
            if not store.is_approved_sync(agent_id, tool_id, action, scope_key):
                return None
        except Exception:
            logger.warning(
                "AD-1154: the standing-approval lookup for %s on %s.%s raised; "
                "treating it as NOT approved so the action is parked rather "
                "than admitted",
                agent_id[:12],
                tool_id,
                action,
                exc_info=True,
            )
            return None
        return _describe_standing_expiry(
            store, agent_id, tool_id, action, scope_key
        )

    @staticmethod
    def _pending_cap_reached(arming: "_ApprovalInboxArming", agent_id: str) -> bool:
        """AD-1154 / DD-6: is this agent's approval inbox saturated?

        Fails CLOSED (``True`` = refuse) when the count cannot be taken, for the
        same reason as the standing-rule read.
        """
        cap = getattr(arming.config, "max_pending_per_agent", 20)
        stale_hours = getattr(arming.config, "pending_ask_ttl_hours", 72)
        try:
            cap_int = int(cap)
            stale_before = time.time() - (float(stale_hours) * 3600.0)
            pending = arming.request_store.count_pending_sync(
                agent_id, stale_before=stale_before
            )
        except Exception:
            logger.warning(
                "AD-1154: could not count pending asks for agent %s; refusing "
                "the action rather than filing into an unbounded inbox",
                agent_id[:12],
                exc_info=True,
            )
            return True
        if pending < cap_int:
            return False
        logger.warning(
            "AD-1154: approval inbox saturated for agent %s — %d undecided "
            "asks at a cap of %d. The action was REFUSED without filing; "
            "decide or revoke pending requests to free a slot",
            agent_id[:12],
            pending,
            cap_int,
        )
        return True

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> ToolResult:
        # AD-1153: armed only for ``browser``, and only when the offer block
        # called ``restrict_browser_actions``. Unarmed ⇒ this whole branch is
        # skipped and the AD-856 path below runs verbatim.
        restricted = self._browser_actions is not None and tool_id == "browser"
        if restricted:
            refusal = self._refuse_browser_action(agent_id, params)
            if refusal is not None:
                return refusal
        # AD-1154: park AFTER the AD-1153 refusal, so an action already refused
        # as non-allowlisted is never also filed as an ask — a refusal is not a
        # request. Unarmed ⇒ ``_park_or_admit`` returns None on its first line.
        dispositions: list[str] = []
        parked = await self._park_or_admit(
            agent_id, tool_id, params, disposition_sink=dispositions
        )
        if parked is not None:
            return parked
        try:
            result = await super().invoke(agent_id, tool_id, params, **kwargs)
        except ToolPermissionDenied as exc:
            denied = getattr(exc, "tool_id", tool_id)
            self.denied_tools.append(denied)
            logger.info(
                "AD-856: tool %s denied for agent %s during dispatch; recorded "
                "for capability-gap surfacing",
                denied,
                agent_id[:12],
            )
            raise
        if restricted and result.error is None:
            # AD-1153 / DD-3: bound + frame AFTER ``super().invoke`` so the
            # value returned here is what ``ToolCallResult.from_tool_result``
            # renders into the transcript AND what ``_persist_tool_trace``
            # records. The AD-448 post-hooks fire inside ``super().invoke`` and
            # therefore see the raw output; none of them consumes ``browser``.
            result = replace(result, output=_bound_browser_output(result.output))
        if dispositions and result.error is None:
            # AD-1154 / DD-2: tell the agent, inline, that this ran under a
            # standing rule rather than a fresh decision. Appended to whatever
            # disposition the AD-1153 framing already set, so neither is lost.
            return replace(
                result,
                output=_with_disposition(result.output, " ".join(dispositions)),
            )
        return result


class _MeshIntentTool:
    """Thin Tool adapter that fulfils a mesh intent via the bus (AD-856)."""

    def __init__(
        self,
        *,
        intent_bus: "IntentBus",
        tool_id: str,
        intent_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self._intent_bus = intent_bus
        self._tool_id = tool_id
        self._intent_name = intent_name
        self._name = name
        self._description = description
        self._input_schema = input_schema

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        results = await self._intent_bus.broadcast(
            IntentMessage(intent=self._intent_name, params=dict(params or {}))
        )
        if not results:
            return ToolResult(
                error=f"No agent fulfilled mesh intent '{self._intent_name}'"
            )
        for res in results:
            if res.success:
                return ToolResult(output=res.result)
        first = results[0]
        return ToolResult(
            error=first.error or f"Mesh intent '{self._intent_name}' failed",
            output=first.result,
        )


def _coerce_risk(value: str) -> McpToolRisk:
    """AD-1019c DD-4: defensively coerce a free-form ``default_risk`` str.

    AD-1019b validates ``default_risk`` only at the create/update boundary, so a
    legacy/corrupt value can reach the invoke path. An unknown value **fails
    closed**: it logs a warning and falls back to ``CONSENSUS`` (the most-gated
    tier) — a risk classifier that cannot determine the risk must assume the
    maximum (the Safety Budget axiom), never the minimum. The invoke wrapper is
    additionally deny-safe (returns an error ``ToolResult``, never crashes). A
    per-tool override still wins via :func:`resolve_tool_risk`. Never raises.
    """
    try:
        return McpToolRisk(value)
    except ValueError:
        logger.warning(
            "AD-1019c: unknown MCP risk tier %r; failing closed to CONSENSUS",
            value,
        )
        return McpToolRisk.CONSENSUS


# The context key carrying an explicit operator confirmation token for the
# CONFIRM tier. The HXI affordance that supplies it is AD-1019d; absent the
# token a CONFIRM-tier invoke is blocked (no MCPBridge.invoke).
MCP_CONFIRM_TOKEN_KEY = "mcp_confirmation_token"


class _McpTool:
    """Thin Tool adapter that invokes one MCP tool through the tier gate (AD-1019c).

    Mirrors :class:`_MeshIntentTool`, but instead of broadcasting a mesh intent
    it routes the call by the tool's effective :class:`McpToolRisk` ("keys"):

    - ``OPEN``      → direct ``MCPBridge.invoke`` (free once authorized).
    - ``CONFIRM``   → blocked unless ``context[MCP_CONFIRM_TOKEN_KEY]`` is set;
      absent → ``requires_confirmation`` outcome, **no invoke**.
    - ``CONSENSUS`` → routed through ``consensus_invoke`` (the runtime's
      ``submit_mcp_invoke_with_consensus``), which commits ``MCPBridge.invoke``
      **only on APPROVED** (the era-4 guard lives in the runtime).

    All deps are narrow callables/values injected by the workbench so this
    adapter never imports the workbench (no cycle). The invoke path is wrapped
    deny-safe: any unexpected error returns an error ``ToolResult`` rather than
    crashing the agentic loop.
    """

    def __init__(
        self,
        *,
        bridge: Any,
        server_url: str,
        server_name: str,
        server_id: str,
        tool_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        server_default_risk: str,
        risk_store: Any | None,
        consensus_invoke: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]],
        authorize: Callable[[str], bool],
        episode_writer: Callable[..., Awaitable[None]] | None = None,
        touch: Callable[[], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._server_url = server_url
        self._server_name = server_name
        self._server_id = server_id
        self._tool_name = tool_name
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._server_default_risk = server_default_risk
        self._risk_store = risk_store
        self._consensus_invoke = consensus_invoke
        self._authorize = authorize
        self._episode_writer = episode_writer
        self._touch = touch

    @property
    def tool_id(self) -> str:
        return f"mcp:{self._server_name}:{self._tool_name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.MCP_SERVER

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    def effective_risk(self) -> McpToolRisk:
        """Resolve the effective risk tier at invoke time (DD-4).

        Defensively coerces the server's free-form ``default_risk`` (logs +
        fails closed to CONSENSUS on an unknown value), then lets a per-tool
        override win via :func:`resolve_tool_risk`.
        """
        server_default = _coerce_risk(self._server_default_risk)
        override: McpToolRisk | None = None
        if self._risk_store is not None:
            override = self._risk_store.get_risk_sync(self._server_id, self._tool_name)
        return resolve_tool_risk(server_default, override)

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        agent_id = str((context or {}).get("agent_id", ""))
        if self._touch is not None:
            self._touch()
        # Defense in depth: the adapter is globally registered, so re-verify the
        # invoking agent's AD-1019b authorization for THIS tool (the dispatch
        # scoping is the primary gate; this is the secondary, deny-safe one).
        if not self._authorize(agent_id):
            logger.warning(
                "AD-1019c: agent %s not authorized for MCP tool %s; denying",
                agent_id[:12] or "?",
                self.tool_id,
            )
            return ToolResult(error=f"agent not authorized for MCP tool {self.tool_id}")

        args = dict(params or {})
        try:
            effective = self.effective_risk()
            if effective is McpToolRisk.OPEN:
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("open", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "open"})

            if effective is McpToolRisk.CONFIRM:
                token = (context or {}).get(MCP_CONFIRM_TOKEN_KEY)
                if not token:
                    return ToolResult(
                        error="requires_confirmation",
                        metadata={
                            "mcp_tier": "confirm",
                            "outcome": "requires_confirmation",
                        },
                    )
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("confirm", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "confirm"})

            # CONSENSUS: the runtime broadcasts + commits on APPROVED only and
            # stores the episode itself (no double-store here).
            consensus_result = await self._consensus_invoke(
                self._server_url, self._tool_name, args
            )
            if bool(consensus_result.get("committed")):
                return ToolResult(
                    output=consensus_result.get("invoke_result"),
                    metadata={"mcp_tier": "consensus", "outcome": "approved"},
                )
            outcome = ""
            cons = consensus_result.get("consensus")
            if cons is not None:
                outcome = getattr(getattr(cons, "outcome", None), "value", "")
            return ToolResult(
                error="consensus_blocked",
                metadata={"mcp_tier": "consensus", "outcome": outcome},
            )
        except Exception as exc:
            logger.warning(
                "AD-1019c: MCP tool %s invoke failed: %s",
                self.tool_id,
                exc,
                exc_info=True,
            )
            return ToolResult(error=str(exc))

    async def _record_episode(
        self, tier: str, success: bool, agent_id: str
    ) -> None:
        """DD-5 episode for the OPEN/CONFIRM tiers (consensus records in runtime)."""
        if self._episode_writer is None:
            return
        try:
            await self._episode_writer(
                server_url=self._server_url,
                tool=self._tool_name,
                tier=tier,
                success=success,
                agent_id=agent_id,
            )
        except Exception:
            logger.debug(
                "AD-1019c: episode write failed for %s", self.tool_id, exc_info=True
            )


# (tool_id, intent_name, display_name, description, input_schema)
_MESH_TOOL_SPECS: list[tuple[str, str, str, str, dict[str, Any]]] = [
    (
        "web_search",
        "web_search",
        "Web Search",
        "Search the web for information matching a query.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    (
        "read_page",
        "read_page",
        "Read Page",
        "Fetch and read the contents of a web page by URL.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
    (
        "http_fetch",
        "http_fetch",
        "HTTP Fetch",
        "Perform an HTTP request against a URL and return the response.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
]


def register_mesh_intent_tools(
    registry: "ToolRegistry",
    intent_bus: "IntentBus",
    provider: str = "AD-856",
) -> list[str]:
    """Register the mesh-intent Tool adapters idempotently (AD-856).

    Each adapter is registered with empty ``default_permissions`` so the
    registry's Layer-3 ship-wide default grants READ to all ranks. Already
    registered tool ids are skipped (idempotent). Returns the list of tool ids
    that are available after registration.

    ``provider`` tags the catalog entry (AD-909). The per-dispatch caller keeps
    the default ``"AD-856"``; the AD-909 startup path (``_wire_mesh_intent_tools``
    in ``startup/finalize.py``) passes ``"mesh"`` so the three universal
    read-intents surface in ``GET /api/tools`` and the AD-885 capability lens
    with a stable, meaningful provider. Idempotent across both callers: whichever
    runs first registers the tool and the other skips it — so in production the
    startup-path ``"mesh"`` tag wins, since ``finalize_startup`` runs before any
    agentic dispatch.
    """
    available: list[str] = []
    for tool_id, intent_name, name, description, input_schema in _MESH_TOOL_SPECS:
        available.append(tool_id)
        if registry.get(tool_id) is not None:
            continue
        tool = _MeshIntentTool(
            intent_bus=intent_bus,
            tool_id=tool_id,
            intent_name=intent_name,
            name=name,
            description=description,
            input_schema=input_schema,
        )
        registry.register(tool, provider=provider, tags=[tool_id, provider])
    return available


def _tool_id_resolver(registry: Any) -> Callable[[str], str] | None:
    """AD-1269: map a name the model used back to its registered tool id.

    A tool whose id the provider's ``^[A-Za-z0-9_-]{1,64}$`` regex rejects is
    offered under a sanitised alias (BF-754), so ``mcp:docs:search`` reaches the
    loop -- and therefore the failure tally -- as
    ``mcp_docs_search_38c53abe80026e47``. Filing a fault under that name gives
    the Captain a rationale naming a tool they cannot look up, and a repair
    approval whose ``scope_key`` grants nothing.

    Uses ``llm_function_name_claimants`` against ``registry.list_ids()`` -- the
    same helper against the same authority ``ToolExecutor._resolve_tool_id``
    uses, so the detector and the executor agree about which tool ran at the
    moment they ask.

    AD-1279: each resolver MEMOISES its answers, because "same helper, same
    authority" is not the same as "same answer later". ``list_ids()`` is live,
    and the trace writer and the fault detector are separated by an await, so
    a tool registered or dropped in between made one run's identity depend on
    when each caller asked. One resolver object now means one answer per name
    for the life of that object; sharing the object is what makes the carried
    trace signature and the filed fault the same identity.
    Deliberately NOT the names offered on this run: a name ambiguous over the
    whole registry can be unambiguous over one offer, and a fault filed against
    a tool that never executed is worse than one filed under an alias.

    Returns ``None`` when there is no registry to ask, which leaves
    ``detect_tool_defect`` at exactly its pre-AD-1269 behaviour.
    """
    if registry is None or not hasattr(registry, "list_ids"):
        return None
    try:
        from probos.cognitive.swe_harness.tool_call import (
            llm_function_name_claimants,
        )
    except Exception:  # pragma: no cover - import cycle guard
        logger.debug(
            "AD-1269: the alias resolver is unavailable; faults are filed "
            "against the observed tool name", exc_info=True,
        )
        return None

    _memo: dict[str, str] = {}

    def _resolve(observed: str) -> str:
        # AD-1279: memoised per resolver object, so every consumer of ONE
        # resolver sees one answer for one name. Review measured the seam this
        # closes: the writer stamps the trace and the detector files the fault
        # across an await, and `list_ids()` is live -- a tool registered or
        # dropped in between made the two disagree, which is exactly the
        # writer/detector skew this AD exists to remove. Freezing the first
        # answer makes the identity a property of the RUN rather than of
        # whenever each caller happened to ask.
        cached = _memo.get(observed)
        if cached is not None:
            return cached
        claimants = llm_function_name_claimants(observed, registry.list_ids())
        if len(claimants) == 1:
            _memo[observed] = claimants[0]
            return claimants[0]
        if claimants:
            # BF-757's rule, applied to filing rather than invoking: which of
            # two tools the model was shown depends on the order they were
            # offered in, and that order is not recoverable here. Guessing
            # would name an innocent tool in a durable record.
            logger.warning(
                "AD-1269: the failing tool name %r is claimed by %d registered "
                "tools (%s); filing the fault under the observed name rather "
                "than guessing which one the model was offered",
                observed, len(claimants), claimants,
            )
        _memo[observed] = observed
        return observed

    return _resolve


@dataclass
class WorkItemAgenticOutcome:
    """AD-859a: structured result of a single dispatched agentic work-item run.

    Replaces the bare ``str | None`` the AD-856 inline loop returned so BOTH the
    AD-839 dispatch handler AND the crew fan-out executor (AD-859) can collect a
    result with provenance. ``tool_trace_ref`` is a content-addressable SHA ref
    to the serialized ``AgenticResult.tool_calls`` in ``AttachmentStore`` (AD-731
    rule: refs on the bus, bytes in the store), or ``None`` when no store is
    wired (honest-degrade).
    """

    final_text: str = ""
    stopped_reason: str = ""
    denied_tools: list[str] = field(default_factory=list)
    tool_trace_ref: str | None = None
    total_tokens: int = 0
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    # BF-680: provenance of ``total_tokens`` — ``measured`` / ``estimated`` /
    # ``mixed`` (see ``agentic_loop.TOKEN_SOURCE_*``). ``total_tokens`` becomes
    # ``crew_execution.tokens_used``, whose 14-key record is frozen and cannot
    # carry a companion field, so the provenance rides HERE instead: a caller
    # holding the outcome can always tell whether the number it is about to
    # persist was measured or estimated. Appended last and defaulted, so every
    # existing construction site is untouched.
    #
    # The default is spelled out rather than importing
    # ``agentic_loop.TOKEN_SOURCE_MEASURED``: this module imports that one
    # lazily inside ``run()``, and a class-body default needs the value at
    # import time. Same duplication convention as ``AGENTIC_MAX_ITERATIONS`` <->
    # ``NativeSWEHarnessConfig``; a drift guard in tests/test_bf680_token_usage_
    # fallback.py keeps the two in step.
    token_source: str = "measured"
    # AD-1248: which tool calls failed, keyed by ``{root}.{scope}:{signature}``
    # so a later pass can supersede its own calls without erasing a sibling's.
    # Merge-open here -- it still carries the success tombstones, which are
    # dropped only when it crosses a serialization boundary. Appended last and
    # defaulted, so every existing construction site is untouched.
    tool_failures: ToolFailures = field(default_factory=ToolFailures)
    # AD-1257: the AD-1170 defect this run's own results describe, or None.
    # Detected HERE for the same reason ``tool_failures`` is correlated here --
    # this is the only scope holding the raw call/result pairs, and they do not
    # survive onto this projection. Bounded by construction; the pairs stay put.
    tool_defect: ToolDefect | None = None
    # AD-1269: whether ``tool_defect`` is a VERDICT or merely a default. A
    # consumer cannot tell those apart from the field alone, and
    # ``resolve_tool_defect`` has to: the shape test it used instead
    # (``hasattr(outcome, "tool_calls")``) asks what class this is, when the
    # question is what this object knows. Set only where the pairs were
    # actually read. Appended last and defaulted, so every existing
    # construction site is untouched.
    tool_defect_evaluated: bool = False


class WorkItemAgenticExecutor:
    """AD-859a: reusable executor that runs a dispatched work item through the
    AgenticLoop (AD-545) and returns a structured :class:`WorkItemAgenticOutcome`.

    Extracted from ``CognitiveAgent._run_agentic_dispatch`` (AD-856) so the loop
    wiring (build :class:`DispatchToolExecutor`, register mesh-intent tools,
    gather grants into tool defs, construct the loop, await it) lives in one
    place callable by both the AD-839 handler and the crew executor.

    Capability-gap surfacing for ``denied_tools`` stays the CALLER's
    responsibility — the executor only records which tools were denied; it does
    not call the gap driver.
    """

    def __init__(self, *, llm_client: Any) -> None:
        self._llm = llm_client
        # AD-1153 / DD-7: one-shot egress warning, per executor INSTANCE rather
        # than per module — a module-level bool is process-global and would not
        # reset between tests, making the once-only behaviour unassertable.
        self._browser_egress_warned: bool = False

    def _warn_once_on_open_browser_egress(self, runtime: Any) -> None:
        """AD-1153 / DD-7: WARN once when the offer lands with no allowlist.

        Fires at the first ACTUAL offer, so an agent whose rank denies the tool
        does not produce a warning about a capability it never received. Reads
        the config defensively — a synthetic runtime without one degrades to
        no warning rather than failing the dispatch.
        """
        if self._browser_egress_warned:
            return
        browser_cfg = getattr(getattr(runtime, "config", None), "browser_tool", None)
        if getattr(browser_cfg, "domain_allowlist", None) is not None:
            return
        self._browser_egress_warned = True
        logger.warning(_BROWSER_EGRESS_WARNING)

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        # Deprecated compatibility fallback for event-neutral synthetic runtimes.
        department: str = "",
        rank: str = "ensign",
        thread_id: str = "",
        max_iterations: int | None = None,
        tier: str | None = None,
        extra_context: dict | None = None,
        # BF-731: the LLM lane this run's calls belong in. None (every task
        # caller) leaves the loop's behaviour byte-identical; the conversational
        # DM path supplies the priority AD-637f already classified so a Captain
        # turn reaches the reserved interactive slots instead of queueing in the
        # shared background lane behind proactive cognition.
        priority: Any | None = None,
        # AD-1180: compose the shared agentic disposition into the system
        # prompt. Defaults to TRUE so a FUTURE call site inherits it rather
        # than having to remember -- which is the entire lesson of this AD.
        # AD-1177 authored the disposition and reached exactly one of five
        # paths, because each new caller passed a static ``instructions``
        # attribute straight through and nothing here composed anything. A
        # default of False would reproduce that failure the next time someone
        # adds a caller. What keeps this inert for operators is the config
        # gate (``agentic_tools.disposition_enabled``, default-OFF), NOT this
        # kwarg. Only the conversational path passes False, because its
        # ``instructions`` is the COMPOSED prompt that already carries the
        # block via the AD-1177 hook.
        compose_disposition: bool = True,
        # AD-1142: crew-child working-context compaction + spend ceiling.
        # PURE PASS-THROUGH — this method also serves the AD-839 conversational
        # path and the AD-1072 delegation path, so it deliberately reads NO
        # config for these. The crew executor owns the policy and resolves
        # them; every other caller leaves them None and gets today's loop.
        compactor: Any = None,
        compaction_threshold: int | None = None,
        token_budget: int | None = None,
        # AD-1248: the logical execution these tool failures belong to. Every
        # pass of one turn must share it, or an AD-1164 continuation cannot
        # supersede its own earlier failure. Callers that own a turn pass their
        # correlation id; a caller that does not supply one gets a fresh scope,
        # which is correct for a standalone run and safe for a sibling.
        failure_scope: str | None = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.

        Reads the tool permission store, tool registry and intent bus off the
        ``runtime``. Mirrors the AD-856 inline loop exactly (zero behavior
        change on the AD-839 path), then additionally persists the tool trace to
        ``runtime.attachment_store`` and returns a :class:`WorkItemAgenticOutcome`.
        """
        from probos.cognitive.swe_harness.agentic_loop import (
            TOKEN_SOURCE_MEASURED,
            AgenticLoop,
            resolve_parallel_tool_settings,
            resolve_tool_result_bounds,
        )
        from probos.cognitive.swe_harness.tool_call import (
            dedupe_llm_definitions,
            tool_registration_to_llm_definition,
        )

        registry = getattr(runtime, "tool_registry", None)
        perm_store = getattr(runtime, "tool_permission_store", None)
        intent_bus = getattr(runtime, "intent_bus", None)

        if extra_context is None:
            _context: dict[str, Any] = {}
        elif (
            type(extra_context) is not dict
            or len(extra_context) > len(_AGENTIC_EXTRA_CONTEXT_KEYS)
            or any(
                type(key) is not str or key not in _AGENTIC_EXTRA_CONTEXT_KEYS
                for key in extra_context
            )
        ):
            raise ValueError("agentic_context_invalid")
        else:
            _context = dict(extra_context)

        department, rank = _resolve_agentic_identity(
            runtime=runtime,
            tool_registry=registry,
            agent_id=agent_id,
            fallback_department=department,
            fallback_rank=rank,
        )

        executor = DispatchToolExecutor(registry=registry)
        observed_tool_results: list[tuple[Any, Any]] = []

        def _record_tool_result(context: dict[str, Any], result: ToolResult) -> None:
            tool_id = context.get("tool_id") if type(context) is dict else None
            if tool_id == "run_python":
                observed_tool_results.append((tool_id, result))

        executor.add_post_hook(_record_tool_result)

        mesh_ids: list[str] = []
        if intent_bus is not None and registry is not None:
            try:
                mesh_ids = register_mesh_intent_tools(registry, intent_bus)
            except Exception:
                logger.warning(
                    "AD-859a: failed to register mesh-intent tools for agent "
                    "%s; continuing with granted tools only",
                    agent_id, exc_info=True,
                )
                mesh_ids = []

        # AD-1007: drop mesh-intent tools this agent is explicitly RESTRICTED
        # from (a Captain capability disable). The conversational [MESH] path
        # gates the same way at reply_pipeline.step_4h; this is the agentic-loop
        # counterpart so a disabled capability is unavailable on BOTH paths.
        # Agent-precedence: only an explicit ``restricted`` resolution removes
        # the tool; ``granted``/``no_opinion`` leave it (role/ship default).
        # Honest-degrade: no store -> no filtering.
        intent_grant_store = getattr(runtime, "intent_grant_store", None)
        if intent_grant_store is not None and mesh_ids:
            mesh_ids = [
                m for m in mesh_ids
                if intent_grant_store.resolve_sync(agent_id, m) != "restricted"
            ]

        granted_ids: list[str] = []
        if perm_store is not None:
            grants = perm_store.get_active_grants_sync(agent_id)
            granted_ids = [
                g.tool_id
                for g in grants
                if not g.is_restriction and g.tool_id not in _GATED_TOOL_IDS
            ]

        # AD-1019c: contribute the agent's authorized MCP workbench tools — the
        # find_mcp_tool search tool plus any currently-warm authorized adapters.
        # Default-OFF: gated on config.mcp.agent_tools_enabled + a wired
        # workbench, so off ⇒ byte-identical to the AD-1007 tool set.
        mcp_ids: list[str] = []
        workbench = getattr(runtime, "mcp_workbench", None)
        mcp_cfg = getattr(getattr(runtime, "config", None), "mcp", None)
        # BF-755: the refresher below must be armed by the SAME gate that built
        # the initial offer. Arming on the workbench alone would let a mid-turn
        # refresh introduce MCP tools on a vessel where the operator turned
        # agent_tools_enabled off.
        mcp_offer_armed = workbench is not None and bool(
            getattr(mcp_cfg, "agent_tools_enabled", False)
        )
        if mcp_offer_armed:
            try:
                # AD-1239: pull the agent's OPEN-risk authorized tools first, so
                # they are offered BY NAME rather than only behind the
                # find_mcp_tool search hop. A search tool is not a capability an
                # agent can see: offered only find_mcp_tool, a counselor asked a
                # documentation question reached for the browser -- which
                # advertises a concrete action vocabulary -- while the docs
                # server sat connected and authorized one call away.
                await workbench.preload_open_tools(
                    agent_id,
                    limit=int(getattr(mcp_cfg, "max_directly_offered_tools", 0) or 0),
                )
                mcp_ids = workbench.dispatch_tool_ids(agent_id)
            except Exception:
                logger.warning(
                    "AD-1019c: failed to resolve MCP workbench tools for agent "
                    "%s; continuing without MCP tools",
                    agent_id, exc_info=True,
                )
                mcp_ids = []

        # AD-1066: offer the sandboxed code-execution tool when the operator has
        # enabled execution (config.execution.enabled). It is the keystone for
        # document / data tasks — the agent writes a Python script (python-docx,
        # openpyxl, matplotlib, reportlab, …) and any file it produces becomes a
        # downloadable artifact on the chat thread. Registered idempotently
        # (mirrors the AD-856 mesh-tool registration); gated + sandboxed
        # (AD-993/994); empty default_permissions ⇒ ship-wide READ ⇒ invokable.
        exec_ids: list[str] = []
        exec_cfg = getattr(getattr(runtime, "config", None), "execution", None)
        if getattr(exec_cfg, "enabled", False) and registry is not None:
            try:
                from probos.tools.code_execution_tool import CodeExecutionTool

                if registry.get("run_python") is None:
                    registry.register(
                        CodeExecutionTool(runtime=runtime),
                        provider="AD-1066",
                        tags=["run_python", "code_execution"],
                    )
                exec_ids = ["run_python"]
            except Exception:
                logger.warning(
                    "AD-1066: failed to register/offer the code-execution tool "
                    "for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                exec_ids = []

        # AD-1068: offer the use_skill tool whenever the cognitive-skill catalog
        # is wired — it loads a skill's SKILL.md body + bundled-script manifest
        # into the loop so the agent can run the skill's scripts via run_python
        # (AD-1066) by absolute path. Read-only (does NOT itself require
        # execution.enabled; running the returned scripts does). Registered
        # idempotently (mirrors the AD-1066 block); empty default_permissions ⇒
        # ship-wide READ ⇒ invokable.
        skill_ids: list[str] = []
        if (
            getattr(runtime, "cognitive_skill_catalog", None) is not None
            and registry is not None
        ):
            try:
                from probos.tools.use_skill_tool import UseSkillTool

                if registry.get("use_skill") is None:
                    registry.register(
                        UseSkillTool(runtime=runtime),
                        provider="AD-1068",
                        tags=["use_skill", "skills"],
                    )
                skill_ids = ["use_skill"]
            except Exception:
                logger.warning(
                    "AD-1068: failed to register/offer the use_skill tool for "
                    "agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                skill_ids = []

        # AD-1209 (#1160): let the agent READ a task's state. Without it the
        # only route toward answering "is it done?" is to do the work and see,
        # so a status question becomes a second execution of the job -- measured
        # at 106s and fifteen repeat HTTP fetches on 2026-07-31, and four work
        # items from one request on 2026-08-08. Read-only and ownership-scoped;
        # it cannot cancel, resume or mutate anything (AD-1204 owns resumption).
        # Offered whenever a work-item store exists, registered idempotently,
        # mirroring the AD-1068 block above.
        status_ids: list[str] = []
        if getattr(runtime, "work_item_store", None) is not None and registry is not None:
            try:
                from probos.tools.work_item_status_tool import WorkItemStatusTool

                if registry.get("work_item_status") is None:
                    registry.register(
                        WorkItemStatusTool(runtime=runtime),
                        provider="AD-1209",
                        tags=["work_item_status", "tasks"],
                    )
                status_ids = ["work_item_status"]
            except Exception:
                logger.warning(
                    "AD-1209: failed to register/offer the work_item_status tool "
                    "for agent %s; continuing without it — a status question may "
                    "restart the work it is asking about",
                    agent_id, exc_info=True,
                )
                status_ids = []

        # AD-1226 (#1197): let the agent READ BACK something it produced. The
        # episode carries a content-addressable ref, not a copy, so "what was in
        # that list you sent me?" is answerable without the text ever having
        # been carried in context -- and without producing it a second time.
        # Measured 2026-08-08: a correctly delivered fifteen-row table, and four
        # minutes later the agent reporting that it could not see what it had
        # sent. Read-only and ownership-scoped. Flag-gated AND store-gated:
        # without the attachment store there is nothing to read back, and an
        # offer pointing at nothing is worse than no offer. Registered
        # idempotently, mirroring the AD-1209 block above.
        recall_ids: list[str] = []
        _memory_cfg = getattr(getattr(runtime, "config", None), "memory", None)
        if (
            getattr(_memory_cfg, "recall_outcome_refs_enabled", False)
            and getattr(runtime, "attachment_store", None) is not None
            and registry is not None
        ):
            try:
                from probos.tools.recall_artifact_tool import RecallArtifactTool

                if registry.get("recall_artifact") is None:
                    registry.register(
                        RecallArtifactTool(runtime=runtime),
                        provider="AD-1226",
                        tags=["recall_artifact", "artifacts"],
                    )
                recall_ids = ["recall_artifact"]
            except Exception:
                logger.warning(
                    "AD-1226: failed to register/offer the recall_artifact tool "
                    "for agent %s; continuing without it — a question about the "
                    "agent's own earlier output may be answered from "
                    "recollection or by redoing the work",
                    agent_id, exc_info=True,
                )
                recall_ids = []

        # AD-1072: the conversational-loop discovery + delegation tools, both
        # default-OFF (config.agentic_tools). With both flags off this whole
        # section is inert and ``tool_ids`` is byte-identical to the AD-1068 set.
        agentic_tools_cfg = getattr(
            getattr(runtime, "config", None), "agentic_tools", None
        )

        # AD-1072: offer the read-only capability-search tool when enabled. It
        # lets the agent discover tools / skills / mesh-intents by keyword before
        # acting, instead of confabulating a verb (BF-651 / AD-1064). Registered
        # idempotently (mirrors the AD-1066/1068 blocks); read-only.
        search_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "tool_search_enabled", False)
            and registry is not None
        ):
            try:
                from probos.tools.search_capabilities_tool import (
                    SearchCapabilitiesTool,
                )

                if registry.get("search_capabilities") is None:
                    registry.register(
                        SearchCapabilitiesTool(runtime=runtime),
                        provider="AD-1072",
                        tags=["search_capabilities", "discovery"],
                    )
                search_ids = ["search_capabilities"]
            except Exception:
                logger.warning(
                    "AD-1072: failed to register/offer the search_capabilities "
                    "tool for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                search_ids = []

        # AD-1072: offer the delegation tool when enabled. It hands a bounded
        # subtask to another crew agent by callsign, routed through THIS same
        # governed executor (so the delegate's tool permissions / consensus gates
        # / tool-trace all apply). Bounded by delegation_max_depth (recursion
        # guard) + delegation_max_iterations. The tool reuses the parent
        # executor's own LLM client (self._llm). Registered idempotently.
        delegate_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "delegation_enabled", False)
            and registry is not None
        ):
            try:
                from probos.tools.delegate_task_tool import DelegateTaskTool

                if registry.get("delegate_task") is None:
                    registry.register(
                        DelegateTaskTool(
                            runtime=runtime,
                            llm_client=self._llm,
                            max_depth=getattr(
                                agentic_tools_cfg, "delegation_max_depth", 1
                            ),
                            max_iterations=getattr(
                                agentic_tools_cfg, "delegation_max_iterations", 5
                            ),
                            tier=getattr(
                                agentic_tools_cfg, "delegation_tier", "standard"
                            ),
                        ),
                        provider="AD-1072",
                        tags=["delegate_task", "delegation"],
                    )
                delegate_ids = ["delegate_task"]
            except Exception:
                logger.warning(
                    "AD-1072: failed to register/offer the delegate_task tool "
                    "for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                delegate_ids = []

        event_log_ids: list[str] = []
        if registry is not None and registry.get("event_log_query") is not None:
            if registry.check_permission(
                agent_id,
                "event_log_query",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                event_log_ids = ["event_log_query"]

        # AD-1139: offer the read-only Oracle consult tool when startup
        # registered it (default-OFF via config.agentic_tools). It lets the
        # agent reach the ship's shared knowledge commons — Σ tiers only, never
        # the sovereign episodic shard — mid-task, instead of only receiving
        # Oracle context passively during perceive. Permission-checked, and an
        # agent whose department/rank is denied simply does not see the tool
        # (silent honest-degrade, mirroring the event_log_query block above).
        oracle_ids: list[str] = []
        if registry is not None and registry.get("oracle_query") is not None:
            if registry.check_permission(
                agent_id,
                "oracle_query",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                oracle_ids = ["oracle_query"]

        # AD-1140: offer the commons-write tool when startup registered it
        # (default-OFF via config.agentic_tools). It is the write half of Σ —
        # the agent records a finding into Ship's Records so a different agent
        # in a later session reaches it through ``oracle_query``. WRITE-level,
        # and an agent whose department/rank is denied simply does not see the
        # tool (silent honest-degrade, mirroring the two blocks above).
        publish_ids: list[str] = []
        if registry is not None and registry.get("publish_finding") is not None:
            if registry.check_permission(
                agent_id,
                "publish_finding",
                ToolPermission.WRITE,
                agent_department=department,
                agent_rank=rank,
            ):
                publish_ids = ["publish_finding"]

        # AD-1153: offer the browser READ-ONLY (default-OFF via
        # config.agentic_tools.browser_enabled). Two flags, one AND: the config
        # gate plus ``registry.get("browser")``, which already carries
        # ``browser_tool.enabled`` and the Playwright-import check from
        # ``_wire_browser_tool`` — so the availability logic is not re-derived
        # here. Permission-checked at READ, which is exactly what
        # ``check_and_invoke`` requires at invoke time, so an offered agent is an
        # invoking agent. The registered rank matrix keeps ``ensign: none``
        # (DD-2): rank is trust-derived, so that denies the browser precisely to
        # agents that are new, self-designed or currently failing. Denied ⇒ the
        # tool is silently absent (honest-degrade, mirroring the blocks above).
        #
        # NOTE for AD-1154 (#1081): admitting ``click`` / ``type`` here makes the
        # tier-3 path reachable, and BF-682 (the raw confirmation token in the
        # TOOL_INTERVENTION_REQUIRED payload) becomes a precondition to close
        # first. No action in ``_BROWSER_LOOP_ACTIONS`` can reach tier 3, so no
        # token is minted on this path today.
        browser_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "browser_enabled", False)
            and registry is not None
            and registry.get("browser") is not None
        ):
            if registry.check_permission(
                agent_id,
                "browser",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                browser_ids = ["browser"]
                self._warn_once_on_open_browser_egress(runtime)

        # AD-1153 / DD-1: arm the read-only guard ONLY when the tool reached the
        # loop through the block above AND the agent does not already hold it
        # through a Captain grant. An agent can hold ``browser`` by both routes;
        # narrowing the grant path would silently revoke a working capability and
        # invert Layer 4's grant-UP semantics (``browser`` is deliberately NOT in
        # ``_GATED_TOOL_IDS`` — it carries no ``allowed_departments``, so the
        # gate would have nothing to protect and would only remove the Captain's
        # escape hatch for probationary agents).
        # BF-690: one decision, two consequences. The condition that arms the
        # invoke-time guard also narrows the schema the agent is offered, so the
        # advertised action set and the permitted action set cannot disagree.
        # ``None`` = unarmed = the offer is passed through verbatim.
        restricted_browser_actions: frozenset[str] | None = None
        if browser_ids and "browser" not in granted_ids:
            restricted_browser_actions = _BROWSER_LOOP_ACTIONS
            executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)

        # AD-1154: arm the approval inbox on the same seam. Default-OFF via
        # ``config.approval_inbox.enabled``; off ⇒ ``_approval_inbox`` stays
        # None and ``invoke`` is byte-identical to AD-1153. Armed only when the
        # request store is actually wired, because an inbox with nowhere to file
        # would refuse every tier-3 action without recording it — a strictly
        # worse outcome than today's gate. ``action_approval_store`` may be None:
        # standing rules are a separate flag and an absent store simply means no
        # rule can match, which is the fail-closed direction.
        approval_cfg = getattr(
            getattr(runtime, "config", None), "approval_inbox", None
        )
        capability_request_store = getattr(runtime, "capability_request_store", None)
        if (
            getattr(approval_cfg, "enabled", False)
            and capability_request_store is not None
        ):
            executor.arm_approval_inbox(
                request_store=capability_request_store,
                approval_store=getattr(runtime, "action_approval_store", None),
                config=approval_cfg,
            )

        tool_ids = list(
            dict.fromkeys([
                *granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids,
                *status_ids, *recall_ids,
                *search_ids, *delegate_ids, *event_log_ids, *oracle_ids,
                *publish_ids, *browser_ids,
            ])
        )
        # BF-755: the non-MCP half, so a mid-turn refresh can REBUILD the MCP
        # half from the current authorized view rather than unioning onto the
        # old one. An append-only merge could never drop a tool whose server was
        # disabled or whose grant was revoked mid-turn.
        _mcp_id_set = set(mcp_ids)
        non_mcp_ids = [t for t in tool_ids if t not in _mcp_id_set]

        tools: list[dict] = []
        # AD-1248: one scope for this whole run, so every pass of a turn shares
        # it and a continuation supersedes its own earlier calls. Root == scope
        # here because these are the execution's OWN calls; a delegated child
        # inherits this root under a fresh scope.
        _failure_scope = (
            scope_from_source(failure_scope) if failure_scope else mint_scope()
        )
        # AD-1163: resolved once, before the loop, so the browser offer can name
        # the Captain's open page. AD-1158/1162 made the binding WORK; this is
        # what makes the agent aware it exists.
        _captain_row = _captain_browser_session(runtime)

        offered_names: set[str] = set()

        def _build_tools(ids: list[str]) -> list[dict]:
            """BF-755: assemble the offer for *ids*. Extracted so the same
            assembly can run again mid-turn when discovery changes the set --
            two assemblies that could drift is the shape this repo keeps
            producing, so there is exactly one."""
            built: list[dict] = []
            if registry is None:
                return built
            for tid in ids:
                reg = registry.get(tid)
                if reg is None:
                    continue
                definition = tool_registration_to_llm_definition(reg)
                # BF-690: only the restricted browser offer is rewritten; every
                # other tool, and an unarmed browser, is byte-identical.
                if tid == "browser" and restricted_browser_actions is not None:
                    definition = _narrow_browser_offer(
                        definition, restricted_browser_actions
                    )
                if tid == "browser" and _captain_row is not None:
                    definition = _announce_shared_session(definition, _captain_row)
                    # AD-1163a: record what the agent was ACTUALLY told. Twice
                    # now the binding logged as present while the agent made
                    # zero tool calls, and the gap between "we wired it" and
                    # "the model saw it" was unobservable. Log the offered
                    # description verbatim so that gap is readable instead of
                    # inferred.
                    logger.info(
                        "AD-1163: browser offered to %s with description: %s",
                        agent_id,
                        (definition.get("function") or {}).get("description", ""),
                    )
                built.append(definition)
            # BF-757: last gate before the provider. A duplicate function name
            # makes it reject the WHOLE request, so one collision would cost the
            # agent every tool rather than the one.
            deduped = dedupe_llm_definitions(built, agent_id=agent_id)
            # AD-1248 / DD-1a: record what the model was ACTUALLY offered, POST
            # dedupe -- a pre-dedupe capture names tools that were never sent.
            # Accumulated because BF-755 can re-offer mid-turn, so a single
            # snapshot would miss a tool the agent really did call.
            for _definition in deduped:
                _offered = (_definition.get("function") or {}).get("name")
                if isinstance(_offered, str) and _offered:
                    offered_names.add(_offered)
            return deduped

        tools = _build_tools(tool_ids)

        def _refresh_tools() -> list[dict] | None:
            """BF-755: re-offer after discovery pulled a tool onto the workbench.

            ``dispatch_tool_ids`` is the SAME authorized view used to build the
            initial offer, so a tool can only appear here if the agent was
            already allowed to have it -- discovery widens what is *visible*,
            never what is *permitted*.
            """
            if workbench is None or not mcp_offer_armed:
                return None
            try:
                current = workbench.dispatch_tool_ids(agent_id)
            except Exception:
                # WARNING, not DEBUG: the tool the agent just found becomes
                # uncallable for the rest of the turn. That is a visible
                # degradation, and at DEBUG it is invisible at the default
                # console level.
                logger.warning(
                    "BF-755: could not re-read the workbench for %s; keeping "
                    "the offer as assembled, so a tool discovered this turn "
                    "stays uncallable until the next one",
                    agent_id[:12], exc_info=True,
                )
                return None
            merged = list(dict.fromkeys([*non_mcp_ids, *current]))
            if merged == tool_ids:
                return None
            tool_ids[:] = merged
            return _build_tools(merged)

        # AD-1065: the conversational chat path passes a lower iteration cap +
        # a faster tier than the task-path defaults (25 / deep). When both are
        # None (the AD-839/859 task callers) the AgenticLoop defaults are used,
        # so the task path is byte-identical.
        _loop_kwargs: dict[str, Any] = {}
        if max_iterations is not None:
            _loop_kwargs["max_iterations"] = max_iterations
        if tier is not None:
            _loop_kwargs["tier"] = tier
        # AD-1142: threaded the same way, so a caller that passes none of them
        # (every non-crew caller, and the crew path with the gate off) builds a
        # byte-identical kwarg dict — same keys, same order.
        if compactor is not None:
            _loop_kwargs["compactor"] = compactor
        if compaction_threshold is not None:
            _loop_kwargs["compaction_threshold"] = compaction_threshold
        if token_budget is not None:
            _loop_kwargs["token_budget"] = token_budget
        # BF-731: same additive shape. Absent => the kwarg is never passed to
        # AgenticLoop, which in turn never passes it to complete(), so the task
        # path and every test double keep the exact call they had before.
        if priority is not None:
            _loop_kwargs["priority"] = priority
        # BF-755: a tool the agent finds mid-turn becomes callable in that turn.
        # Only passed when the MCP offer itself was armed -- an unarmed vessel
        # never receives the kwarg, so its construction is byte-identical and
        # every test double pinning the old signature keeps working (the BF-678
        # class).
        if mcp_offer_armed:
            _loop_kwargs["refresh_tools"] = _refresh_tools
        # AD-1146: opt into the provider's real multi-turn message array
        # (assistant.tool_calls + role:"tool" results). Default-OFF — with the
        # flag off the loop builds the AD-545 flattened prompt verbatim. Read
        # defensively so synthetic/event-neutral runtimes without a config still
        # construct the loop.
        _agentic_loop_cfg = getattr(
            getattr(runtime, "config", None), "agentic_loop", None
        )
        loop = AgenticLoop(
            llm_client=self._llm,
            tool_executor=executor,
            event_emit_fn=getattr(runtime, "emit_event", None),
            structured_tool_messages=bool(
                getattr(_agentic_loop_cfg, "structured_tool_messages", False)
            ),
            # AD-1148: bound each tool result before it enters the loop's
            # message history. 0 = unbounded (default-OFF), so message content
            # is byte-identical until an operator opts in.
            **resolve_tool_result_bounds(_agentic_loop_cfg),
            # AD-1147: fan the read-only allowlisted tool calls of one response
            # out concurrently, bounded. Default-OFF — the sequential AD-545
            # path runs verbatim until an operator opts in.
            **resolve_parallel_tool_settings(_agentic_loop_cfg),
            **_loop_kwargs,
        )
        # AD-1129: accepted compatibility extras are copied first; the run's
        # authoritative identity and explicit thread provenance always win.
        _context.update(
            {
                "agent_id": agent_id,
                "department": department,
                "rank": rank,
                "thread_id": thread_id,
            }
        )
        # AD-1162: supply the key AD-1158 reads. Without a producer, every agent
        # browser call created a fresh signed-out session while the Captain
        # watched a different one. Bound only when the Captain actually has a
        # live session; absent, the key is omitted and behaviour is AD-1158's.
        _captain_session = _captain_browser_session_id(runtime)
        if _captain_session is not None:
            _context["browser_session_id"] = _captain_session
            logger.info(
                "AD-1162: binding agent %s to the Captain's browser session %s; "
                "browser calls without an explicit session_id will act on the "
                "page the Captain is watching.",
                agent_id, _captain_session[:12],
            )
        elif browser_ids:
            # AD-1163: the ABSENCE is the diagnostic. Without this line the only
            # evidence is a missing INFO, which is invisible unless you already
            # suspect it. If the Captain says "the document I have open" and no
            # session is bound, the agent works on a page the Captain cannot see.
            logger.info(
                "AD-1162: agent %s was offered the browser with NO Captain "
                "session bound; calls without an explicit session_id will create "
                "a fresh, signed-out browser rather than acting on the Captain's "
                "page. Expected when the Captain has not opened one; unexpected "
                "if they are watching a session right now.",
                agent_id,
            )
        # AD-1180: compose the shared disposition at the ONE choke point every
        # agentic path already flows through, instead of duplicating prose into
        # five call sites. Composed AFTER ``instructions`` for three reasons:
        # (1) the conversational path's AD-1177 hook appends it exactly this way
        # (``composed += _agentic_self_desc`` in ``_decide_via_llm``), so all
        # five paths now produce an identically shaped prompt; (2) the constant
        # is authored as a SUFFIX -- it opens with its own blank-line separator
        # and ends mid-thought with none, so a prefix placement would glue its
        # last sentence onto the agent's first line; (3) identity and standing
        # orders are the frame, and the operating disposition belongs closest to
        # the task.
        #
        # Default-OFF: with ``disposition_enabled`` False this is exactly
        # ``instructions or ""`` -- the pre-AD-1180 expression, unchanged, for
        # BOTH values of ``compose_disposition``.
        _system_prompt = instructions or ""
        if compose_disposition and getattr(
            agentic_tools_cfg, "disposition_enabled", False
        ):
            _system_prompt = f"{_system_prompt}{AGENTIC_DISPOSITION}"

        agentic_result = await loop.run(
            system_prompt=_system_prompt,
            user_message=task_text,
            tools=tools,
            context=_context,
        )

        # AD-1279: built ONCE and handed to both the trace writer below and
        # the detector at the end of this method. Two calls would close over
        # the same registry and answer identically today, but one object makes
        # "the writer and the detector cannot disagree" structural rather than
        # incidental -- and the whole point of signing the trace is that a
        # reader can trust the digest it finds there.
        _fault_tool_id_resolver = _tool_id_resolver(registry)

        tool_trace_ref = await self._persist_tool_trace(
            agentic_result, runtime, agent_id,
            resolve_tool_id=_fault_tool_id_resolver,
        )
        artifact_refs, ignored_artifact_entries = _extract_artifact_refs(
            observed_tool_results,
            thread_id=thread_id,
        )
        if ignored_artifact_entries:
            logger.warning(
                "AD-1125: dropped %d malformed, duplicate, cross-thread, or "
                "over-limit artifact evidence entries for agent %s in thread %s; "
                "continuing with %d validated refs",
                ignored_artifact_entries,
                agent_id,
                thread_id or "<none>",
                len(artifact_refs),
            )
        raw_total_tokens = getattr(agentic_result, "total_tokens", 0)
        total_tokens = (
            raw_total_tokens
            if type(raw_total_tokens) is int and raw_total_tokens >= 0
            else 0
        )
        if total_tokens != raw_total_tokens:
            logger.warning(
                "AD-1125: agentic result for agent %s carried an invalid token "
                "total; recording zero so downstream evidence remains bounded",
                agent_id,
            )
        # BF-680: the loop substitutes a client-side estimate when the provider
        # reports no usage. Surface that here, correlated to the agent and
        # thread, because the ``crew_execution`` record this total lands in is a
        # frozen 14-key set with nowhere to say it.
        token_source = getattr(
            agentic_result, "token_source", TOKEN_SOURCE_MEASURED
        )
        if token_source != TOKEN_SOURCE_MEASURED:
            logger.warning(
                "BF-680: token total %d for agent %s in thread %s is %s, not a "
                "provider measurement; downstream cost evidence records it as "
                "a bare int and cannot distinguish the two",
                total_tokens,
                agent_id,
                thread_id or "<none>",
                token_source,
            )

        return WorkItemAgenticOutcome(
            final_text=agentic_result.final_text or "",
            stopped_reason=agentic_result.stopped_reason,
            denied_tools=list(executor.denied_tools),
            tool_trace_ref=tool_trace_ref,
            total_tokens=total_tokens,
            artifact_refs=artifact_refs,
            token_source=token_source,
            # AD-1248: correlated HERE because this is the only scope holding
            # the raw call/result pairs -- ``WorkItemAgenticOutcome`` is the
            # projection callers see, and the pairs do not survive it.
            tool_failures=correlate_tool_outcomes(
                agentic_result,
                root=_failure_scope,
                scope=_failure_scope,
                known_tools=offered_names,
                excluded_tools=executor.denied_tools,
            ),
            # AD-1257: same scope, same reason. BF-793 -- the detector's only
            # production caller was handed this projection, which carries
            # neither list, so it returned None on every DM turn no matter how
            # often a tool had failed. Pure data: ``run()`` serves five callers
            # and none of them is forced to act on this.
            tool_defect=detect_tool_defect(
                agentic_result, resolve_tool_id=_fault_tool_id_resolver,
            ),
            # AD-1269: says "the pairs were read here", which is the only thing
            # that distinguishes a verdict of None from a field nobody set.
            tool_defect_evaluated=True,
        )

    async def _persist_tool_trace(
        self,
        agentic_result: Any,
        runtime: Any,
        agent_id: str,
        *,
        resolve_tool_id: Callable[[str], str] | None = None,
    ) -> str | None:
        """Persist the loop's tool calls AND their outputs; return the SHA ref.

        AD-1151: the blob records each tool's output, not just that it was
        called, so the durable trace matches the Nooplex §3.3 Transparency
        guarantee that AD-1142 and AD-1148 both cited. The shape is
        unchanged for existing readers — still a bare JSON array, still carrying
        every ``ToolCallRequest`` key — so versioning is by key presence.

        BF-760: for a STRUCTURED tool result the recorded output is the BF-728
        context rendering rather than what the tool returned, because the
        rendering happens before the result reaches the loop. The entry carries
        ``source_chars`` so the loss is visible; retaining the value itself is
        AD-1240 (#1239).

        AD-1279: ``resolve_tool_id`` is the SAME object the detector is given,
        so the identity written onto an error entry and the identity the fault
        row is keyed on cannot disagree. It stays inside the existing
        ``except``: ``canonical_tool_id`` degrades to the observed name, so a
        raising resolver must still produce a full trace.

        Honest-degrade to ``None`` (log a warning) when the store is unwired or
        the write fails — the trace ref is provenance, not correctness, so a
        missing store must not fail the dispatch (AD-731 / log-and-degrade tier).
        The payload shaping sits inside the same ``try`` so a malformed result
        degrades identically rather than failing the dispatch.
        """
        try:
            store = getattr(runtime, "attachment_store", None)
        except Exception:
            logger.warning(
                "AD-859a: attachment_store accessor raised while persisting the "
                "tool trace for agent %s; tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
        if store is None:
            return None
        try:
            # Function-local, matching the AgenticLoop import at the top of
            # ``run``. There is no module cycle to work around here, but the
            # locality is load-bearing anyway: tests monkeypatch names on
            # ``swe_harness.agentic_loop`` itself, which only takes effect when
            # this module resolves them at call time.
            from probos.cognitive.swe_harness.agentic_loop import (
                build_tool_trace_payload,
                resolve_tool_trace_bounds,
            )

            bounds = resolve_tool_trace_bounds(
                getattr(getattr(runtime, "config", None), "agentic_loop", None)
            )
            _entries, blob = build_tool_trace_payload(
                getattr(agentic_result, "tool_calls", []),
                getattr(agentic_result, "tool_results", []),
                resolve_tool_id=resolve_tool_id,
                **bounds,
            )
            blob_max_bytes = bounds["blob_max_bytes"]
            if blob_max_bytes and len(blob) > blob_max_bytes:
                # AD-1151 / DD-5: every output has already been elided and the
                # call records alone still exceed the cap. Persist them anyway —
                # dropping request records to save bytes would regress the
                # guarantee this trace exists to provide.
                logger.warning(
                    "AD-1151: tool trace for agent %s is %d bytes after eliding "
                    "every output, over the %d-byte cap; persisting the call "
                    "records anyway so the provenance record is not lost",
                    agent_id, len(blob), blob_max_bytes,
                )
            content_hash = hashlib.sha256(blob).hexdigest()
            await store.write(
                content_hash=content_hash,
                blob=blob,
                mime="application/json",
                origin="crew_trace",
            )
            return content_hash
        except Exception:
            logger.warning(
                "AD-859a: failed to persist the tool trace for agent %s; "
                "tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
