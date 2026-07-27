"""AD-1140: ``publish_finding`` — a crew agent's write into the durable commons.

AD-1139 gave an agent the *read* half of Σ. This is the write half: one governed
verb for putting a worked-out finding into Ship's Records, so a **different**
agent in a **different** session can retrieve it through ``oracle_query``. That
round trip is what makes this Σ (a shared commons) rather than Ω (one agent's
private notes).

**DD-1 — the governance instrument is a department gate plus bounds, not
consensus and not a rank floor.** A publish is additive and fully reversible
(git history, ``_archived/``, ``publish()`` status promotion), so the
Reversibility Preference axiom is already satisfied; ProbOS consensus gates
*destructive* operations, and no consensus seam exists on the native-tool path.
The real risk is volume and quality pollution, which a per-claim quorum vote
would not bind anyway. ``ensign`` holds ``write`` upward because the crew
children this exists for are ensigns — so the DD-7 bounds below are
load-bearing: they are the only thing between a looping agent and an unbounded
git repo.

**DD-2 — framing is inline (load-bearing).** ``AgenticLoop`` renders a tool
result as bare content; there is no consumer-side wrapper. So every confirmation
carries its own parenthetical disposition, in the shape ``_ORACLE_DISPOSITION``
(AD-1139) and ``_VISUAL_DISPOSITION`` (AD-1059) established. Every string this
module authors is checked in the tests against the real
``probos.cognitive.decomposer._CAPABILITY_GAP_RE`` — a confirmation that tripped
that regex would be mistaken for the LLM reporting a capability gap and would
spuriously trigger self-modification.

**DD-3 — the envelope is split.** The claim *text* is the markdown body, so the
AD-550 dedup Jaccard, ``RecordsStore.search``'s keyword match and the AD-1138
embedding all see the substance. The *envelope* is YAML frontmatter, so it
round-trips through ``_parse_document`` and lands whole in AD-1138's
``frontmatter_json`` sidecar. Provenance fields are system-owned and are
**rejected** rather than dropped when supplied — silently dropping an ``author``
key would let an agent believe it stamped provenance it did not.

**DD-4 — ``fleet`` is accepted, recorded, and written at ``ship`` scope.** Both
Oracle Tier 2 paths query Ship's Records at ``_RECORDS_QUERY_SCOPE = "ship"``,
and ``fleet`` is level 3 against ``ship``'s level 2, so a faithful
``classification: fleet`` write would be durable, committed, indexed — and
reachable by nobody on this node, including its author. The tool therefore
writes ``classification: ship`` and stamps ``requested_scope: fleet``, and the
confirmation says exactly that. No node boundary is crossed here and nothing
under ``probos.federation`` is imported.

**DD-5 — the write lands in ``notebooks/{callsign}/`` through
``write_notebook``.** A dedicated ``claims/`` subdir would route around every
curation guard: AD-550 dedup hard-codes ``notebooks/{callsign}/*.md``, AD-554
convergence iterates ``notebooks/*/``, AD-555 quality reads
``list_entries("notebooks")``. AD-1138 indexing already lives *inside*
``write_entry``, so a publish is auto-indexed with no extra wiring.

**DD-8 — sovereignty.** This module imports, references and reaches **no**
episodic surface. Σ is the commons; the sovereign per-agent shard (AD-397 /
AD-607e) is a different Nooplex letter and is untouched. Enforced structurally
by constructor injection — the tool receives a records store, a callsign
resolver, its bounds and a node id, and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import deque
from typing import Any

from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)

# DD-3: schema version for the envelope. A later migration keys off this.
CLAIM_VERSION = 1

# DD-9: reserved system tag on every published claim, so curation and later
# analysis can separate agent-published claims from proactive-loop notebook
# entries without parsing frontmatter. Counts against the tag budget as a
# system tag, not an agent one.
FINDING_TAG = "finding"

# DD-3/DD-7: the complete accepted parameter set. Anything else is rejected
# (not dropped) — see ``_ALLOWED_KEYS`` handling in :meth:`invoke`.
_ALLOWED_KEYS = frozenset(
    {"title", "claim", "basis", "confidence", "classification", "tags"}
)

# DD-4: the classification vocabulary, mirroring
# ``records_store._CLASSIFICATION_LEVELS``. Imported rather than re-typed at
# validation time so the two cannot drift.
_DEFAULT_CLASSIFICATION = "ship"
_FLEET_CLASSIFICATION = "fleet"
# DD-4: what a ``fleet`` request is actually written as, so Tier 2 can reach it.
_FLEET_WRITE_CLASSIFICATION = "ship"

# DD-7 bounds.
_MAX_TITLE_CHARS = 200
_MAX_BASIS_CHARS = 1000
_MAX_TAGS = 8
_MAX_TAG_CHARS = 32
_MAX_SLUG_CHARS = 48
# The rate-limiter deque is hard-capped so a flood cannot grow it without
# bound; the per-author budget is checked against the pruned window.
_RATE_WINDOW_SECONDS = 3600.0
_MAX_TRACKED_AUTHORS = 256
# Final bound on the confirmation text handed back to the loop.
_MAX_OUTPUT_CHARS = 2000

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# DD-7: the callsign becomes a **directory name**. A ``/`` would nest it out of
# ``check_notebook_similarity``'s flat ``notebooks/{callsign}/*.md`` glob and
# out of ``check_cross_agent_convergence``'s one-level ``iterdir``, so the entry
# would fall out of both curation guards while still being written.
# ``_safe_path`` blocks traversal but not nesting, so this fails closed.
_CALLSIGN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _slugify(title: str) -> str:
    """Reduce a title to the slug charset, mirroring ``skill_framework._slugify``."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return slug[:_MAX_SLUG_CHARS]


def compute_claim_id(title: str, claim: str, basis: str) -> str:
    """DD-3: content-addressed identity over the canonical claim triple.

    Canonical JSON with sorted keys, so the same ``{title, claim, basis}``
    always hashes to the same id regardless of parameter order, and any change
    to any of the three produces a different one.
    """
    canonical = json.dumps(
        {"title": title, "claim": claim, "basis": basis},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── DD-2: authored strings. All checked against the real gap regex in tests. ──

_HEADER = "## Ship's Records — Knowledge Claim"

_SUCCESS_DISPOSITION: str = (
    "(Recorded in Ship's Records as a knowledge claim at {classification} "
    "scope. Other crew reach it through a commons query in a later session. "
    "Do not narrate this publication; cite the claim if you build on it.)"
)

# DD-4: the fleet confirmation is truthful about what actually happened — the
# claim was written at ship scope and marked for onward distribution, because a
# record written at fleet scope would sit outside every Tier 2 query on this
# node.
_FLEET_DISPOSITION: str = (
    "(Recorded at ship scope and marked for fleet distribution. Crew on this "
    "ship reach it now; a fleet transport carries it onward once one is "
    "configured.)"
)

_DUPLICATE_DISPOSITION: str = (
    "(This finding matches an entry already in Ship's Records at {path}. The "
    "existing entry stands and nothing further was written. Continue with the "
    "task.)"
)

_RATE_LIMITED_DISPOSITION: str = (
    "(This agent has reached its publication budget for the current hour. The "
    "finding stays in working context; publish it again later if it still "
    "matters.)"
)

# AD-1141 DD-6: the ship-wide refusal. Distinct wording from the per-author
# refusal above because telling an agent it hit its *personal* limit when the
# ship budget refused it is simply false, and a false explanation is what sends
# an agent into the retry loop the limiter exists to absorb.
_SHIP_RATE_LIMITED_DISPOSITION: str = (
    "(The ship has reached its publication budget for the current hour. Keep "
    "the finding in your output; record it in a later session if it still "
    "matters.)"
)

_TOOL_DESCRIPTION: str = (
    "Record a finding you have worked out into Ship's Records, so other crew "
    "reach it in a later session through a commons query. Supply the claim "
    "itself, the basis you believe it on, and a confidence between 0 and 1. "
    "Authorship, department, timestamps and the claim identity are stamped by "
    "the ship. Publish a durable, reusable conclusion — a restatement of the "
    "task, or a step-by-step narration of what you just did, belongs in your "
    "answer instead. A finding reaches the whole ship by default; narrow its "
    "classification only when that finding genuinely calls for it."
)

# AD-1140/DD-10: the scope-selection rule, carried on the parameter itself.
#
# ``input_schema`` is handed to the provider verbatim as the ``parameters``
# block (``swe_harness.tool_call.tool_registration_to_llm_definition``), so a
# parameter description is read by the model at the moment it fills the call
# in. That is the only surface guaranteed to be present at the point of
# decision: standing orders are composed per agent and a manual has to be
# *retrieved*, which makes policy compliance depend on a retrieval hit.
#
# Two properties are load-bearing:
#
# 1. **The burden of proof runs toward narrowing, not broadening.** A commons
#    that defaults to a private scope is a commons in name only, and the cost
#    of the mistake is asymmetric — a finding filed too wide is noise a reader
#    skips, while a finding filed too narrow is invisible to the crew member
#    who needed it and stays invisible forever. So each narrower value states
#    the *test* that admits it rather than describing the audience, because an
#    audience description invites an agent to reason about who might care
#    (unbounded, unfalsifiable) instead of whether a stated condition holds.
#
# 2. **Uncertainty is routed to ``confidence``, explicitly.** The two fields
#    are orthogonal — one is how strongly the claim is held, the other is who
#    retrieves it — but they collapse under an agent that feels unsure and
#    reaches for the nearest instrument of caution. Left unstated, the reliable
#    failure is a well-founded tentative finding filed ``private``, where the
#    calibration signal it carries is worth the most and reaches nobody.
#
# Module-level by construction: the DD-2 gap-regex sweep in the AD-1140 tests
# collects module-level ``str`` values, so text left inline in the schema
# property would sit outside that guard.
_CLASSIFICATION_GUIDANCE: str = (
    "Who should reach this finding. Default to 'ship'; choose a narrower "
    "scope only when one of these tests actually holds, because a finding "
    "filed narrow is one the rest of the crew never sees. "
    "'ship' — any crew member could act on it, or read it without your "
    "department's context; when the choice is unclear, this is the answer. "
    "'department' — reading it correctly depends on department-specific "
    "context, instruments or duty, such that another department would misread "
    "it; choose this for that reason, never merely because the finding arose "
    "from your own duty. "
    "'private' — a working note you are still forming, rather than a finding "
    "another crew member should build on. "
    "'fleet' — it concerns other vessels rather than this one. "
    "Carry uncertainty in 'confidence', never by narrowing the scope: a "
    "tentative finding belongs at ship scope with a low confidence."
)


class PublishFindingTool:
    """Governed agent write into the durable knowledge commons.

    Satisfies the AD-423a ``Tool`` protocol structurally — no inheritance,
    mirroring :class:`probos.tools.oracle_query_tool.OracleQueryTool`.

    Constructor injection only (DIP, and DD-8's structural sovereignty
    guarantee): the tool holds a records store, a callsign resolver, its bounds
    and the node id. It has no runtime handle and therefore no path to the
    episodic shard.

    Args:
        records_store: duck-typed ``RecordsStore`` — needs ``write_notebook``
            and ``check_notebook_similarity``.
        callsign_resolver: ``agent_id -> (callsign, department)``. In production
            this is
            :func:`probos.cognitive.oracle_service.make_reader_identity_resolver`,
            which is the same translation the BF-679 read path uses, so an
            agent authors and later reads its own records under one identity.
        source_node: this node's federation id. Written into the envelope as
            the field a later fleet transport routes on; nothing in this AD
            reads it back.
        max_per_hour: DD-7 per-author publication budget.
        max_per_hour_ship: AD-1141 DD-6 ship-wide publication budget, checked
            **before** the per-author budget. Per-author limiting does not
            bound ship-wide write volume at all, and AD-1141 is what creates a
            fan-out of concurrent authors. The registry holds one tool
            instance, so this instance's window *is* the ship's window.
            **This bounds the write RATE, not the near-duplicate scan's window
            population**: 40/hr against a 72-hour staleness window admits far
            more entries than ``max_scan_entries`` examines, so it does not
            make AD-550 dedup sound and must not be read as doing so.
        max_content_chars: DD-7 claim-body cap. Matches ``semantic._RECORD_DOC_CHARS``
            so "what you publish is what is discoverable" is true rather than
            approximately true.
        quality_engine: optional AD-555 ``NotebookQualityEngine``. Degrades
            silently to ``None``.
        similarity_threshold / staleness_hours / max_scan_entries: AD-550 dedup
            tuning, passed straight through to ``check_notebook_similarity``.
    """

    def __init__(
        self,
        *,
        records_store: Any,
        callsign_resolver: Any,
        source_node: str = "",
        max_per_hour: int = 12,
        max_per_hour_ship: int = 40,
        max_content_chars: int = 4000,
        quality_engine: Any = None,
        similarity_threshold: float = 0.8,
        staleness_hours: float = 72.0,
        max_scan_entries: int = 20,
    ) -> None:
        self._records = records_store
        self._resolve_callsign = callsign_resolver
        self._source_node = source_node if type(source_node) is str else ""
        self._max_per_hour = max_per_hour
        self._max_per_hour_ship = max_per_hour_ship
        self._max_content_chars = max_content_chars
        self._quality = quality_engine
        self._similarity_threshold = similarity_threshold
        self._staleness_hours = staleness_hours
        self._max_scan_entries = max_scan_entries
        # DD-7: per-author monotonic publication timestamps. The registry holds
        # one tool instance, so this is the process-wide budget.
        self._publications: dict[str, deque[float]] = {}
        # AD-1141 DD-6: the ship-wide window, on the same instance and
        # therefore the same process-wide scope. ``maxlen`` keeps a burst from
        # growing it without bound.
        self._ship_publications: deque[float] = deque(maxlen=max(1, max_per_hour_ship))

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "publish_finding"

    @property
    def name(self) -> str:
        return "Publish Finding"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return _TOOL_DESCRIPTION

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "claim", "basis"],
            "properties": {
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_TITLE_CHARS,
                    "description": "A short heading naming the finding.",
                },
                "claim": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": self._max_content_chars,
                    "description": (
                        "The finding itself, written so a crew member who was "
                        "not on this task can act on it."
                    ),
                },
                "basis": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_BASIS_CHARS,
                    "description": (
                        "Why you believe it — what you observed, measured or "
                        "read that supports the claim."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.5,
                    "description": "How strongly you hold the claim, 0 to 1.",
                },
                "classification": {
                    "type": "string",
                    "enum": ["private", "department", "ship", "fleet"],
                    "default": _DEFAULT_CLASSIFICATION,
                    "description": _CLASSIFICATION_GUIDANCE,
                },
                "tags": {
                    "type": "array",
                    "maxItems": _MAX_TAGS - 1,
                    "items": {
                        "type": "string",
                        "maxLength": _MAX_TAG_CHARS,
                        "pattern": _TAG_RE.pattern,
                    },
                    "description": (
                        "Up to seven lowercase keywords for later retrieval."
                    ),
                },
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "description": (
                "A framed confirmation stating what was recorded, at what "
                "scope, and where other crew reach it."
            ),
        }

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        raw = params if type(params) is dict else {}
        ctx = context if type(context) is dict else {}

        # DD-3 anti-spoof: reject rather than drop. A dropped ``author`` key
        # would let the agent believe it stamped provenance it did not.
        if any(type(key) is not str or key not in _ALLOWED_KEYS for key in raw):
            return self._invalid("parameter", started)

        fields = self._validate(raw)
        if type(fields) is str:
            return self._invalid(fields, started)

        identity = self._resolve_identity(ctx)
        if identity is None:
            return self._invalid("author", started)
        callsign, department = identity

        # AD-1141 DD-6: the ship budget is checked BEFORE the per-author one.
        # Reversing them would tell a single author it had hit its *personal*
        # limit when the ship's budget is what refused it — a false explanation,
        # and the retry loop the limiter exists to absorb.
        if not self._admit_ship_publication():
            return self._refused(
                _SHIP_RATE_LIMITED_DISPOSITION, "ship_rate_limited", started,
            )

        if not self._admit_publication(callsign):
            return self._refused(
                _RATE_LIMITED_DISPOSITION, "rate_limited", started,
            )

        self._record_ship_publication()

        return await self._publish(
            fields=fields,
            callsign=callsign,
            department=department,
            ctx=ctx,
            started=started,
        )

    # ── Validation ────────────────────────────────────────────────
    def _validate(self, raw: dict[str, Any]) -> dict[str, Any] | str:
        """DD-7: bound every agent-supplied field. Returns a field name on failure.

        Strict ``type(x) is ...`` checks throughout, matching AD-1139's style:
        a ``bool`` is an ``int`` in Python, and an ``isinstance`` check on
        ``confidence`` would silently accept ``True`` as ``1.0``.
        """
        title = raw.get("title")
        if type(title) is not str:
            return "title"
        title = title.strip()
        if not title or len(title) > _MAX_TITLE_CHARS:
            return "title"
        if not _SLUG_RE.fullmatch(_slugify(title)):
            # DD-6: a title of pure punctuation slugifies to empty and would
            # produce an unaddressable path.
            return "title"

        claim = raw.get("claim")
        if type(claim) is not str:
            return "claim"
        claim = claim.strip()
        if not claim or len(claim) > self._max_content_chars:
            return "claim"

        basis = raw.get("basis")
        if type(basis) is not str:
            return "basis"
        basis = basis.strip()
        if not basis or len(basis) > _MAX_BASIS_CHARS:
            return "basis"

        confidence = raw.get("confidence", 0.5)
        if type(confidence) is int:
            confidence = float(confidence)
        if type(confidence) is not float:
            return "confidence"
        if not (0.0 <= confidence <= 1.0):
            return "confidence"

        classification = raw.get("classification", _DEFAULT_CLASSIFICATION)
        if type(classification) is not str:
            return "classification"
        from probos.knowledge.records_store import _CLASSIFICATION_LEVELS

        if classification not in _CLASSIFICATION_LEVELS:
            return "classification"

        raw_tags = raw.get("tags", [])
        if type(raw_tags) is not list:
            return "tags"
        # DD-9: the reserved system tag occupies one of the budgeted slots, so
        # an agent may supply at most _MAX_TAGS - 1.
        if len(raw_tags) > _MAX_TAGS - 1:
            return "tags"
        tags: list[str] = []
        for tag in raw_tags:
            if type(tag) is not str or len(tag) > _MAX_TAG_CHARS:
                return "tags"
            if not _TAG_RE.fullmatch(tag):
                return "tags"
            if tag != FINDING_TAG and tag not in tags:
                tags.append(tag)

        return {
            "title": title,
            "claim": claim,
            "basis": basis,
            "confidence": confidence,
            "classification": classification,
            "tags": [FINDING_TAG, *tags],
        }

    def _resolve_identity(self, ctx: dict[str, Any]) -> tuple[str, str] | None:
        """DD-3: resolve the system-owned author identity from the tool context.

        Never accepts an identity from ``params`` — authorship is the whole
        provenance claim, and spoofable authorship makes the envelope
        worthless.

        ``agent_id`` is stamped by ``ToolRegistry.check_and_invoke`` on every
        invocation, so it is always present on the governed path. The callsign
        resolver is the BF-679 ``agent_id -> (callsign, department)``
        translation, reused rather than duplicated so an agent authors under
        exactly the identity Tier 2 later resolves it back to.

        The department falls back to the context, which
        ``WorkItemAgenticExecutor.run`` sets authoritatively from
        ``_resolve_agentic_identity`` (verified empirically at the ``Tool.invoke``
        boundary: ``department``, ``agent_department``, ``_crew_session_id``
        and ``_crew_work_item_id`` all arrive). A department that resolves
        nowhere is written empty rather than guessed.
        """
        agent_id = ctx.get("agent_id")
        if type(agent_id) is not str or not agent_id:
            return None

        callsign = ""
        department = ""
        try:
            resolved = self._resolve_callsign(agent_id)
        except Exception:
            logger.warning(
                "AD-1140: callsign resolution raised for agent %s; refusing the "
                "publication rather than authoring it under an unproven identity",
                agent_id, exc_info=True,
            )
            return None
        if type(resolved) is tuple and len(resolved) == 2:
            raw_callsign, raw_department = resolved
            if type(raw_callsign) is str:
                callsign = raw_callsign
            if type(raw_department) is str:
                department = raw_department
        elif type(resolved) is str:
            callsign = resolved

        # DD-7: the callsign becomes a directory name — fail closed on anything
        # that would nest, traverse, or empty the path.
        if not _CALLSIGN_RE.fullmatch(callsign):
            logger.warning(
                "AD-1140: agent %s resolved to callsign %r, which is not a safe "
                "single directory name; refusing the publication so the entry "
                "cannot land outside the curation guards' flat notebook glob",
                agent_id, callsign,
            )
            return None

        if not department:
            for key in ("department", "agent_department"):
                candidate = ctx.get(key)
                if type(candidate) is str and candidate:
                    department = candidate
                    break
        return callsign, department

    # ── DD-7: rate limiting ───────────────────────────────────────
    def _admit_ship_publication(self) -> bool:
        """AD-1141 DD-6: prune the ship window and test capacity. Records nothing.

        Split from :meth:`_record_ship_publication` deliberately. The ship
        budget is tested first, but a call that then fails the per-author
        budget never happened, so it must not consume ship capacity — the
        timestamp is appended only once both budgets have admitted the call.

        Honest bound: this limits the ship's publication **rate**. It does not
        bound how many entries sit inside the AD-550 staleness window, so it
        does not make near-duplicate suppression sound.
        """
        now = time.monotonic()
        cutoff = now - _RATE_WINDOW_SECONDS
        while self._ship_publications and self._ship_publications[0] <= cutoff:
            self._ship_publications.popleft()
        if len(self._ship_publications) >= self._max_per_hour_ship:
            logger.info(
                "AD-1141: the ship reached its publication budget of %d per "
                "hour; the finding is refused without a write and stays in the "
                "agent's working context",
                self._max_per_hour_ship,
            )
            return False
        return True

    def _record_ship_publication(self) -> None:
        """AD-1141 DD-6: consume one slot of the ship-wide hourly budget."""
        self._ship_publications.append(time.monotonic())

    def _admit_publication(self, callsign: str) -> bool:
        """Prune the author's window and admit the call if it fits the budget.

        The timestamp is appended only on admission, so a refused call does not
        extend the window. The tracked-author map is bounded so a flood of
        distinct callsigns cannot grow it without limit.
        """
        now = time.monotonic()
        window = self._publications.get(callsign)
        if window is None:
            if len(self._publications) >= _MAX_TRACKED_AUTHORS:
                self._evict_idle_authors(now)
            window = deque(maxlen=self._max_per_hour)
            self._publications[callsign] = window

        cutoff = now - _RATE_WINDOW_SECONDS
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= self._max_per_hour:
            logger.info(
                "AD-1140: %s reached its publication budget of %d per hour; the "
                "finding is refused without a write and stays in working context",
                callsign, self._max_per_hour,
            )
            return False
        window.append(now)
        return True

    def _evict_idle_authors(self, now: float) -> None:
        """Drop authors whose window has fully aged out, then hard-trim."""
        cutoff = now - _RATE_WINDOW_SECONDS
        for name in [
            key for key, window in self._publications.items()
            if not window or window[-1] <= cutoff
        ]:
            del self._publications[name]
        while len(self._publications) >= _MAX_TRACKED_AUTHORS:
            self._publications.pop(next(iter(self._publications)))

    # ── Write path ────────────────────────────────────────────────
    async def _publish(
        self,
        *,
        fields: dict[str, Any],
        callsign: str,
        department: str,
        ctx: dict[str, Any],
        started: float,
    ) -> ToolResult:
        requested = fields["classification"]
        # DD-4: a fleet request is written at ship scope so Tier 2 can reach
        # it, and the intent is preserved in ``requested_scope``. Every other
        # classification takes the same code path with the two values equal.
        written = (
            _FLEET_WRITE_CLASSIFICATION
            if requested == _FLEET_CLASSIFICATION
            else requested
        )

        claim_id = compute_claim_id(
            fields["title"], fields["claim"], fields["basis"],
        )
        slug = f"{_slugify(fields['title'])}-{claim_id[:8]}"
        body = self._render_body(fields)

        dedup = await self._check_similarity(callsign, slug, body)
        if dedup.get("action") == "suppress":
            existing = str(dedup.get("existing_path") or "")
            self._record_quality("dedup_suppression")
            logger.info(
                "AD-1140: %s published a finding matching %s; the existing "
                "entry stands and no write was made",
                callsign, existing or "<unknown>",
            )
            return ToolResult(
                output=self._bounded(
                    _DUPLICATE_DISPOSITION.format(path=existing or slug),
                ),
                duration_ms=(time.monotonic() - started) * 1000.0,
                metadata={
                    "published": False,
                    "reason": "duplicate",
                    "claim_id": claim_id,
                    "path": existing,
                },
            )

        envelope = self._build_envelope(
            fields=fields,
            claim_id=claim_id,
            written=written,
            requested=requested,
            ctx=ctx,
        )

        try:
            path = await self._records.write_notebook(
                callsign=callsign,
                topic_slug=slug,
                content=body,
                department=department,
                tags=list(fields["tags"]),
                classification=written,
                extra_frontmatter=envelope,
            )
        except Exception:
            logger.error(
                "AD-1140: the records write failed for %s claim %s; nothing was "
                "recorded and the agent is told the publication did not land",
                callsign, claim_id[:8], exc_info=True,
            )
            return self._invalid("write_failed", started)

        self._record_quality("dedup_write")
        logger.info(
            "AD-1140: %s published claim %s at %s (requested %s) to %s",
            callsign, claim_id[:8], written, requested, path,
        )
        disposition = (
            _FLEET_DISPOSITION
            if requested == _FLEET_CLASSIFICATION
            else _SUCCESS_DISPOSITION.format(classification=written)
        )
        return ToolResult(
            output=self._bounded(f"{_HEADER}\n\n{disposition}\n"),
            duration_ms=(time.monotonic() - started) * 1000.0,
            metadata={
                "published": True,
                "path": path,
                "claim_id": claim_id,
                "classification": written,
                "requested_scope": requested,
            },
        )

    async def _check_similarity(
        self, callsign: str, slug: str, body: str,
    ) -> dict[str, Any]:
        """DD-6: call the AD-550 gate explicitly; degrade to write on failure.

        ``write_notebook`` does not call this — ``proactive.py`` does it at the
        call site, so this tool must too. That is the concrete meaning of
        passing *through* the curation guards rather than around them.

        **Known bound:** Layer 3 scans at most ``max_scan_entries`` entries
        updated within ``staleness_hours``. A publisher exceeding that inside
        the window can slip a near-duplicate past. The DD-7 rate limit is what
        keeps the flood below that ceiling; the two bounds are coupled by
        design.

        Degrading to *write* matches ``proactive.py``: a broken dedup check
        must not silently discard an agent's finding.
        """
        try:
            return await self._records.check_notebook_similarity(
                callsign=callsign,
                topic_slug=slug,
                new_content=body,
                similarity_threshold=self._similarity_threshold,
                staleness_hours=self._staleness_hours,
                max_scan_entries=self._max_scan_entries,
            )
        except Exception:
            logger.warning(
                "AD-1140: the AD-550 dedup check raised for %s/%s; proceeding "
                "with the write so a broken guard does not discard the finding",
                callsign, slug, exc_info=True,
            )
            return {"action": "write", "reason": "dedup_check_failed"}

    @staticmethod
    def _render_body(fields: dict[str, Any]) -> str:
        """DD-3: the claim text is the markdown body, so every retrieval sees it.

        Basis travels in the body as well as being bounded separately, because
        the AD-1138 embedding and the keyword index both read the body only.
        """
        return (
            f"# {fields['title']}\n\n"
            f"{fields['claim']}\n\n"
            f"## Basis\n\n{fields['basis']}\n"
        )

    def _build_envelope(
        self,
        *,
        fields: dict[str, Any],
        claim_id: str,
        written: str,
        requested: str,
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """DD-3: the system-owned frontmatter block.

        Every value is a plain ``str`` / ``int`` / ``float`` so the envelope
        round-trips losslessly through ``yaml.dump`` → ``yaml.safe_load``.

        ``session_id`` / ``work_item_id`` come from the crew executor's
        ``extra_context`` and are written as ``""`` when the caller is not a
        crew child — the linkage is recorded when it exists and is never
        fabricated when it does not.

        ``half_life_days`` is a **reserved, unconsumed slot**. Nothing in
        ProbOS applies decay to Ship's Records; AD-873 is the
        ``_composite_recall_score`` reranker over *episodes*, which is a
        different tier. The field is written so a later decay implementation
        has somewhere to land, and it is honest to say it currently decays
        nothing.
        """
        return {
            "claim_id": claim_id,
            "claim_version": CLAIM_VERSION,
            "confidence": fields["confidence"],
            "basis": fields["basis"],
            "requested_scope": requested,
            "source_node": self._source_node,
            "session_id": self._context_id(ctx, "_crew_session_id"),
            "work_item_id": self._context_id(ctx, "_crew_work_item_id"),
            "contest_state": "uncontested",
            "half_life_days": 0,
        }

    @staticmethod
    def _context_id(ctx: dict[str, Any], key: str) -> str:
        value = ctx.get(key)
        return value if type(value) is str else ""

    def _record_quality(self, event: str) -> None:
        """AD-555: reflect publications in the ship-wide notebook quality score.

        Mirrors ``proactive.py``'s dedup event recording. Degrades silently when
        no engine is wired — quality metrics are observability, not a gate.
        """
        if self._quality is None:
            return
        try:
            self._quality.record_event(event)
        except Exception:
            logger.warning(
                "AD-1140: the notebook quality engine rejected a %s event; the "
                "publication stands and only the quality metric is affected",
                event, exc_info=True,
            )

    # ── Result helpers ────────────────────────────────────────────
    @staticmethod
    def _bounded(text: str) -> str:
        """DD-2: final hard cap on the confirmation handed back to the loop."""
        if len(text) <= _MAX_OUTPUT_CHARS:
            return text
        return text[:_MAX_OUTPUT_CHARS]

    def _refused(
        self, disposition: str, reason: str, started: float,
    ) -> ToolResult:
        """DD-7: a bound refusal is framed output, deliberately not an ``error``.

        An ``error`` result is the shape that drives a retry loop, and a retry
        loop is exactly what the limiter exists to absorb.
        """
        return ToolResult(
            output=self._bounded(f"{_HEADER}\n\n{disposition}\n"),
            duration_ms=(time.monotonic() - started) * 1000.0,
            metadata={"published": False, "reason": reason},
        )

    @staticmethod
    def _invalid(code: str, started: float) -> ToolResult:
        return ToolResult(
            error=f"publish_finding_invalid:{code}",
            duration_ms=(time.monotonic() - started) * 1000.0,
        )
