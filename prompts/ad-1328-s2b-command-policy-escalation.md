# AD-1328 S2b -- Command policy escalation: an escalated run_command is filed in the AD-1154 inbox, runs exactly once under the Captain's approval when re-issued in its scope, and is reused within the same work item

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16 -- re-anchored on the final S1 (repair r3, review round 4 clean) and S2a (repairs r1, r2) code: S2a H8 and H11 applied, the record budget decided (D5), the typed `approval` projection, the storage-declaration anchor corrected.

**Status:** Ready for build (slice S2b of AD-1328, #1530). No new AD or BF number: AD-1328 is allocated by the issue title.
**Base:** the merged PR 1 tree (S1 final + S2a final), git tree `22dd3afc46cae65fe60e1f5bdc4c0f90b51fee7b` (candidate commit `ac49f647`). Build on a worktree of `main` after PR 1 merges; before installing, confirm `git rev-parse HEAD^{tree}` or, if `main` moved, that every SEARCH still occurs exactly once. Every block is anchored on that tree (grep evidence below); the labels **(against S2a)** and **(base tree)** only say which slice last changed the file.
**Dependencies:** S1 (public API by name only: `CanonicalCommand.key`/`.kind`, `CommandEvaluation.policy_digest`/`.dialect`), S2a (`CommandPolicyGate`, `CommandGateVerdict`, `policy_result_metadata`, `command_policy_record_of`, `compact_command_policy_record`, the three call-site seams). Followed by **S2c** (resume and closure, below; a separate contract).
**Estimated tests:** about 77 test functions in four new files, plus deliberate edits to S2a tests (listed under Tests).

One-line summary: `RunCommandTool` hands every `escalate` verdict to the runtime's one `CommandEscalations` service, which (1) runs it under a usable Captain approval for the same agent, scope, canonical key and policy digest -- recording the `approved_run` the first time and a `reuse` after, each referencing the original request, before the command starts -- or (2) refuses it as denied in this scope, or (3) files it as an AD-1154 `action` request carrying the bounded command, the matched rules and each cause; the Captain's approval records an `active` row and fulfils the request, never replaying the command; the mesh path keeps S2a's truthful refusal; the decision record gains an `approval` entry (schema v2); a shell agent's policy refusal no longer lowers its confidence.

---

## Problem

S2a refuses every `escalate` with `_ESCALATE_FRAME` ("no approval was requested from here", S2a Section 4). #1530 requires that `escalate` reach a real approval surface carrying the rule and justification (or the segment reason when no rule decided it, O-S1-11), that the approved command then run exactly once (cf. BF-830), and approval reuse for the same canonical command within a declared scope, expiring with the scope, a policy change or an authority change, never crossing agents, never upgrading a `forbid`, each reuse recorded with the original approval's reference. Reading the live code for this slice found:

1. **Approval of an AD-1154 `action` deliberately does not replay it** (`src/probos/capability_request.py:34`, `:794-802`; `src/probos/routers/capability_requests.py:247-256`); an ordinary approved action has no fulfiller (`_APPROVAL_FULFILLERS`, `routers/capability_requests.py:423-428`; pinned `"action" not in` by `tests/test_ad1204_approval_resumes_the_turn.py:875`, `tests/test_ad1211_approval_fulfils_every_kind.py:1643-1644`). The validated `repair/dispatch` subtype is handled before the map (`:451-462`) -- the precedent for a subtype with its own fulfiller.
2. **AD-1323 already solved "an approval the resumed pass consumes once"** (`src/probos/continue_extension_permits.py:1-31`: activate only by someone other than the asker, spend by one compare-and-set, rows never deleted; `:529-568`). S2b's store follows it.
3. **Every `action` request is Captain-reserved** (`src/probos/delegated_approvals.py:12-15`, `:171-172`); the REST route decides with `decided_by="captain"` (`routers/capability_requests.py:168-170`). So the approver and its authority are fixed today.
4. **The mesh path cannot honour an approval exactly once.** A mesh `run_command` reaches `ShellCommandAgent` only through the decomposer's DAG (`src/probos/cognitive/decomposer.py:985-989` -> `runtime.submit_intent_with_consensus`), which broadcasts to every pool member and each EXECUTES (`src/probos/runtime.py:4443`; `run_command` is `execute_then_vote`, `src/probos/types.py:948-961`, `src/probos/cognitive/intent_grants.py:9-16`; pool of 3, `src/probos/startup/agent_fleet.py:52`), then every red-team agent re-runs each successful result (`runtime.py:4541-4545`) that its own policy judgement admits (S2a: `src/probos/agents/red_team.py:311-313`, `:406-430`), and the Tier-3 cascade approval re-broadcasts it again (`src/probos/consensus/escalation.py:453-457`, `:512-518`), wired only in the interactive shell (`src/probos/experience/shell.py:146`). The mesh intent carries no requester identity and no scope (`IntentMessage`, `types.py:58-74`). Its originator is the Captain: no crew path can emit it (Absence Verified).
5. **The tool sees who asks and, for crew children, in which work item.** `ToolRegistry.check_and_invoke` sets `ctx["agent_id"]` over the caller's context and passes it to `tool.invoke` (`src/probos/tools/registry.py:461-467`); the loop context's `_crew_work_item_id` and `thread_id` arrive with it (`src/probos/cognitive/agentic_dispatch.py:110-127`, `:777`). Only crew children carry a work item id (`crew_executor.py:1930`, `crew_verifier.py:1536`, `:2112`); plain work items (`cognitive_agent.py:2347-2356`) and promoted DM turns (`agentic_dispatch.py:2412-2415`) do not.

## Solution

1. NEW `src/probos/execution/command_approvals.py`: `SqliteCommandApprovalStore` (tables `command_approvals`, `command_approval_uses`; ConnectionFactory; compare-and-set; no DELETE), the scope helpers and `command_approval_request` (the validated identity of a filed command escalation).
2. NEW `src/probos/execution/command_escalation.py`: `CommandEscalations` (`resolve`, `fulfil_approval`, `record_denial`), `escalation_scope`, `command_approval_payload`, the five agent-facing frames, `build_command_escalations`.
3. `command_gate.py` (S2a): record schema v2 with an `approval` entry; `runs` admits an `escalate` only with an approved state; `cause_text`; `COMMAND_POLICY_REFUSAL_KEY`; truthful docstring.
4. `RunCommandTool` gets `command_escalations=` (constructor injection through `register_native_swe_tools` from `_wire_native_swe_harness`, which builds the service when the stores run and exposes it as `runtime.command_escalations` for the router).
5. Startup: the store is started only when `execution.command_policy` has rules (`_start_command_approval_store`, the AD-1323 pattern); `CommunicationResult`, `ProbOSRuntime`, shutdown and the store registry learn it.
6. Router: the command subtype's fulfiller before the kind map (approve -> `fulfil_approval`; deny -> `record_denial`); no standing rule for a command approval.
7. `ShellCommandAgent`: refusals carry `COMMAND_POLICY_REFUSAL_KEY`; `handle_intent` does not move confidence for them (O-S2a-5).

### Slicing and the PR boundary (decided 2026-10-16)

The approval round trip does not fit one adversarial review with resume included: resume needs the work item id threaded into the tool context for plain work items and promoted DM turns, and a post-run park through two different seams (AD-1204's `_park_work_item`, `continue_or_ask.py:592-640`; AD-1324 does not park crew children, `tier_floor_ask.py:151-153`) -- agentic-dispatch internals this slice does not touch. So:

- **S2b (this):** store, service, filing, Captain-only activation, run-on-re-issue exactly once, reuse within a work item, denial, records, mesh frame, O-S2a-4..7. Coherent alone: an escalation is filed truthfully; after approval the agent's next identical call in the scope runs once and is recorded.
- **S2c (next, closes #1530):** O-S2b-1..4 below (resume, the p0 seam, DM-turn scope, closing trackers).
- **PRs:** PR 1 = S1 + S2a, "Part of #1530", no closing keyword. PR 2 = S2b + S2c, closes #1530. One broad gate per PR.

### Decisions

- **D1 -- Slicing.** As above. Milestones M1-M4.
- **D2 -- Escalation flow (tool path).** Filed as AD-1154 `kind="action"` with payload `tool_id="run_command"`, `action="execute"`, `scope_key` = the scope (D4), `thread_id`, and `params` = bounded command text (1,200 characters, then 300; `backslashreplace`, so a lone surrogate files instead of failing BF-854's check), its length, canonical key and kind, policy digest, dialect, call site, matched rule names, up to five causes (kind, rule, justification or reason, alternative; 200 then 80 characters each). `work_item_id` = the crew work item. The request IS the approval surface (HXI panel, AD-857 notifier), so it carries the command and the justification; the AD-1224 record and the new store never do. Dedup is AD-1154's (`action_dedup_key`, `capability_request.py:456-482`): a repeat folds into the pending request. The pending cap and stale window are `approval_inbox.max_pending_per_agent` / `pending_ask_ttl_hours` (`config_models/experience.py:158`, `:170`), as AD-1154 applies them (`agentic_dispatch.py:1335-1387`); filing does not require `approval_inbox.enabled` (that flag arms the browser wrapper). What the agent sees, error-shaped and final (AD-1154 DD-2 voice, checked against `_CAPABILITY_GAP_RE`): **pending** -- "filed for review as request X and was not run ... Do not repeat this call now ... Once it is approved, running the same command again in this task runs it" (work item) or "... again within an hour runs it once" (thread or none); **approved** -- the command runs and the result carries the approval in its record; **denied** -- "The Captain denied this command for this work (request X) ... continue without it"; **inbox full** / **filing failed** -- refused, not run. Requester: the agent the registry named (`registry.py:462`). **Mesh path:** S2a's `_ESCALATE_FRAME`, unchanged -- "no approval was requested from here"; nothing is filed (D3).
- **D3 -- Resume and exactly once.** Ranked: (a) **a scoped approval the re-issued call consumes** -- chosen; (b) replay on approval -- rejected (AD-1154, BF-830: the working directory and repository state move between filing and a human decision; a REST handler would run a shell command); (c) a one-shot pool grant on the mesh -- rejected (D3 mesh, below). The approval row lives in `command_approvals.db`, written only from the Captain's decision; each run is admitted by one transaction (compare-and-set on `uses`, then a `command_approval_uses` row) committed **before** the spawn, so a crash can lose a run but never repeat one; nothing replays at startup. A partial unique index allows one `approved_run` per approval. An approval arriving after the turn ended is the normal case: it waits (work item: until the item ends or 7 days; thread or none: one run within an hour). An approval arriving after the work item ended, or under another policy digest, grants nothing and the request stays approved, not fulfilled (BF-722 retry). **Pool and red team:** the tool path has no pool and no red-team re-run; `run_command` is not parallel-safe (`agentic_loop.py:147-155`), so one loop issues one call at a time. **Mesh:** no approval route. Every pool member executes and every red-team agent re-runs (Problem 4), so no grant can make an approved command run once without changing `run_command`'s consensus mode -- out of #1530 ("never bypasses consensus"). Reframe check: the requirement protects against an agent running an unapproved command and against an approved act running twice; on the mesh path the originator is the Captain's own decomposed request (Absence Verified), so keeping the truthful refusal loses no protection; the Captain's route to run it is the tool path or a policy edit. Recorded; the Captain may overrule (see answer). Follow-up recommended: make `run_command` `propose_commit` (BF-779's mode) so the mesh can carry an approval.
- **D4 -- Approval reuse store.** `command_approvals(request_id PK, agent_id, scope_key, canonical_key, policy_digest, state active|denied, approver, approver_authority, decided_at, expires_at NOT NULL, uses)`; `command_approval_uses(use_id PK, request_id, agent_id, scope_key, use_kind approved_run|reuse, used_at)`. **Key:** agent + scope + canonical key + digest + approver authority. **Scope:** `work_item:<id>` (crew child; reusable while the item is not done, cancelled or failed -- `workforce.py:114` -- and for at most 7 days), `thread:<id>` and `""` (one run within an hour; no reuse). **Expiry:** scope end (checked against the work-item store at each use and at activation; a read failure fails closed), policy change (digest is part of the key; activation refuses a digest other than the running gate's), authority change (`approver = 'captain' AND approver_authority = 'captain'` in every use; a future change of who may approve writes another authority and strands old rows), `expires_at`. **Never crosses agents** (agent in the key and in the compare-and-set). **Never upgrades a `forbid`:** only `escalate` verdicts reach the service, and `CommandGateVerdict.runs` admits an approval only when the verdict's own decision is `escalate`; a rule changed to `forbid` also changes the digest. **Denial:** stored for a non-empty scope and refused there without refiling. Registered in `execution/storage_declarations.py` (`FEATURE_GATED`, unbounded, no DELETE). Started only when the policy has rules (zero-config boot unchanged: no `command_approvals.db`). Migration: none (new database, `CREATE ... IF NOT EXISTS`). Cloud-ready: ConnectionFactory, no direct `aiosqlite.connect` (`check_architecture_principles.py:192`). No standing rule for a command approval (the router refuses `grant_standing`, as it does for repair at `:579-585`): a standing rule would outlive the scope.
- **D5 -- Records.** `RECORD_SCHEMA` -> `probos.command_policy.record/v2` (`_RECORD_SCHEMAS` follows it, so a v1 record is refused); `_RECORD_KEYS` gains `approval`: `None`, or -- on an `escalate` record only -- exactly `{state, request_id, use_id}` with `state` in `filed | denied | inbox_full | unfiled | approved_run | reuse` and the ids that state carries, each in a closed form: `request_id` the AD-1154 id (`str(uuid.uuid4())`, `capability_request.py:742`, 36 characters) on `filed`, `denied`, `approved_run` and `reuse`, else None; `use_id` the store's `uuid4().hex` (32) on `approved_run` and `reuse`, else None. `command_policy_record_of` re-validates it and rebuilds it field by field (S2a's typed projection, repair r1 F4: no field can hold free text, so an id cannot carry command text). **Budget (decided 2026-10-16, re-anchor):** the largest admitted v2 record is 2,037 characters (S2a's 1,898-character maximum, B10/B31, plus 139 for a maximal `approval`), within `MAX_RECORD_CHARS` = 2,048, which stays; a gate verdict's record grows by 18 (`"approval": null`). At the 4,096-byte AD-1224 envelope with maximal provenance that maximum is about 4,147 bytes emitted and 4,128 durable (computed: S2a's measured 3,994 / 3,975 plus 153 escaped bytes), so the sink keeps S2a's compact form (`compact_command_policy_record`, repair r1 F5): the two lists become counts and the `approval` entry is kept whole. S2b relies on that compaction rather than widening the envelope; only an all-maximal record (8 rules of 64 characters, 8 causes) reaches it, and the approval's durable evidence is the `command_approval_uses` row in any case. A gate record with `approval: null` at S2a's maximum stays whole (about 4,014 / 3,995 bytes). M3 #11-#12 measure both. Each run under an approval carries `request_id` (the original approval) and `use_id` on the AD-1224 completion record; the durable reuse record is the `command_approval_uses` row (request id, agent, scope, kind, time). No command text or justification in the record, the store or any log line S2b adds; the request payload carries both because it is the approval surface. AD-1316: with the broker on, preflight still denies `command_policy_escalate` before admission and nothing is filed (an approval could never run an unproven shell).
- **D6 -- O-S2a-4..7.** **O-S2a-4:** requester = the Captain's decomposed request; members executing = all three, plus a red-team re-run of each successful result its own judgement admits (measured above from source; a refused command is answered from the verdict, S2a); durable mesh record: none added (the mesh path has no per-call durable record for any `run_command`; the gate's INFO line stands); `_MeshEffectAdapter`: no change (members judge before executing). **O-S2a-5:** a policy refusal does not move the shell agent's confidence (`COMMAND_POLICY_REFUSAL_KEY`); hebbian routing and trust are unchanged (failed results are not verified, `runtime.py:4522`). **O-S2a-6:** no change -- under the broker every shell effect is refused as unproven anyway, and the reason code already names the policy; revisit when shell isolation is proven. **O-S2a-7:** S2b builds no gate; the AST test stands unchanged.
- **D7 -- Tests, mutation, pins.** Below.

### Obligations carried to S2c (O-S2b)

- **O-S2b-1 Resume.** Carry the work item id of plain work items (`cognitive_agent.py:2347-2356`) and promoted DM turns (`agentic_dispatch.py:2412-2415`) into the tool context under a key distinct from `_crew_work_item_id` (that key means "crew child" to AD-1324, `agentic_dispatch.py:2447-2463`), extend `escalation_scope`, and park the item on its first command escalation after the run (`continue_or_ask._park_work_item`), so an approval's FULFILLED resumes and re-dispatches it (`capability_gap_driver.py:279-340`). Decide whether a command denial should cancel a parked item (`:281-284` cancels on any denial).
- **O-S2b-2 Seam.** The crossing test for `TA-P0-003-approval-resume` (`docs/development/seams/p0-manifest.yaml:47-57`): file -> approve -> fulfil -> resumed turn -> the re-issued command runs once.
- **O-S2b-3 DM-turn scope.** A DM turn that is not promoted has only `thread:` (one run, no reuse); confirm or give it a turn identity.
- **O-S2b-4 Closure (O-S2a-8).** `DECISIONS.md` closure entry for AD-1328, `PROGRESS.md`, roadmap check; PR 2 closes #1530.

---

### Section 1 -- NEW `src/probos/execution/command_approvals.py`

```python
"""AD-1328 S2b (#1530): command approvals -- the Captain's decision on one escalated
``run_command``, in one scope, and every run that decision admitted.

An escalated command is filed as an AD-1154 ``action`` request (tool ``run_command``,
action ``execute``) by ``probos.execution.command_escalation``; the request store stays
the authority for the ask. This store holds what the decision allows afterwards.

* A row is written only from a decided request (``record_decision``), keyed on the
  request id, and names what the decision is for: the asking agent, the scope
  (``work_item:<id>``, ``thread:<id>`` or ``""``), the command's canonical key and the
  policy digest. Approval writes ``active``; denial writes ``denied``. A replay of the
  decision changes nothing.
* ``use`` admits one run by one compare-and-set, committed before the caller starts
  the command: the first is the ``approved_run``, any later one a ``reuse``, each row
  naming the original request. Only a work-item scope admits more than one run, and a
  partial unique index makes a second ``approved_run`` for one approval impossible.
* A row admits nothing for another agent, scope, canonical key or digest; nothing at or
  past ``expires_at`` (``NOT NULL``); and nothing approved by anyone but the Captain
  under the Captain's authority (every ``action`` request is Captain-reserved,
  ``probos.delegated_approvals.classify_capability_request``). A change of who may
  approve is a change of ``approver_authority``, which strands every older row.
* Whether a work item is still open is the caller's question (it holds the work-item
  store); this module reads no other store and imports nothing from the runtime.

Rows are never deleted: approvals, denials and uses are governance evidence. Storage
goes through :class:`probos.protocols.ConnectionFactory`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from probos.capability_request import THREAD_ID_MAX_CHARS, validate_action_payload
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

#: The AD-1154 action shape a command escalation is filed under.
COMMAND_APPROVAL_TOOL_ID: Final = "run_command"
COMMAND_APPROVAL_ACTION: Final = "execute"
#: The only approver, and the only authority, a command approval is honoured under.
CAPTAIN: Final = "captain"
APPROVER_AUTHORITY: Final = "captain"
WORK_ITEM_SCOPE_PREFIX: Final = "work_item:"
THREAD_SCOPE_PREFIX: Final = "thread:"
#: Ceilings. A work-item approval also ends with its work item (checked by the caller).
REUSABLE_APPROVAL_TTL_SECONDS: Final = 7 * 86400.0
SINGLE_USE_APPROVAL_TTL_SECONDS: Final = 3600.0
#: Statuses that end a work-item scope; every per-type terminal set in probos.workforce
#: is a subset (tests pin it against probos.workforce._TERMINAL_STATUSES).
ENDED_WORK_ITEM_STATUSES: Final = frozenset({"done", "cancelled", "failed"})

_KEY_RE = re.compile(r"[0-9a-f]{64}")
_WORK_ITEM_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MAX_TEXT = 128

_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_approvals (
    request_id TEXT PRIMARY KEY CHECK (length(request_id) > 0),
    agent_id TEXT NOT NULL CHECK (length(agent_id) > 0),
    scope_key TEXT NOT NULL,
    canonical_key TEXT NOT NULL CHECK (length(canonical_key) = 64),
    policy_digest TEXT NOT NULL CHECK (length(policy_digest) > 0),
    state TEXT NOT NULL CHECK (state IN ('active', 'denied')),
    approver TEXT NOT NULL,
    approver_authority TEXT NOT NULL,
    decided_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0 CHECK (uses >= 0)
);
CREATE INDEX IF NOT EXISTS idx_command_approvals_identity
    ON command_approvals(agent_id, scope_key, canonical_key, policy_digest, state);
CREATE TABLE IF NOT EXISTS command_approval_uses (
    use_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    use_kind TEXT NOT NULL CHECK (use_kind IN ('approved_run', 'reuse')),
    used_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_command_approval_first_use
    ON command_approval_uses(request_id) WHERE use_kind = 'approved_run';
CREATE INDEX IF NOT EXISTS idx_command_approval_uses_request
    ON command_approval_uses(request_id);
"""
_COLUMNS = (
    "request_id, agent_id, scope_key, canonical_key, policy_digest, state, approver, "
    "approver_authority, decided_at, expires_at, uses"
)
_USE_COLUMNS = "use_id, request_id, agent_id, scope_key, use_kind, used_at"

ApprovalState = Literal["active", "denied"]
UseKind = Literal["approved_run", "reuse"]


@dataclass(frozen=True)
class CommandApproval:
    """One decided command escalation."""

    request_id: str
    agent_id: str
    scope_key: str
    canonical_key: str
    policy_digest: str
    state: str
    approver: str
    approver_authority: str
    decided_at: float
    expires_at: float
    uses: int


@dataclass(frozen=True)
class CommandApprovalUse:
    """One run an approval admitted; ``request_id`` is the original approval."""

    use_id: str
    request_id: str
    agent_id: str
    scope_key: str
    use_kind: str
    used_at: float


@dataclass(frozen=True)
class CommandApprovalAsk:
    """What a filed command escalation asks approval for, read from its request."""

    request_id: str
    agent_id: str
    scope_key: str
    work_item_id: str | None
    canonical_key: str
    policy_digest: str


def scope_work_item_id(scope_key: object) -> str | None:
    """The work item a ``work_item:<id>`` scope names, else None."""
    if type(scope_key) is not str or not scope_key.startswith(WORK_ITEM_SCOPE_PREFIX):
        return None
    work_item_id = scope_key[len(WORK_ITEM_SCOPE_PREFIX):]
    return work_item_id if _WORK_ITEM_ID_RE.fullmatch(work_item_id) else None


def valid_scope_key(scope_key: object) -> bool:
    """``""``, ``work_item:<id>`` or ``thread:<id>`` (at most the AD-1154 thread bound)."""
    if type(scope_key) is not str:
        return False
    if scope_key == "":
        return True
    if scope_key.startswith(WORK_ITEM_SCOPE_PREFIX):
        return scope_work_item_id(scope_key) is not None
    if scope_key.startswith(THREAD_SCOPE_PREFIX):
        return 0 < len(scope_key) - len(THREAD_SCOPE_PREFIX) <= THREAD_ID_MAX_CHARS
    return False


def approval_ttl_seconds(scope_key: str) -> float:
    """How long a decision in ``scope_key`` can be used, at most."""
    if scope_work_item_id(scope_key) is not None:
        return REUSABLE_APPROVAL_TTL_SECONDS
    return SINGLE_USE_APPROVAL_TTL_SECONDS


def command_approval_request(req: Any) -> CommandApprovalAsk | None:
    """The identity a capability request asks approval for, when it is a well-formed
    command escalation (``action`` / ``run_command`` / ``execute``), else None.

    The payload is re-validated (``validate_action_payload``); a work-item scope must
    name the request's own work item.
    """
    if getattr(req, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(req, "payload", None))
    if payload is None:
        return None
    if payload["tool_id"] != COMMAND_APPROVAL_TOOL_ID or payload["action"] != COMMAND_APPROVAL_ACTION:
        return None
    params = payload["params"]
    canonical_key = params.get("canonical_key")
    policy_digest = params.get("policy_digest")
    if type(canonical_key) is not str or _KEY_RE.fullmatch(canonical_key) is None:
        return None
    if type(policy_digest) is not str or not 0 < len(policy_digest) <= _MAX_TEXT:
        return None
    scope_key = payload["scope_key"]
    if not valid_scope_key(scope_key):
        return None
    work_item_id = scope_work_item_id(scope_key)
    if work_item_id is not None and getattr(req, "work_item_id", None) != work_item_id:
        return None
    request_id = getattr(req, "id", None)
    agent_id = getattr(req, "agent_id", None)
    if type(request_id) is not str or not request_id or len(request_id) > _MAX_TEXT:
        return None
    if type(agent_id) is not str or not agent_id or len(agent_id) > _MAX_TEXT:
        return None
    return CommandApprovalAsk(request_id, agent_id, scope_key, work_item_id, canonical_key, policy_digest)


def _check_identity(
    request_id: object, agent_id: object, scope_key: object, canonical_key: object, policy_digest: object,
) -> None:
    for name, value in (("request_id", request_id), ("agent_id", agent_id), ("policy_digest", policy_digest)):
        if type(value) is not str or not value or len(value) > _MAX_TEXT:
            raise ValueError(f"command_approval_{name}_invalid")
    if not valid_scope_key(scope_key):
        raise ValueError("command_approval_scope_invalid")
    if type(canonical_key) is not str or _KEY_RE.fullmatch(canonical_key) is None:
        raise ValueError("command_approval_canonical_key_invalid")


def _row_to_approval(row: Any) -> CommandApproval:
    return CommandApproval(
        request_id=row[0], agent_id=row[1], scope_key=row[2], canonical_key=row[3],
        policy_digest=row[4], state=row[5], approver=row[6], approver_authority=row[7],
        decided_at=float(row[8]), expires_at=float(row[9]), uses=int(row[10]),
    )


async def _rollback(db: Any) -> None:
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1328: rollback found no open transaction")


class SqliteCommandApprovalStore:
    """SQLite-backed command approvals; see the module docstring for the guarantees.

    Public API:
        start() / stop()
        record_decision(...) -> CommandApproval | None   first decision wins
        find(agent, scope, key, digest, *, state)        newest usable row, else None
        use(request_id, *, agent_id, scope_key)          one admitted run, else None
        get(request_id) / list_uses(request_id)
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._clock = clock
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database and apply the schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-1328: command approval store started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the database; later calls fail closed."""
        db, self._db = self._db, None
        if db is not None:
            await db.close()

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise RuntimeError("AD-1328: the command approval store clock is not a finite real")
        return float(now)

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("AD-1328: the command approval store is not running")
        return self._db

    async def record_decision(
        self,
        *,
        request_id: str,
        agent_id: str,
        scope_key: str,
        canonical_key: str,
        policy_digest: str,
        state: ApprovalState,
        approver: str,
        ttl_seconds: float,
    ) -> CommandApproval | None:
        """Write the decision on one filed escalation; the first decision wins.

        Returns the row as stored. Raises ``ValueError`` for an identity that is not
        well formed. ``approver_authority`` is always the Captain's.
        """
        _check_identity(request_id, agent_id, scope_key, canonical_key, policy_digest)
        if state not in ("active", "denied"):
            raise ValueError("command_approval_state_invalid")
        if type(approver) is not str or not approver.strip() or len(approver) > _MAX_TEXT:
            raise ValueError("command_approval_approver_invalid")
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("command_approval_ttl_invalid")
        db = self._require_db()
        now = self._now()
        async with self._lock:
            try:
                await db.execute(
                    f"INSERT OR IGNORE INTO command_approvals ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        request_id, agent_id, scope_key, canonical_key, policy_digest, state,
                        approver, APPROVER_AUTHORITY, now, now + float(ttl_seconds),
                    ),
                )
                await db.commit()
            except BaseException:
                await _rollback(db)
                raise
        return await self.get(request_id)

    async def find(
        self,
        agent_id: str,
        scope_key: str,
        canonical_key: str,
        policy_digest: str,
        *,
        state: ApprovalState,
    ) -> CommandApproval | None:
        """The newest unexpired row of ``state`` for exactly this identity. An ``active``
        row outside a work-item scope is found only while it is unused."""
        db = self._require_db()
        now = self._now()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM command_approvals "
            "WHERE agent_id = ? AND scope_key = ? AND canonical_key = ? AND policy_digest = ? "
            "AND state = ? AND expires_at > ? "
            "AND (state <> 'active' OR substr(scope_key, 1, 10) = 'work_item:' OR uses = 0) "
            "ORDER BY decided_at DESC LIMIT 1",
            (agent_id, scope_key, canonical_key, policy_digest, state, now),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_approval(row)

    async def use(self, request_id: str, *, agent_id: str, scope_key: str) -> CommandApprovalUse | None:
        """Admit one run under an active approval; None when it admits none.

        One transaction: the compare-and-set on the approval, then the use row. It is
        committed before the caller starts the command, so a crash afterwards can lose
        a run but never repeat one (nothing replays it).
        """
        db = self._require_db()
        now = self._now()
        async with self._lock:
            try:
                cursor = await db.execute(
                    "UPDATE command_approvals SET uses = uses + 1 "
                    "WHERE request_id = ? AND agent_id = ? AND scope_key = ? AND state = 'active' "
                    "AND expires_at > ? AND approver = ? AND approver_authority = ? "
                    "AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",
                    (request_id, agent_id, scope_key, now, CAPTAIN, APPROVER_AUTHORITY),
                )
                if int(cursor.rowcount) != 1:
                    await _rollback(db)
                    return None
                async with db.execute(
                    "SELECT uses FROM command_approvals WHERE request_id = ?", (request_id,),
                ) as cur:
                    row = await cur.fetchone()
                use = CommandApprovalUse(
                    use_id=uuid.uuid4().hex,
                    request_id=request_id,
                    agent_id=agent_id,
                    scope_key=scope_key,
                    use_kind="approved_run" if int(row[0]) == 1 else "reuse",
                    used_at=now,
                )
                await db.execute(
                    f"INSERT INTO command_approval_uses ({_USE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                    (use.use_id, use.request_id, use.agent_id, use.scope_key, use.use_kind, use.used_at),
                )
                await db.commit()
            except BaseException:
                await _rollback(db)  # a failed use record must not leave the increment
                raise
        return use

    async def get(self, request_id: str) -> CommandApproval | None:
        db = self._require_db()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM command_approvals WHERE request_id = ?", (request_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_approval(row)

    async def list_uses(self, request_id: str) -> list[CommandApprovalUse]:
        """Every run one approval admitted, oldest first."""
        db = self._require_db()
        out: list[CommandApprovalUse] = []
        async with db.execute(
            f"SELECT {_USE_COLUMNS} FROM command_approval_uses WHERE request_id = ? "
            "ORDER BY used_at, rowid",
            (request_id,),
        ) as cur:
            async for row in cur:
                out.append(CommandApprovalUse(row[0], row[1], row[2], row[3], row[4], float(row[5])))
        return out
```

### Section 2 -- NEW `src/probos/execution/command_escalation.py`

```python
"""AD-1328 S2b (#1530): an escalated ``run_command`` goes to the chain of command.

``RunCommandTool`` hands every ``escalate`` verdict to the runtime's one
``CommandEscalations`` (built by ``build_command_escalations`` when the policy has
rules and the approval and request stores run). For one call it answers, in order:

1. **A usable approval** for this agent, scope, canonical command and policy digest
   (``probos.execution.command_approvals``) whose scope is still open: one run is
   admitted and recorded -- the ``approved_run`` the first time, a ``reuse`` after --
   and the tool runs the command. Only a work item's scope reuses.
2. **A denial** in this scope: refused; nothing is filed again.
3. Otherwise **filed** as an AD-1154 ``action`` request (tool ``run_command``, action
   ``execute``) carrying the bounded command text, the matched rules and each cause
   (rule and justification, or the reason no rule decided it); a repeat folds into the
   pending request. The agent is told the request id, that nothing ran, and not to
   repeat the call now.

Approval never replays the command (AD-1154, BF-830). The Captain's approval, through
``probos.routers.capability_requests``, calls ``fulfil_approval``: an ``active`` row is
recorded when the policy digest is the running one and the scope is still open, then
the request is marked fulfilled. The command runs when the asking agent issues it
again in that scope. ``forbid`` never reaches this module, and no approval runs a
command whose own decision is ``forbid`` (``CommandGateVerdict.runs``).

Every step fails toward refusal: a store that raises, a payload that will not
validate, an inbox at its cap or a call without an agent identity is refused, never
run. The mesh path (``ShellCommandAgent``) does not come here: it runs a command on
every pool member and re-runs it to verify, so it keeps S2a's refusal.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from probos.capability_request import THREAD_ID_MAX_CHARS, validate_action_payload
from probos.execution.command_approvals import (
    CAPTAIN,
    COMMAND_APPROVAL_ACTION,
    COMMAND_APPROVAL_TOOL_ID,
    ENDED_WORK_ITEM_STATUSES,
    THREAD_SCOPE_PREFIX,
    WORK_ITEM_SCOPE_PREFIX,
    approval_ttl_seconds,
    command_approval_request,
    scope_work_item_id,
)
from probos.execution.command_gate import CommandGateVerdict

logger = logging.getLogger(__name__)

_FILED_IN_TASK_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. It was "
    "filed for review as request {request_id} and was not run. {causes} Do not repeat this "
    "call now; a repeat is folded into the same request. Continue with the rest of your task "
    "and report that this command is waiting for approval. Once it is approved, running the "
    "same command again in this task runs it."
)
_FILED_ONCE_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. It was "
    "filed for review as request {request_id} and was not run. {causes} Do not repeat this "
    "call now; a repeat is folded into the same request. Continue with the rest of your work "
    "and report that this command is waiting for approval. Once it is approved, running the "
    "same command again {where}within an hour runs it once."
)
_DENIED_FRAME: Final = (
    "The Captain denied this command for this work (request {request_id}), so it was not "
    "run. {causes} Do not repeat it; continue without it and report that it was denied."
)
_INBOX_FULL_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. Too many "
    "of your requests are already awaiting review, so it was refused rather than filed, and "
    "it was not run. {causes} Continue with the rest of your work and report what remains open."
)
_UNFILED_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. Filing it "
    "for review failed, so it was not run. {causes} Do not repeat this call; continue with "
    "the rest of your work and report that this command needs approval."
)
#: Display bounds for the filed payload: the first pair, then the second if the payload
#: would exceed the AD-1154 limit (4,000 characters, capability_request.py:73).
_COMMAND_DISPLAY_CHARS: Final = (1200, 300)
_CAUSE_DISPLAY_CHARS: Final = (200, 80)
_MAX_CAUSES_FILED: Final = 5
_MAX_AGENT_ID_CHARS: Final = 128
_RATIONALE_CHARS: Final = 280


@dataclass(frozen=True)
class EscalationScope:
    """Who asks, and the scope an approval of this call would be bound to."""

    agent_id: str
    scope_key: str  # "work_item:<id>", "thread:<id>" or ""
    work_item_id: str | None
    thread_id: str


@dataclass(frozen=True)
class EscalationOutcome:
    """The verdict as recorded (with its ``approval`` entry) and the refusal, if any."""

    verdict: CommandGateVerdict
    message: str | None  # None: the command runs


def escalation_scope(context: object) -> EscalationScope | None:
    """The asker and scope from the invocation context ``ToolRegistry.check_and_invoke``
    built: it sets ``agent_id`` over the caller's keys; a crew child's loop context
    carries ``_crew_work_item_id``, a conversation's ``thread_id``. None without an
    agent identity."""
    if type(context) is not dict:
        return None
    agent_id = context.get("agent_id")
    if type(agent_id) is not str or not agent_id.strip() or len(agent_id) > _MAX_AGENT_ID_CHARS:
        return None
    thread = context.get("thread_id")
    thread_id = thread if type(thread) is str and 0 < len(thread) <= THREAD_ID_MAX_CHARS else ""
    crew_item = context.get("_crew_work_item_id")
    if type(crew_item) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + crew_item) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + crew_item, crew_item, thread_id)
    if thread_id:
        return EscalationScope(agent_id, THREAD_SCOPE_PREFIX + thread_id, None, thread_id)
    return EscalationScope(agent_id, "", None, "")


def with_approval(
    verdict: CommandGateVerdict, state: str, request_id: str | None = None, use_id: str | None = None,
) -> CommandGateVerdict:
    """The verdict carrying what the approval route did (its record's ``approval``)."""
    return dataclasses.replace(
        verdict, approval={"state": state, "request_id": request_id, "use_id": use_id},
    )


def _display(text: str, limit: int) -> str:
    safe = text.encode("utf-8", "backslashreplace").decode("utf-8")
    if len(safe) <= limit:
        return safe
    return f"{safe[:limit]} ...[{len(safe) - limit} more characters]"


def command_approval_payload(
    verdict: CommandGateVerdict, command: str, scope: EscalationScope,
) -> dict[str, Any] | None:
    """The AD-1154 action payload for one escalation, or None if it will not validate."""
    if verdict.evaluation is None or verdict.canonical is None:
        return None
    record = verdict.record or {}
    causes = verdict.causes
    for command_chars, cause_chars in zip(_COMMAND_DISPLAY_CHARS, _CAUSE_DISPLAY_CHARS):
        payload: dict[str, Any] = {
            "tool_id": COMMAND_APPROVAL_TOOL_ID,
            "action": COMMAND_APPROVAL_ACTION,
            "params": {
                "command": _display(command, command_chars),
                "command_chars": len(command),
                "canonical_key": verdict.canonical.key,
                "canonical_kind": verdict.canonical.kind,
                "policy_digest": verdict.evaluation.policy_digest,
                "dialect": verdict.evaluation.dialect,
                "call_site": verdict.call_site,
                "rules": list(record.get("matched_rules", [])),
                "causes": [
                    {
                        "kind": cause.kind,
                        "rule": cause.rule,
                        "text": _display(cause.text, cause_chars),
                        "alternative": None if cause.alternative is None else _display(cause.alternative, cause_chars),
                    }
                    for cause in causes[:_MAX_CAUSES_FILED]
                ],
                "causes_omitted": max(len(causes) - _MAX_CAUSES_FILED, 0),
            },
            "scope_key": scope.scope_key,
            "session_id": None,
            "thread_id": scope.thread_id,
        }
        if validate_action_payload(payload) is not None:
            return payload
    return None


def _rationale(verdict: CommandGateVerdict) -> str:
    names = list((verdict.record or {}).get("matched_rules", []))
    basis = ", ".join(names) if names else ", ".join(sorted({cause.kind for cause in verdict.causes}))
    return f"AD-1328 command policy escalation ({basis or 'escalate'})"[:_RATIONALE_CHARS]


class CommandEscalations:
    """The runtime's one route from an ``escalate`` verdict to the chain of command."""

    def __init__(
        self,
        *,
        gate: Any,
        approvals: Any,
        requests: Any,
        work_items: Any,
        max_pending_per_agent: int = 20,
        pending_ttl_hours: float = 72.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._gate = gate
        self._approvals = approvals
        self._requests = requests
        self._work_items = work_items
        self._max_pending = int(max_pending_per_agent)
        self._pending_ttl_seconds = float(pending_ttl_hours) * 3600.0
        self._clock = clock

    async def resolve(self, verdict: CommandGateVerdict, *, command: str, context: object) -> EscalationOutcome:
        """Run under an approval, refuse as denied, or file; never raises for a store fault."""
        if verdict.decision != "escalate" or verdict.canonical is None or verdict.evaluation is None:
            return EscalationOutcome(verdict, verdict.refusal_message)
        scope = escalation_scope(context)
        if scope is None:
            logger.warning(
                "AD-1328: an escalated run_command call carried no agent identity; it was "
                "neither filed nor run",
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        key = verdict.canonical.key
        digest = verdict.evaluation.policy_digest
        try:
            row = await self._approvals.find(scope.agent_id, scope.scope_key, key, digest, state="active")
            if row is not None and await self._scope_open(scope.scope_key):
                use = await self._approvals.use(row.request_id, agent_id=scope.agent_id, scope_key=scope.scope_key)
                if use is not None:
                    logger.info(
                        "AD-1328: agent %s runs an escalated command as %s of approval %s (scope %s)",
                        scope.agent_id[:12], use.use_kind, row.request_id[:12], scope.scope_key[:40] or "-",
                    )
                    return EscalationOutcome(with_approval(verdict, use.use_kind, row.request_id, use.use_id), None)
            if scope.scope_key:
                denied = await self._approvals.find(scope.agent_id, scope.scope_key, key, digest, state="denied")
                if denied is not None:
                    return self._refuse(verdict, "denied", _DENIED_FRAME, denied.request_id)
        except Exception:
            logger.warning(
                "AD-1328: the command approval lookup failed for agent %s; the command is not "
                "run and is filed for review", scope.agent_id[:12], exc_info=True,
            )
        return await self._file(verdict, command, scope)

    async def fulfil_approval(self, request_store: Any, decided: Any) -> Any | None:
        """The Captain approved a command escalation: record it, then fulfil the request.

        Returns the fulfilled request, or None -- nothing usable recorded and the request
        left approved, so the Captain can retry (BF-722) -- when the request is not an
        approved, well-formed command escalation, was not decided by the Captain, was
        filed under another policy digest than the running one, or its work item ended.
        """
        ask = command_approval_request(decided)
        if ask is None or getattr(decided, "status", None) != "approved":
            return None
        if getattr(decided, "decided_by", None) != CAPTAIN:
            logger.warning(
                "AD-1328: command approval %s was decided by %r, not the Captain; it grants nothing",
                ask.request_id[:12], getattr(decided, "decided_by", None),
            )
            return None
        if self._gate.digest != ask.policy_digest:
            logger.warning(
                "AD-1328: command approval %s was filed under another command policy "
                "(digest %s, running %s); it grants nothing and the command escalates again",
                ask.request_id[:12], ask.policy_digest[:16], str(self._gate.digest)[:16],
            )
            return None
        if not await self._scope_open(ask.scope_key):
            logger.warning(
                "AD-1328: command approval %s arrived after its work item ended; it grants nothing",
                ask.request_id[:12],
            )
            return None
        row = await self._approvals.record_decision(
            request_id=ask.request_id, agent_id=ask.agent_id, scope_key=ask.scope_key,
            canonical_key=ask.canonical_key, policy_digest=ask.policy_digest,
            state="active", approver=CAPTAIN, ttl_seconds=approval_ttl_seconds(ask.scope_key),
        )
        if row is None or row.state != "active":
            return None
        logger.info(
            "AD-1328: command approval %s recorded for agent %s (scope %s); the command runs "
            "when the agent issues it again there",
            ask.request_id[:12], ask.agent_id[:12], ask.scope_key[:40] or "-",
        )
        return await request_store.mark_fulfilled(ask.request_id)

    async def record_denial(self, decided: Any) -> bool:
        """The Captain denied a command escalation: within its scope it stays denied."""
        ask = command_approval_request(decided)
        if ask is None or not ask.scope_key or getattr(decided, "status", None) != "denied":
            return False
        approver = getattr(decided, "decided_by", None)
        row = await self._approvals.record_decision(
            request_id=ask.request_id, agent_id=ask.agent_id, scope_key=ask.scope_key,
            canonical_key=ask.canonical_key, policy_digest=ask.policy_digest, state="denied",
            approver=approver if type(approver) is str and approver.strip() else CAPTAIN,
            ttl_seconds=approval_ttl_seconds(ask.scope_key),
        )
        return row is not None and row.state == "denied"

    async def _file(self, verdict: CommandGateVerdict, command: str, scope: EscalationScope) -> EscalationOutcome:
        try:
            pending = self._requests.count_pending_sync(
                scope.agent_id, stale_before=self._clock() - self._pending_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "AD-1328: could not count pending asks for agent %s; the command is refused "
                "rather than filed", scope.agent_id[:12], exc_info=True,
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        if pending >= self._max_pending:
            return self._refuse(verdict, "inbox_full", _INBOX_FULL_FRAME)
        payload = command_approval_payload(verdict, command, scope)
        if payload is None:
            logger.warning("AD-1328: an escalated command's approval payload did not validate; not filed")
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        try:
            request = await self._requests.file_action_request(
                scope.agent_id, payload, rationale=_rationale(verdict), work_item_id=scope.work_item_id,
            )
        except Exception:
            logger.warning(
                "AD-1328: filing an escalated command for agent %s failed; it was not run",
                scope.agent_id[:12], exc_info=True,
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        request_id = getattr(request, "id", "") if request is not None else ""
        if type(request_id) is not str or not request_id:
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        logger.info(
            "AD-1328: escalated command for agent %s filed as request %s (scope %s)",
            scope.agent_id[:12], request_id[:12], scope.scope_key[:40] or "-",
        )
        if scope.work_item_id is not None:
            return self._refuse(verdict, "filed", _FILED_IN_TASK_FRAME, request_id)
        where = "in this conversation " if scope.thread_id else ""
        return self._refuse(verdict, "filed", _FILED_ONCE_FRAME, request_id, where=where)

    async def _scope_open(self, scope_key: str) -> bool:
        """A work-item scope is open while its item exists and has not ended; a thread or
        empty scope ends by time alone. A read that fails closes it."""
        work_item_id = scope_work_item_id(scope_key)
        if work_item_id is None:
            return True
        if self._work_items is None:
            return False
        try:
            item = await self._work_items.get_work_item(work_item_id)
        except Exception:
            logger.warning(
                "AD-1328: could not read work item %s; its command approvals are not used",
                work_item_id, exc_info=True,
            )
            return False
        return item is not None and getattr(item, "status", None) not in ENDED_WORK_ITEM_STATUSES

    @staticmethod
    def _refuse(
        verdict: CommandGateVerdict, state: str, frame: str, request_id: str | None = None, *, where: str = "",
    ) -> EscalationOutcome:
        message = frame.format(request_id=request_id or "", causes=verdict.cause_text, where=where)
        return EscalationOutcome(with_approval(verdict, state, request_id), message)


def build_command_escalations(
    *, gate: Any, approvals: Any, requests: Any, work_items: Any, inbox: Any,
) -> CommandEscalations | None:
    """The runtime's one ``CommandEscalations``, or None: no policy rules, or no approval
    or request store (an escalation then keeps S2a's refusal, ``_ESCALATE_FRAME``)."""
    if gate is None or getattr(gate, "configured", False) is not True:
        return None
    if approvals is None or requests is None:
        logger.warning(
            "AD-1328: the command policy has rules but the %s is not running; an escalated "
            "command is refused without being filed",
            "command approval store" if approvals is None else "capability request store",
        )
        return None
    return CommandEscalations(
        gate=gate,
        approvals=approvals,
        requests=requests,
        work_items=work_items,
        max_pending_per_agent=int(getattr(inbox, "max_pending_per_agent", 20)),
        pending_ttl_hours=float(getattr(inbox, "pending_ask_ttl_hours", 72)),
    )
```

### Section 3 -- `src/probos/execution/command_gate.py` (against S2a)

Eleven edits, anchored on the final S2a code (tree `22dd3afc`); each SEARCH occurs exactly once. S2a's `:985` anchor (`if record["decision"] not in COMMAND_DECISION_RANK ...`) no longer exists: S2a repair r1 replaced it with the typed projection, so the `approval` check joins its `checks` tuple and its rebuilt dict (S2a repair r1 H8).

<<<<<<< SEARCH
AD-1328 S2a refuses an ``escalate`` truthfully without asking anyone; S2b routes it
to the AD-1154 approval inbox. The policy only adds gates: it never admits a command
that the permission ladder, consensus or the effect broker would refuse.
"""
=======
An ``escalate`` is refused here with ``_ESCALATE_FRAME`` (no approval was requested).
``RunCommandTool`` hands it to ``probos.execution.command_escalation`` (AD-1328 S2b),
which files it in the AD-1154 approval inbox and runs it once the Captain approved it
in the same scope; the mesh path (``ShellCommandAgent``) has no approval route and
keeps the refusal. The policy only adds gates: it never admits a command that the
permission ladder, consensus or the effect broker would refuse.
"""
>>>>>>> REPLACE

<<<<<<< SEARCH
from dataclasses import dataclass
from typing import Any, Final, Literal
=======
from dataclasses import dataclass, field
from typing import Any, Final, Literal
>>>>>>> REPLACE

<<<<<<< SEARCH
RECORD_SCHEMA: Final = "probos.command_policy.record/v1"
=======
RECORD_SCHEMA: Final = "probos.command_policy.record/v2"  # AD-1328 S2b: + approval
>>>>>>> REPLACE

<<<<<<< SEARCH
#: AD-1328 S2a: refused without asking anyone. S2b replaces this with the approval inbox.
_ESCALATE_FRAME: Final = (
=======
#: AD-1328: an escalation with no approval route -- the mesh path, or a tool with no
#: approval service (S2b's ``command_escalation`` files the rest).
_ESCALATE_FRAME: Final = (
>>>>>>> REPLACE

<<<<<<< SEARCH
_RECORD_KEYS: Final = frozenset({
    "schema", "call_site", "decision", "dialect", "policy_digest", "canonical_key",
    "canonical_kind", "matched_rules", "matched_rules_omitted", "causes", "causes_omitted",
})
=======
_RECORD_KEYS: Final = frozenset({
    "schema", "call_site", "decision", "dialect", "policy_digest", "canonical_key",
    "canonical_kind", "matched_rules", "matched_rules_omitted", "causes", "causes_omitted",
    "approval",
})
#: AD-1328 S2b: what the approval route did for an escalated command (a record's
#: ``approval`` entry; None when no route was asked), and which ids each state carries:
#: (the AD-1154 request id, the approval-store use id). Only the last two run it.
_APPROVAL_SHAPES: Final = {
    "filed": (True, False),
    "denied": (True, False),
    "inbox_full": (False, False),
    "unfiled": (False, False),
    "approved_run": (True, True),
    "reuse": (True, True),
}
APPROVAL_STATES: Final = frozenset(_APPROVAL_SHAPES)
APPROVED_STATES: Final = frozenset({"approved_run", "reuse"})
_APPROVAL_KEYS: Final = frozenset({"state", "request_id", "use_id"})
#: The closed forms of those ids: ``str(uuid.uuid4())`` (``CapabilityRequestStore``) and
#: ``uuid.uuid4().hex`` (``SqliteCommandApprovalStore.use``). No id can carry free text.
_APPROVAL_REQUEST_ID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_APPROVAL_USE_ID: Final = re.compile(r"[0-9a-f]{32}")
#: AD-1328 S2b (O-S2a-5): marks a shell agent's policy refusal, which is the policy's
#: decision and not the agent's failure, so it does not move the agent's confidence.
COMMAND_POLICY_REFUSAL_KEY: Final = "command_policy_refusal"
>>>>>>> REPLACE

<<<<<<< SEARCH
    status: Literal["no_policy", "evaluated"]
    call_site: CallSite | None
    evaluation: CommandEvaluation | None
    canonical: CanonicalCommand | None
=======
    status: Literal["no_policy", "evaluated"]
    call_site: CallSite | None
    evaluation: CommandEvaluation | None
    canonical: CanonicalCommand | None
    # AD-1328 S2b: set only by probos.execution.command_escalation.with_approval. A dict,
    # so it is left out of the generated __hash__.
    approval: dict[str, Any] | None = field(default=None, hash=False)
>>>>>>> REPLACE

<<<<<<< SEARCH
    @property
    def runs(self) -> bool:
        """Whether the caller runs the command: no policy, or ``allow``."""
        return self.status == "no_policy" or self.decision == "allow"
=======
    @property
    def runs(self) -> bool:
        """Whether the caller runs the command: no policy, ``allow``, or an ``escalate``
        the Captain's approval admitted in its scope (AD-1328 S2b). An approval never
        runs a command whose own decision is ``forbid``."""
        if self.status == "no_policy" or self.decision == "allow":
            return True
        approved = type(self.approval) is dict and self.approval.get("state") in APPROVED_STATES
        return approved and self.decision == "escalate"

    @property
    def cause_text(self) -> str:
        """AD-1328 S2b: each cause as the agent is told it (five, then a count)."""
        return _describe(self.causes)
>>>>>>> REPLACE

<<<<<<< SEARCH
            "causes_omitted": max(len(causes) - _MAX_RECORDED, 0),
        }
=======
            "causes_omitted": max(len(causes) - _MAX_RECORDED, 0),
            "approval": None if self.approval is None else dict(self.approval),
        }
>>>>>>> REPLACE

<<<<<<< SEARCH
def command_policy_record_of(result: object, *, tool_id: object) -> dict[str, Any] | None:
=======
def _valid_id(value: object, required: bool, form: re.Pattern[str]) -> bool:
    if not required:
        return value is None
    return type(value) is str and form.fullmatch(value) is not None


def _valid_approval(value: object, decision: object) -> bool:
    """AD-1328 S2b: a record's ``approval`` entry is None, or -- on an ``escalate`` record
    only -- exactly its three keys: a known state and the ids that state carries, each in
    its closed form (``_APPROVAL_SHAPES``)."""
    if value is None:
        return True
    if decision != "escalate" or type(value) is not dict or set(value) != _APPROVAL_KEYS:
        return False
    state = value["state"]
    if type(state) is not str or state not in _APPROVAL_SHAPES:
        return False
    has_request, has_use = _APPROVAL_SHAPES[state]
    return _valid_id(value["request_id"], has_request, _APPROVAL_REQUEST_ID) and _valid_id(
        value["use_id"], has_use, _APPROVAL_USE_ID,
    )


def command_policy_record_of(result: object, *, tool_id: object) -> dict[str, Any] | None:
>>>>>>> REPLACE

<<<<<<< SEARCH
        type(causes) is list and len(causes) <= _MAX_RECORDED,
    )
=======
        type(causes) is list and len(causes) <= _MAX_RECORDED,
        _valid_approval(record["approval"], record["decision"]),  # AD-1328 S2b
    )
>>>>>>> REPLACE

<<<<<<< SEARCH
        "causes_omitted": record["causes_omitted"],
    }
    if len(json.dumps(copied, sort_keys=True)) > MAX_RECORD_CHARS:
        return None  # not reachable for an S2a record (at most about 1,900 characters)
=======
        "causes_omitted": record["causes_omitted"],
        # AD-1328 S2b: rebuilt field by field, like the causes.
        "approval": None if record["approval"] is None else {
            "state": record["approval"]["state"],
            "request_id": record["approval"]["request_id"],
            "use_id": record["approval"]["use_id"],
        },
    }
    if len(json.dumps(copied, sort_keys=True)) > MAX_RECORD_CHARS:
        return None  # not reachable: the typed maximum is 2,037 characters with S2b's approval
>>>>>>> REPLACE

### Section 4 -- `src/probos/cognitive/swe_harness/tools.py` (against S2a)

Six edits.

<<<<<<< SEARCH
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE,
    CommandGateVerdict,
    CommandPolicyGate,
    policy_result_metadata,
)
=======
from probos.execution.command_escalation import CommandEscalations
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE,
    CommandGateVerdict,
    CommandPolicyGate,
    policy_result_metadata,
)
>>>>>>> REPLACE

<<<<<<< SEARCH
        command_policy_gate: CommandPolicyGate | None = None,
    ) -> None:
        self._runtime = runtime
=======
        command_policy_gate: CommandPolicyGate | None = None,
        command_escalations: CommandEscalations | None = None,
    ) -> None:
        self._runtime = runtime
>>>>>>> REPLACE

<<<<<<< SEARCH
        self._command_policy_gate = command_policy_gate

    def _policy_verdict(self, command: Any, cwd: object) -> CommandGateVerdict | None:
=======
        self._command_policy_gate = command_policy_gate
        # AD-1328 S2b (#1530): the runtime's approval route for an escalated command
        # (runtime.command_escalations), injected at registration. None: S2a's refusal.
        self._command_escalations = command_escalations

    async def _escalate(
        self, verdict: CommandGateVerdict, command: str, context: dict[str, Any] | None,
    ) -> tuple[CommandGateVerdict, str | None]:
        """AD-1328 S2b: the verdict to record and the refusal to return for a command the
        policy does not run on its own. ``forbid``, and an ``escalate`` with no approval
        route, keep the S2a refusal; an ``escalate`` goes to ``CommandEscalations``."""
        escalations = self._command_escalations
        if verdict.decision != "escalate" or escalations is None:
            return verdict, verdict.refusal_message
        outcome = await escalations.resolve(verdict, command=command, context=context)
        return outcome.verdict, outcome.message

    def _policy_verdict(self, command: Any, cwd: object) -> CommandGateVerdict | None:
>>>>>>> REPLACE

<<<<<<< SEARCH
            verdict = self._policy_verdict(command, cwd)
            if verdict is not None and not verdict.runs:
                return ToolResult(
                    error=verdict.refusal_message,
                    metadata=policy_result_metadata(verdict),
                )
=======
            verdict = self._policy_verdict(command, cwd)
            if verdict is not None and not verdict.runs:
                # AD-1328 S2b (#1530): an escalation goes to the chain of command. It runs
                # here only under the Captain's approval in this scope, recorded first.
                # ``command`` is the exact str judge accepted (S2a repair r1, F3), so the
                # filed text, the judged text and the spawned text are one object; a raise
                # lands in the handler below with the escalate record and nothing runs.
                verdict, refusal = await self._escalate(verdict, command, context)
                if refusal is not None or not verdict.runs:
                    return ToolResult(
                        error=refusal or verdict.refusal_message,
                        metadata=policy_result_metadata(verdict),
                    )
>>>>>>> REPLACE

<<<<<<< SEARCH
    command_env_passthrough: tuple[str, ...] = (),
    command_policy_gate: CommandPolicyGate | None = None,
) -> int:
=======
    command_env_passthrough: tuple[str, ...] = (),
    command_policy_gate: CommandPolicyGate | None = None,
    command_escalations: CommandEscalations | None = None,
) -> int:
>>>>>>> REPLACE

<<<<<<< SEARCH
                # AD-1328 S2a: the runtime's command policy.
                command_policy_gate=command_policy_gate,
            ),
=======
                # AD-1328 S2a: the runtime's command policy.
                command_policy_gate=command_policy_gate,
                # AD-1328 S2b: its approval route for an escalated command.
                command_escalations=command_escalations,
            ),
>>>>>>> REPLACE

### Section 5 -- `src/probos/startup/finalize.py` (against S2a)

<<<<<<< SEARCH
        count = register_native_swe_tools(
            registry, runtime,
            command_env_passthrough=tuple(config.execution.command_env_passthrough),
            # AD-1328 S2a (#1530): the runtime's one command policy (ProbOSRuntime.__init__).
            command_policy_gate=getattr(runtime, "command_policy_gate", None),
        )
=======
        # AD-1328 S2b (#1530): the approval route for an escalated command; None unless the
        # policy has rules and the approval and request stores run. Exposed for the
        # capability-request router, which records the Captain's decision through it.
        from probos.execution.command_escalation import build_command_escalations

        command_escalations = build_command_escalations(
            gate=getattr(runtime, "command_policy_gate", None),
            approvals=getattr(runtime, "command_approval_store", None),
            requests=getattr(runtime, "capability_request_store", None),
            work_items=getattr(runtime, "work_item_store", None),
            inbox=getattr(config, "approval_inbox", None),
        )
        runtime.command_escalations = command_escalations
        count = register_native_swe_tools(
            registry, runtime,
            command_env_passthrough=tuple(config.execution.command_env_passthrough),
            # AD-1328 S2a (#1530): the runtime's one command policy (ProbOSRuntime.__init__).
            command_policy_gate=getattr(runtime, "command_policy_gate", None),
            command_escalations=command_escalations,
        )
>>>>>>> REPLACE

### Section 6 -- `src/probos/startup/communication.py` (base tree)

Four edits.

<<<<<<< SEARCH
async def init_communication(
=======
async def _start_command_approval_store(
    config: "SystemConfig", data_dir: Path,
) -> "SqliteCommandApprovalStore | None":
    """AD-1328 S2b: command approvals; None unless execution.command_policy has rules,
    so a runtime without a policy creates no database (zero-config boot unchanged)."""
    if not config.execution.command_policy.rules:
        return None
    from probos.execution.command_approvals import SqliteCommandApprovalStore

    store = SqliteCommandApprovalStore(db_path=str(data_dir / "command_approvals.db"))
    await store.start()
    logger.info("AD-1328: command approval store started")
    return store


async def init_communication(
>>>>>>> REPLACE

<<<<<<< SEARCH
    await action_approval_store.start()
    logger.info("action-approval-store started")
=======
    await action_approval_store.start()
    logger.info("action-approval-store started")

    # --- Command Approval Store (AD-1328 S2b) -- the Captain's decisions on escalated
    #     run_command calls and the runs they admitted. Only with policy rules.
    command_approval_store = await _start_command_approval_store(config, data_dir)
>>>>>>> REPLACE

<<<<<<< SEARCH
        continue_extension_permit_store=continue_extension_permit_store,  # AD-1323
    )
=======
        continue_extension_permit_store=continue_extension_permit_store,  # AD-1323
        command_approval_store=command_approval_store,  # AD-1328 S2b
    )
>>>>>>> REPLACE

<<<<<<< SEARCH
    from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
    from probos.decision_pre_clearance import DecisionPreClearanceStore
    from probos.identity import AgentIdentityRegistry
=======
    from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
    from probos.decision_pre_clearance import DecisionPreClearanceStore
    from probos.execution.command_approvals import SqliteCommandApprovalStore  # AD-1328 S2b
    from probos.identity import AgentIdentityRegistry
>>>>>>> REPLACE

### Section 7 -- `src/probos/startup/results.py` (base tree)

Two edits.

<<<<<<< SEARCH
    from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
    from probos.assignment import AssignmentService
=======
    from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
    from probos.execution.command_approvals import SqliteCommandApprovalStore  # AD-1328 S2b
    from probos.assignment import AssignmentService
>>>>>>> REPLACE

<<<<<<< SEARCH
    continue_extension_permit_store: "SqliteContinueExtensionPermitStore | None" = None  # AD-1323
=======
    continue_extension_permit_store: "SqliteContinueExtensionPermitStore | None" = None  # AD-1323
    command_approval_store: "SqliteCommandApprovalStore | None" = None  # AD-1328 S2b
>>>>>>> REPLACE

### Section 8 -- `src/probos/runtime.py` (base tree)

<<<<<<< SEARCH
        self.action_approval_store = comm.action_approval_store  # AD-1154
=======
        self.action_approval_store = comm.action_approval_store  # AD-1154
        self.command_approval_store = comm.command_approval_store  # AD-1328 S2b
>>>>>>> REPLACE

### Section 9 -- `src/probos/startup/shutdown.py` (base tree)

<<<<<<< SEARCH
    # AD-1154: Action approval store (standing, TTL-bounded action approvals)
    if getattr(runtime, 'action_approval_store', None):
=======
    # AD-1328 S2b: command approval store (approvals of escalated commands and their runs)
    if getattr(runtime, 'command_approval_store', None):
        with steps("command approval store stop", runtime.command_approval_store):
            await runtime.command_approval_store.stop()
        runtime.command_approval_store = None
        runtime.command_escalations = None

    # AD-1154: Action approval store (standing, TTL-bounded action approvals)
    if getattr(runtime, 'action_approval_store', None):
>>>>>>> REPLACE

### Section 10 -- `src/probos/routers/capability_requests.py` (base tree)

Three edits.

<<<<<<< SEARCH
from probos.routers.deps import get_runtime
=======
from probos.execution.command_approvals import command_approval_request  # AD-1328 S2b
from probos.routers.deps import get_runtime
>>>>>>> REPLACE

<<<<<<< SEARCH
        return await consumer.fulfil(decided.id) is not None
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
=======
        return await consumer.fulfil(decided.id) is not None
    if command_approval_request(decided) is not None:
        # AD-1328 S2b (#1530): a command escalation. Approval records an approval the
        # agent's next identical call in the same scope uses; it never runs the command
        # from here (AD-1154, BF-830). A denial is recorded so the scope stays denied.
        escalations = getattr(runtime, "command_escalations", None)
        if escalations is None:
            logger.warning(
                "AD-1328: no command approval route is wired; the decision on request %s "
                "is recorded and grants nothing", decided.id[:12],
            )
            return False
        try:
            if not approve:
                await escalations.record_denial(decided)
                return False
            return await escalations.fulfil_approval(store, decided) is not None
        except Exception:
            logger.warning(
                "AD-1328: recording the decision on command request %s failed; the decision "
                "stands and an approval can be retried", decided.id[:12], exc_info=True,
            )
            return False
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
>>>>>>> REPLACE

<<<<<<< SEARCH
    if decided.kind not in _STANDING_RULE_KINDS:
        logger.info(
            "AD-1154: grant_standing ignored for capability request %s — kind "
=======
    if command_approval_request(decided) is not None:  # AD-1328 S2b: no standing rule
        logger.info(
            "AD-1328: command request %s cannot grant a standing rule; an approved command "
            "is reused only in its own scope, policy and approver (command_approvals.db)",
            decided.id[:12],
        )
        return None
    if decided.kind not in _STANDING_RULE_KINDS:
        logger.info(
            "AD-1154: grant_standing ignored for capability request %s — kind "
>>>>>>> REPLACE

### Section 11 -- `src/probos/agents/shell_command.py`

Three edits, all on the final S2a code (`shell_command.py:15`, `:90-91`, `:227-230`).

<<<<<<< SEARCH
from probos.execution.command_gate import COMMAND_POLICY_UNAVAILABLE_MESSAGE, CommandPolicyGate
=======
from probos.execution.command_gate import (
    COMMAND_POLICY_REFUSAL_KEY,
    COMMAND_POLICY_UNAVAILABLE_MESSAGE,
    CommandPolicyGate,
)
>>>>>>> REPLACE

<<<<<<< SEARCH
        success = report.get("success", False)
        self.update_confidence(success)
=======
        success = report.get("success", False)
        # AD-1328 S2b (O-S2a-5): a command-policy refusal is the policy's decision, not
        # this agent's failure, so it does not move the agent's confidence.
        if not report.get(COMMAND_POLICY_REFUSAL_KEY):
            self.update_confidence(success)
>>>>>>> REPLACE

<<<<<<< SEARCH
            return {"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}
        if verdict.runs:
            return None
        return {"success": False, "error": verdict.refusal_message}
=======
            return {"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE, COMMAND_POLICY_REFUSAL_KEY: True}
        if verdict.runs:
            return None
        # AD-1328 S2b: the mesh path has no approval route (every pool member runs the
        # command and the red team re-runs it), so an escalation keeps the S2a refusal.
        return {"success": False, "error": verdict.refusal_message, COMMAND_POLICY_REFUSAL_KEY: True}
>>>>>>> REPLACE

### Section 12 -- `src/probos/execution/storage_declarations.py` (base tree)

<<<<<<< SEARCH
            "and transitions are governance evidence."
        ),
    ),
)
=======
            "and transitions are governance evidence."
        ),
    ),
    StoreDeclaration(
        id="execution.command-approvals",
        title="Command policy approvals and the runs they admitted (AD-1328)",
        owner_module="probos.execution.command_approvals",
        owner_symbol="SqliteCommandApprovalStore",
        canonical_path="command_approvals.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.execution.command_approvals.SqliteCommandApprovalStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "No DELETE statements: each approval or denial and every run it admitted is "
            "governance evidence. Growth is one row per decided escalation and one per run."
        ),
        notes=(
            "Constructed only when execution.command_policy has rules. Rows are written only "
            "from a Captain decision on a run_command action request; a run is recorded "
            "before the command starts."
        ),
    ),
)
>>>>>>> REPLACE

### Section 13 -- `DECISIONS.md` (against S2a)

<<<<<<< SEARCH
- Contract `prompts/ad-1328-s2a-command-policy-wiring.md`.
=======
- Contract `prompts/ad-1328-s2a-command-policy-wiring.md`.

### AD-1328 S2b -- Command policy escalation: filed in the approval inbox, run once under the Captain's approval on re-issue, reused within a work item (2026-10-16, #1530)

- *No replay.* An escalated `run_command` is filed as an AD-1154 `action` request (`run_command` / `execute`) carrying the bounded command, the rules and each cause. The Captain's approval records an approval in `command_approvals.db` and fulfils the request; the command runs when the asking agent issues it again in the same scope, each run admitted by one compare-and-set recorded before it starts (`approved_run`, then `reuse`, each naming the original request).
- *Reuse key.* Agent, scope (crew work item, conversation thread, or none), canonical command key, policy digest and approver authority (the Captain's: every action request is Captain-reserved). Only a work item reuses, until it ends or seven days; a thread or no scope admits one run within an hour. Never across agents; a `forbid` never runs under an approval; a policy change escalates again; no standing rule for a command.
- *Mesh path.* No approval route: every shell pool member executes a mesh `run_command` and the red team re-runs it, so no approval could run it exactly once without changing its consensus mode. The truthful refusal stays; a policy refusal no longer lowers the shell agent's confidence.
- *Records.* The decision record is schema v2 with an `approval` entry (state, and the request and use ids in their closed uuid forms, on an `escalate` record only); the store and the record hold no command text; the request does, because it is the approval surface. The largest admitted record (2,037 characters) stays within the 2,048-character bound; when a whole AD-1224 envelope would exceed 4,096 bytes the sink keeps the compact form, which keeps the `approval` entry.
- *Next.* S2c resumes a parked work item on approval and closes #1530. Contract `prompts/ad-1328-s2b-command-policy-escalation.md`.
>>>>>>> REPLACE

### Section 14 -- `PROGRESS.md` (against S2a)

The first 120 characters carry no ledger status keyword (`scripts/gen_ad_ledger.py:126-139`).

<<<<<<< SEARCH
# ProbOS Progress

**AD-1328 slice S2a (2026-10-16), #1530
=======
# ProbOS Progress

**AD-1328 slice S2b (2026-10-16), #1530 -- an escalated run_command reaches the approval inbox; no new AD or BF number.** `RunCommandTool` files an escalated command as an AD-1154 action request carrying the bounded command, the rules and each cause; the Captain's approval records an approval (`command_approvals.db`) and the agent's next identical call in the same scope runs once, recorded before it starts; within a crew work item later calls reuse it until the item ends, each reuse naming the original approval; a new work item, another agent or a policy change escalates again, a denial stays denied in its scope, and a `forbid` never runs under an approval. The approved command is never replayed. The mesh path keeps its truthful refusal (every pool member would run it), and a policy refusal no longer lowers the shell agent's confidence. S2c (resume on approval, closure) follows in the same PR. Contract `prompts/ad-1328-s2b-command-policy-escalation.md`.

**AD-1328 slice S2a (2026-10-16), #1530
>>>>>>> REPLACE

**Regenerate after installing Sections 1-14** (orchestrator): `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`. No config field is added (no facade, reference or profile regeneration).

---

## Tests (written by Builders against the installed source; tests only)

Rules for every file: never edit `src/`. No real shell (spawn recorders as S2a M2/M3). Real SQLite in `tmp_path` for `SqliteCommandApprovalStore` and `CapabilityRequestStore(db_path=...)`. Gates: `CommandPolicyGate(cfg, platform="linux", which=fake_which)` with S1's `_policy`/`_rule` helpers copied (S2a Tests rule). Inject `clock=` where time matters. Every test asserts its premise and a negative control. All tests OS-independent (CI is Linux, this machine Windows): no path separators in assertions, no host shell.

### M1 `tests/test_ad1328_s2b_approval_store.py` (store and parser)

1. `test_schema_and_restart`: start, record, stop, start again on the same file -> the row and its uses persist; `start` twice is harmless.
2. `test_record_decision_first_wins_and_validates`: a replay with another state returns the first row; each of empty agent, 63-hex key, `scope_key="other:x"`, `ttl_seconds` 0 / NaN, `state="x"`, blank approver raises `ValueError`.
3. `test_find_matches_the_exact_identity[agent, scope, key, digest]`: changing any one -> None (never across agents); expired (clock past `expires_at`) -> None; `state="denied"` and `"active"` never see each other.
4. `test_single_use_scopes_admit_one_run[thread, none]`: `use` -> `approved_run`; second `use` -> None; `find(... state="active")` afterwards -> None. Kills St1.
5. `test_work_item_scope_reuses`: three `use` calls -> `approved_run`, `reuse`, `reuse`; `list_uses` returns them oldest first, each with the original `request_id`. Kills St2.
6. `test_use_requires_the_captain_and_authority`: rows written by raw SQL (stdlib `sqlite3` in the test on the same file after `stop`, then `start`) with `approver="agent-x"` or `approver_authority="first_officer"` -> `use` None.
7. `test_second_approved_run_is_impossible`: inserting a second `approved_run` use row for one request by raw SQL raises `sqlite3.IntegrityError` (partial unique index).
8. `test_failed_use_rolls_back`: a connection wrapper (ConnectionFactory injected) whose `execute` raises on `INSERT INTO command_approval_uses` -> `use` raises; `get(...).uses == 0`; with a normal connection the next `use` is `approved_run`. Kills St3.
9. `test_fails_closed_when_stopped_or_clock_bad`: every method raises `RuntimeError` after `stop`; a NaN clock raises.
10. `test_command_approval_request[valid, wrong_kind, wrong_tool, wrong_action, bad_key, long_digest, bad_scope, scope_names_other_item, missing_id, missing_agent, invalid_payload]`: only `valid` returns the ask (fields equal the payload's). Build requests as `CapabilityRequest(...)` dataclasses.
11. `test_scope_helpers`: `scope_work_item_id`, `valid_scope_key` (a 64-character thread ok, 65 not), `approval_ttl_seconds`; `ENDED_WORK_ITEM_STATUSES == probos.workforce._TERMINAL_STATUSES` (drift guard).

### M2 `tests/test_ad1328_s2b_escalation_service.py` (the service)

Helpers: an escalate gate (rule `git push` escalate with a justification; `unmatched_decision="allow"`), a forbid gate, a verdict from `gate.judge(...)`; `CommandEscalations(gate=..., approvals=store, requests=CapabilityRequestStore(db_path=...), work_items=fake, clock=...)` where `fake.get_work_item(id)` returns `SimpleNamespace(status=...)` from a dict.

1. `test_escalation_scope[crew_item, thread_only, neither, no_agent, bad_item_id, long_thread]`.
2. `test_files_the_escalation_with_its_causes`: outcome message starts with the filed frame, names the request id and the rule's justification, says it was not run; the request is `kind="action"`, payload `tool_id="run_command"`, `action="execute"`, `scope_key="work_item:W1"`, `work_item_id="W1"`, `params.canonical_key == verdict.canonical.key`, `params.policy_digest == gate.digest`, `params.rules` holds the rule, `params.causes[0].text` the justification; `outcome.verdict.record["approval"] == {"state": "filed", "request_id": id, "use_id": None}`; `json.dumps(record)` holds no command text (sentinel word). A repeat returns the same request id (one pending request).
3. `test_forbid_never_reaches_approvals`: spies on `store.find` and `requests.file_action_request`: a forbid verdict -> neither called, message is `verdict.refusal_message`. Kills S-E1.
4. `test_approval_then_run_then_reuse_in_one_work_item`: file, `requests.decide(id, True, decided_by="captain")`, `fulfil_approval(requests, decided)` returns the request with `status == "fulfilled"`; resolve -> `message is None`, `verdict.runs`, approval `approved_run` with the request id and a use id; resolve again -> `reuse` with the same request id.
5. `test_single_use_outside_a_work_item[thread, none]`: approval then resolve -> `approved_run`; again -> filed anew (a new request id).
6. `test_fulfil_refuses[not_captain, other_digest, item_ended, not_approved, not_a_command_request]`: returns None; no row; `mark_fulfilled` not called (spy). Retry after a refusal works once the cause is fixed (BF-722). Kills S-E3, S-E4.
7. `test_scope_end_stops_reuse`: approved in W1, then W1 `done` -> resolve files a new request, nothing runs. Kills S-E2.
8. `test_policy_change_escalates_again`: approve under gate A; a service over gate B (one more rule, other digest) and the same stores -> resolve files. Gate B's `fulfil_approval` of the old request returns None.
9. `test_other_agent_never_uses_the_approval`.
10. `test_denial_sticks_in_its_scope`: `record_denial` after `decide(False)` -> True; resolve -> denied frame with the request id, request count unchanged; outside a scope `record_denial` -> False and the next resolve files. Kills S-E5.
11. `test_inbox_full_files_nothing`: `max_pending_per_agent=1` with one pending -> inbox-full frame, request count unchanged. Kills S-E6.
12. `test_unfiled_paths[store_raises, store_returns_none, payload_invalid, no_agent, count_raises]`: unfiled frame, approval state `unfiled`, nothing runs. `store.find` raising -> filed (never admitted).
13. `test_payload_bounds`: a 10,000-character command and a lone surrogate both file; the canonical JSON of the payload is at most 4,000 characters; the command display ends with `more characters]`.
14. `test_frames_do_not_read_as_a_capability_gap`: every frame formatted with `causes="Rule 'r': Pushes need review."`, `request_id="x"`, `where=""` does not match `probos.cognitive.decomposer._CAPABILITY_GAP_RE`.
15. `test_build_command_escalations[no_gate, unconfigured, no_approvals, no_requests, configured]`: None four times, then a service using the inbox config's cap and window.

### M3 `tests/test_ad1328_s2b_tool_router_shell.py` (tool, gate, router, shell agent)

1. `test_tool_files_then_runs_once_then_reuses`: `RunCommandTool(runtime, command_policy_gate=gate, command_escalations=service)`, context `{"agent_id": "a1", "_crew_work_item_id": "W1"}`: escalate -> no spawn, filed frame, metadata approval `filed`; approve + `fulfil_approval`; invoke -> one spawn with S2a's exact kwargs, metadata approval `approved_run`; invoke -> second spawn, `reuse`.
2. `test_tool_without_a_route_keeps_the_s2a_refusal`: `command_escalations=None` -> S2a frame, no spawn, approval `None`.
3. `test_forbid_with_an_approval_on_record_is_refused`: a forbid rule for `git push`, and an `active` row recorded directly for that canonical key and digest -> no spawn, forbid frame; and `dataclasses.replace(forbid_verdict, approval={"state": "approved_run", ...}).runs is False`. Kills E1.
4. `test_service_error_does_not_spawn`: `resolve` raises -> `run_command failed:`, no spawn.
5. `test_record_v2_validation[none, filed, denied, inbox_full, approved_run, reuse, extra_key, bad_state, list_state, request_id_not_uuid, request_id_upper, use_id_not_hex32, use_id_on_filed, request_id_on_unfiled, run_without_use_id, approval_on_forbid, v1_schema]`: built from a real escalate verdict's record (`approval` set to the case's entry; uuid ids from `str(uuid.uuid4())` and `uuid.uuid4().hex`); `command_policy_record_of` accepts exactly the first six, and for each accepted case returns a dict equal to the input whose `approval` is a new object (rebuilt, not the same dict). `approval_on_forbid` is a forbid verdict's record carrying a `filed` entry. Kills G-E2, G-E3, G-E4.
6. `test_router_fulfils_and_records_denial`: `_maybe_fulfil_on_approval(runtime, store, decided, approve=True)` with `runtime.command_escalations=service` -> True, row active; `approve=False` on a denied request -> False, row denied; no service -> False; service raising -> False; an ordinary browser action request -> False (no fulfiller), service untouched. Kills R-E1.
7. `test_command_request_grants_no_standing_rule`: `_maybe_issue_standing_rule` with `grant_standing=True`, `standing_rules_enabled=True` -> None; the action-approval store untouched. Kills R-E2.
8. `test_existing_router_pins_hold`: `"action" not in _APPROVAL_FULFILLERS`; `_STANDING_RULE_KINDS == {"action", "continue"}`.
9. `test_shell_refusals_do_not_move_confidence[forbid, escalate, judgement_error]`: through `handle_intent`, `confidence` unchanged and `_run_sync` not called; control: a recorder returning `{"success": False, "error": "x"}` lowers it, success raises it. Kills Sh-E1.
10. `test_mesh_escalation_files_nothing`: the shell agent with the escalate gate: `IntentResult.error` contains `no approval was requested`; a `CapabilityRequestStore` in the test has no request afterwards (the agent holds none).
11. `test_the_largest_v2_record_is_within_the_bound` (re-anchor, D5): S2a's B10 maximum rebuilt here (8 rule names of 64 characters, 8 `rule` causes with segment `2**31-1`, both counts `2**31-1`, decision `escalate`, dialect `posix`, kind `script`, hex digests, schema `RECORD_SCHEMA`) with `approval` = `{"state": "approved_run", "request_id": str(uuid.uuid4()), "use_id": uuid.uuid4().hex}`: accepted unchanged and `len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS` (computed 2,037; write the measured length in a comment); the same record with `"approval": None` is 121 characters shorter (control). If the maximum exceeds 2,048, stop and report the measured length: do not move the bound.
12. `test_the_largest_approved_record_is_compacted_with_its_approval` (re-anchor, D5; copy S2a B31's `_MaximalRecordTool` and what it needs -- `_StandInTool`/`_RunCommandStandIn` (`:1237`), `_recorded` (`:997`), `_paired`, `_rows`, `_wide_call` (`:1346-1363`), `_WIDE_COMMAND` (`:1285`), `_SHELL_PERMISSIONS` (`:976`), `_MaximalRecordTool` (`:1558-1562`) -- from `tests/test_ad1328_s2a_run_command_tool.py`; tests do not import each other): no patch, real bound 4,096, provenance `'"' * 200`. Premises: `executor._record_size` of the emitted payload with the #11 record whole is over 4,096, and with `compact_command_policy_record(record)` within it. Assert the emitted payload's `command_policy == compact_command_policy_record(record)`, its `approval` equals the record's, its size is at most 4,096; the same through a real `EventLog` in `tmp_path` (durable row). Control: the same record with `"approval": None` is kept whole (S2a B31's case at v2). Record the measured sizes in a comment (computed about 4,147 emitted and 4,128 durable whole).

### M4 `tests/test_ad1328_s2b_seam_and_wiring.py` (the seam, wiring, golden) and the deliberate edits

1. **`test_seam_escalate_approve_run_once_reuse_then_fresh_escalation`** (crosses tool -> registry -> service -> request store -> REST decision -> fulfilment -> store -> tool): copy the `wired` fixture and `_approve` of `tests/test_ad1211_approval_fulfils_every_kind.py:286-324` (real `CapabilityRequestStore`, `WorkItemStore`, `decide_capability_request`); add `runtime.command_escalations`. A real `ToolRegistry` holding `RunCommandTool(gate, escalations)` with the shell permissions, invoked through a real `ToolExecutor` with `context={"_crew_work_item_id": item.id, "thread_id": "t1"}` for agent `agent-1` at rank `commander`. Steps: escalate (no spawn; one pending request whose payload names the rule and justification) -> `_approve` (response `fulfilled` true) -> re-issue (spawn count 1; one `approved_run` use naming the request) -> re-issue (spawn 2; a `reuse` naming the request) -> the same command in a second work item (new request; spawn 2) -> a new gate with one more rule (other digest) and a new service over the same stores, original work item (new request; spawn 2). Mesh half: a `ShellCommandAgent` with the same escalate gate, through `handle_intent`: `_run_sync` not called, request count unchanged, confidence unchanged.
2. `test_seam_denial`: escalate -> `_approve(..., approve=False)` -> re-issue: denied frame, no new request, no spawn; the work item's status is unchanged (S2b parks nothing, so the AD-855 driver does not cancel it).
3. `test_finalize_builds_and_injects_the_route`: `_wire_native_swe_harness` with a runtime stand-in (gate configured, stores) and `register_native_swe_tools` monkeypatched to capture kwargs -> `command_escalations` passed and `runtime.command_escalations` set; with no rules -> None both places.
4. `test_store_starts_only_with_rules`: `_start_command_approval_store(SystemConfig(), tmp_path)` -> None and no `command_approvals.db`; with one rule -> a started store and the file; stop it.
5. `test_store_declaration_resolves`: `probos.execution.storage_declarations.STORE_DECLARATIONS` holds `execution.command-approvals` whose owner imports.
6. `test_no_policy_is_byte_identical`: re-run S2a M2 #1's assertions with `command_escalations=` a spy service: spy never called; spawn args and result unchanged.

**Deliberate edits** (each with a one-line `# AD-1328 S2b:` comment saying why):

Enumerated on tree `22dd3afc` (grep `record/v`, `_RECORD_KEYS`, `"canonical_kind":`, `{"success": False, "error"` in `tests/test_ad1328_s2a_*.py`); re-grep on the build tree and stop on any further hit:

- `tests/test_ad1328_s2a_gate.py:173-176` (`_RECORD_KEYS` literal): add `"approval"`. Lines `:760`, `:1319-1322` then hold unchanged.
- `tests/test_ad1328_s2a_gate.py:761`: `"probos.command_policy.record/v1"` -> `.../v2`.
- `tests/test_ad1328_s2a_gate.py:832` (`wrong_schema`) and `:1214` (`schema_v2` forgery): the forged schema becomes `"probos.command_policy.record/v1"` (now the wrong one); rename the id `schema_v2` to `schema_v1`.
- `tests/test_ad1328_s2a_gate.py:1327-1349` (B10): no edit needed (its record comes from a gate verdict, so it carries `"approval": None`, 1,916 characters); the maximum with an approval is M3 #11.
- `tests/test_ad1328_s2a_run_command_tool.py:1566-1620` (B31): the hand-built record gains `"approval": None` and its schema becomes `.../v2` (else the projection refuses it); update the comment at `:1617` with the measured sizes (computed about 4,014 emitted and 3,995 durable). The maximal approved record is M3 #12.
- `tests/test_ad1328_s2a_run_command_tool.py:1446-1453` (B16b docstring): replace the S2b sentence with the measured sizes and a pointer to M3 #12. B16b and B16 (`:1371-1439`) need no code edit: their record is a gate verdict's (`approval: null`, about 20 more envelope bytes) and their assertions are relational. If B16's premise `size(compact envelope) <= 3000` fails, stop and report the measured size: do not move the bound.
- `tests/test_ad1328_s2a_run_command_tool.py:1068` (`record/v0`): unchanged (still a wrong schema).
- `tests/test_ad1328_s2a_shell_agent.py:273`, `:382`, `:429`, `:453`, `:630`: the refusal dicts compared by equality gain `COMMAND_POLICY_REFUSAL_KEY: True`.

## What This Does NOT Change

- No replay, no auto-resume, no parking (S2c). The AD-855 driver, `continue_or_ask`, the AD-1154 browser wrapper, `ActionApprovalStore` and the standing-rule kinds are untouched.
- The mesh path's execution, consensus, quorum, red team and escalation cascade; the decomposer; `IntentMessage`.
- The permission ladder, LOTO, the AD-1316 broker (an escalation under the broker is still denied preflight and not filed), `RunCommandTool.input_schema`, every launch line, BF-890/892/893 contracts.
- S1's module and API; S2a's frames' text; config models (no field added).

## Do Not Build

OS sandboxing, egress control, an LLM reviewer, environment scrubbing, a policy language beyond prefix rules, replay on approval, a mesh approval route, standing rules for commands, a config knob for the approval lifetimes (constants until an operator needs them), anything of S2c.

## Acceptance Criteria

1. Sections 1-14 install mechanically; each SEARCH occurs exactly once; `gen_ad_ledger.py` regenerates.
2. With no rules nothing is constructed (no store, no service, no database) and every S2a golden passes unchanged (M4 #4, #6).
3. `escalate` reaches the AD-1154 inbox carrying the rule and justification or the segment reason (M2 #2); the approved command runs exactly once when re-issued and is never replayed (M4 #1); reuse within one work item, each recorded with the original approval (M2 #4, M1 #5); a different command, a new work item, another agent or a policy change escalates again (M4 #1, M2 #8-9); a `forbid` never runs under an approval (M3 #3); denial sticks in its scope (M2 #10).
4. The mesh path files nothing and keeps the truthful refusal; a refusal does not move confidence (M3 #9-10).
5. Records: v2 with `approval`; no command text in the record, the store or new log lines (M2 #2).
6. Every test passes on Windows and Linux.
7. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2b_approval_store.py tests/test_ad1328_s2b_escalation_service.py tests/test_ad1328_s2b_tool_router_shell.py tests/test_ad1328_s2b_seam_and_wiring.py tests/test_ad1328_s2a_gate.py tests/test_ad1328_s2a_run_command_tool.py tests/test_ad1328_s2a_shell_agent.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_ad1328_s2a_r1_real_shells.py -q -n 0`; then `tests/test_ad1224_durable_tool_start.py tests/test_ad1154_approval_inbox.py tests/test_ad1204_approval_resumes_the_turn.py tests/test_ad1211_approval_fulfils_every_kind.py tests/test_ad853_capability_request.py tests/test_ad1175_continue_standing_rule.py tests/test_ad1206_repair_issue.py tests/test_ad544_native_tools.py tests/test_ad1316_governed_effect_broker.py tests/test_bf890_shell_agent_env.py tests/test_bf893_process_tree.py tests/test_cognitive_skill_catalog.py tests/test_ad1187_agent_work_pull.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1184_ad_ledger.py -q -n 0`, plus every file from `grep -l "decide_capability_request\|_maybe_fulfil_on_approval\|_maybe_issue_standing_rule" tests/`.
8. `scripts/check_store_registry.py --check`, `scripts/check_architecture_principles.py --check`, `scripts/check_seam_contracts.py --check` and `scripts/gen_ad_ledger.py --check` exit 0.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden Pins (enumerated)

| Pin | Evidence | Effect |
|---|---|---|
| `"action" not in _APPROVAL_FULFILLERS`; sorted keys | `tests/test_ad1204_approval_resumes_the_turn.py:875`, `tests/test_ad1211_approval_fulfils_every_kind.py:1643-1644`, `tests/test_ad853_capability_request.py:229-231` | Map unchanged (branch before it). Holds. |
| `_STANDING_RULE_KINDS == {"action","continue"}` | `tests/test_ad1175_continue_standing_rule.py:64`, `tests/test_ad1206_repair_issue.py:521` | Unchanged. Holds. |
| `CommunicationResult` field set | `tests/test_cognitive_skill_catalog.py:466-472` (membership only) | Holds. |
| `communication.py` text | `tests/test_ad616_router_hot_path.py:51-53` (`Semaphore`, `_bounded_route`) | Untouched. Holds. |
| `shutdown.py` text | `tests/test_bf781_isolation_claims.py:245-369` (specific strings) | Untouched strings. Holds. |
| S2a record v1 / key set / v2-as-forgery; refusal dict equality | `test_ad1328_s2a_gate.py:173-176`, `:761`, `:832`, `:1214`; `test_ad1328_s2a_shell_agent.py:273`, `:382`, `:429`, `:453`, `:630` | Deliberate edits (Tests). |
| S2a record budget (B10, B16, B16b, B31) | `test_ad1328_s2a_gate.py:1327-1349`; `test_ad1328_s2a_run_command_tool.py:1371-1439`, `:1442-1493`, `:1566-1620` | B10 holds (1,916); B16/B16b relational, hold (stop if B16's compact premise fails); B31 edited to v2; the approval maximum is M3 #11-#12 (D5). |
| S2a mutation G2 anchor (`return self.status == "no_policy" or self.decision == "allow"`) | S2a campaign | Anchor gone; E1 replaces it. Rerun every other S2a row whose file S2b changes (`command_gate.py`, `swe_harness/tools.py`, `agents/shell_command.py`) and whose anchor still occurs exactly once. |
| Store registry (`scripts/check_store_registry.py` rules 1-11) | new `CREATE TABLE` module | Declared in `execution/storage_declarations.py`, already in `DECLARATION_MODULES`. |
| Direct connect (`check_architecture_principles.py:192`) | ConnectionFactory only | Holds. |
| SRP sizes (500 lines, 15 methods) | `SqliteCommandApprovalStore` 10, `CommandEscalations` 7, `RunCommandTool` 4 -> 5, `CommandGateVerdict` 6 -> 7 | Holds. |
| AD ledger head window | Section 14's first 120 characters | No keyword. |
| Seam manifest | `p0-manifest.yaml:47-57` | Untouched (S2c). |

## Verified Against Codebase (2026-10-16, re-anchored on tree `22dd3afc46cae65fe60e1f5bdc4c0f90b51fee7b`, S1 final + S2a final)

Re-anchor pass (2026-10-16): every SEARCH of Sections 3, 4, 5, 6-12 read against the file on this tree; files S1/S2a did not touch (`git diff 26250c9c HEAD --stat`: `capability_request.py`, `routers/capability_requests.py`, `delegated_approvals.py`, `startup/communication.py`, `startup/results.py`, `startup/shutdown.py`, `workforce.py`, `agentic_dispatch.py`, `config_models/experience.py` and the other base-tree citations) keep their base line numbers.

```
git rev-parse HEAD^{tree}                           -> 22dd3afc46cae65fe60e1f5bdc4c0f90b51fee7b
src/probos/execution/command_gate.py (final S2a)
  :26-29 docstring tail;  :42 `from dataclasses import dataclass`;  :69 RECORD_SCHEMA v1;  :71 MAX_RECORD_CHARS = 2048
  :82-83 _ESCALATE_FRAME comment;  :92-95 _RECORD_KEYS;  :319-322 verdict fields;  :328-331 runs;  :371-372 record tail
  :379 policy_result_metadata;  :389 _RECORD_SCHEMAS = frozenset({RECORD_SCHEMA});  :417-428 _cause_of
  :431 command_policy_record_of(result, *, tool_id);  :449-461 checks tuple (:460 causes check);  :467-481 rebuilt dict + bound
  :485-494 compact_command_policy_record keeps **record;  :535-542 CommandPolicyGate(config, *, platform, which, is_file)
  :590-598 judge(command, *, site, search_path, cwd, pathext);  :168-173 _pathext None outside _PATHEXT_GRAMMAR
  :210-218 make_program_resolver(*, dialect, search_path, cwd, pathext, which, is_file);  :250-251 posix built-in -> None
src/probos/execution/command_policy.py:450-474      -> CanonicalCommand(kind, dialect, parts).key = sha256 hex
  :377-392 CommandEvaluation.decision/.dialect/.policy_digest;  :1891-1903 _canonical_program (built-in -> its name);  :1906-1931 canonical_command never raises
src/probos/cognitive/swe_harness/tools.py:24-29 imports;  :1137-1139 ctor tail;  :1145-1147 `_policy_verdict(self, command: Any, cwd)`
  :1204-1209 judge then refuse;  :1211-1212 spawn `str(command) if verdict is None else command`;  :1247-1251 except keeps metadata
  :1263-1265 register signature;  :1306-1308 RunCommandTool kwargs
src/probos/startup/finalize.py:1776-1781 register_native_swe_tools call (S2a);  :5586 _wire_native_swe_harness call
src/probos/agents/shell_command.py:15 import;  :50, :56, :59 descriptor;  :77-100 handle_intent (:90-91 confidence);  :227-230 refusals
src/probos/agents/red_team.py:311-313, :406-430    -> S2a: a refused command is not re-run
src/probos/tools/executor.py:52 _RECORD_MAX_BYTES = 4096;  :1108-1117 _record_size;  :1134-1146 _bounded_policy_record;  :1224-1227 projection call
tests/test_ad1328_s2a_run_command_tool.py:1442-1453 B16b (3,994 / 3,975 measured);  :1566-1620 B31 (v1 record, no approval)
tests/test_ad1328_s2a_gate.py:173-176, :761, :832, :1214, :1327-1349 (B10)
src/probos/capability_request.py:742                -> request id = str(uuid.uuid4())
gh issue view 1530                                  -> acceptance + 2026-10-14 amendment quoted in Problem (first draft)
prompts/ad-1328-s2a-repair-r1.md:865 (H8), prompts/ad-1328-s2a-repair-r2.md:509 (H11), prompts/ad-1328-s2a-command-policy-wiring.md:1529-1536 (amendments)
prompts/ad-1328-s1-repair-r3.md:905 (H8: canonical_command keys unchanged)
src/probos/capability_request.py:34, :794-802       -> approval does not replay an action
  :73-87 payload keys/bounds, THREAD_ID_MAX_CHARS;  :165-230 validate_action_payload;  :456-482 action_dedup_key
  :779-839 file_action_request(agent_id, payload, *, rationale, work_item_id);  :931-946 count_pending_sync(agent_id, *, stale_before)
  :948-1035 decide (decided_by default "captain");  :1037-1073 mark_fulfilled emits FULFILLED
src/probos/routers/capability_requests.py:18-20, :31-36 imports;  :158-216 _decide_request (decided_by="captain" :169)
  :247-256 action has no fulfiller;  :423-428 _APPROVAL_FULFILLERS;  :451-462 repair subtype before the map;  :463-465 `if not approve`
  :523 _STANDING_RULE_KINDS;  :579-594 repair refusal then kind check
src/probos/delegated_approvals.py:12-15, :171-172   -> every action request CAPTAIN_RESERVED
src/probos/continue_extension_permits.py:1-31, :529-568 -> activate/consume compare-and-set precedent
src/probos/storage/declarations.py:131-139 (canonical_path .. notes);  src/probos/execution/storage_declarations.py:11-28 (anchor :25-28, `"and transitions are governance evidence."` -- the first draft's SEARCH lacked "and ")
src/probos/tools/registry.py:461-467                -> ctx["agent_id"] set, tool.invoke(params, ctx)
src/probos/tools/executor.py:720, :724              -> caller context reaches check_and_invoke
src/probos/cognitive/agentic_dispatch.py:109-127 context keys, _CREW_WORK_ITEM_ID_RE;  :222 inbox tools {"browser"};  :252-262 AD-1154 frames
  :777-788 _crew_work_item_id to _park_or_admit;  :1335-1387 pending cap;  :1458-1496 _MeshIntentTool;  :1826-1871 mesh tool specs
  :2412-2415 work_item_id_provider;  :2447-2463 tier-floor park not for crew children;  :3405-3417 inbox armed by config
src/probos/cognitive/swe_harness/agentic_loop.py:147-155 PARALLEL_SAFE_TOOL_IDS (no run_command)
src/probos/cognitive/swe_harness/native_builder.py:46-56, :139-172 (agent "swe", no work item)
src/probos/cognitive/cognitive_agent.py:2340-2372   -> plain work items: no work item id in the tool context
src/probos/cognitive/capability_gap_driver.py:16-26, :229-289, :291-340
src/probos/cognitive/continue_or_ask.py:592-640;  src/probos/cognitive/tier_floor_ask.py:151-153
src/probos/runtime.py:4406-4443 broadcast, :4541-4545 red-team re-runs;  :640 command_policy_gate;  :3179, :3245, :3296 store assignments (:3296 Section 8 anchor);  :3451 finalize_startup
src/probos/consensus/escalation.py:108-145 BF-830;  :453-457, :484-518 Tier-3 re-execution;  src/probos/experience/shell.py:146
src/probos/types.py:58-74 IntentMessage;  :948-961 consensus_mode;  src/probos/cognitive/intent_grants.py:9-16
src/probos/cognitive/decomposer.py:50-57 _CAPABILITY_GAP_RE;  :945-989 DAG node -> submit_intent_with_consensus
src/probos/startup/communication.py:23-25 imports;  :277-300 AD-1323 helper;  :303 init_communication;  :730-731 action store;  :936 result kwarg
src/probos/startup/results.py:21-22, :202;  src/probos/startup/shutdown.py:1752-1756;  src/probos/startup/finalize.py:1740 (S2a section: :1776-1781)
src/probos/workforce.py:114 _TERMINAL_STATUSES;  :7740 get_work_item
src/probos/config_models/experience.py:15, :158, :170;  src/probos/config.py:3967 approval_inbox
src/probos/routers/capability_requests.py:43 get_runtime import;  :462-465 repair fulfil, `if not approve`, fulfiller lookup;  :586-588 standing-rule kind check
docs/development/seams/p0-manifest.yaml:47-57;  scripts/check_architecture_principles.py:192;  scripts/gen_ad_ledger.py:126-139
docs/development/architecture-baseline.yaml:870-878 ProbOSRuntime srp-size triggers only (no counts)
tests/test_ad1211_approval_fulfils_every_kind.py:286-324 (wired fixture use, _approve)
```

## Absence Verified (2026-10-16)

```
CLAIM: no crew agent can originate a mesh run_command
RUN:   Grep '"run_command"' src/probos ; read _MESH_TOOL_SPECS, _MESH_READ_INTENT_POOLS, exposable_intents
FOUND: (re-run 2026-10-16 on tree 22dd3afc) shell_command.py:50,56,59; red_team.py:103; command_gate.py:388 (record tool id);
       effect_broker.py:338; panels.py:1220; runtime.py:6319; decomposer.py:176,185 / prompt_builder.py:98,107,382
       examples; llm_client.py:3197 (mock); swe_harness tools.py:1110, native_builder.py:51, policies.py:52.
       Mesh tools: web_search, read_page, http_fetch (agentic_dispatch.py:1826-1871); DM reads exclude it (dm/reply_pipeline.py:72-80);
       federation refuses consensus-flagged intents (federation/mcp_server.py:77-78)
HOLDS: yes -- the mesh path is reached from the decomposer DAG (Captain requests, persistent tasks) and the cascade only

CLAIM: only crew children carry a work item id into the tool context
RUN:   Grep '"_crew_work_item_id":' src/probos ; Grep '_crew_work_item_id"\] =' src/probos
FOUND: crew_verifier.py:1536, :2112; crew_executor.py:1930
HOLDS: yes (plain work items and promoted DM turns: O-S2b-1)

CLAIM: the Tier-3 user callback is wired only in the interactive shell
RUN:   Grep 'set_user_callback\(|user_callback=' src/probos
FOUND: escalation.py:77 (definition); experience/shell.py:146
HOLDS: yes

CLAIM: nothing named command_approval / command_escalation exists
RUN:   Grep 'command_approval|command_escalation|CommandEscalations' over the repository except prompts/ (re-run on tree 22dd3afc)
FOUND: none
HOLDS: yes

CLAIM: no test source-scans the router, finalize's harness wiring or results.py lines S2b edits
RUN:   Grep 'routers/capability_requests\.py|startup/communication\.py|startup/results\.py|shutdown\.py"' tests
FOUND: test_ad616_router_hot_path.py:51 (Semaphore/_bounded_route only); test_bf781_isolation_claims.py:245 (other strings);
       test_ad1195_durable_producers.py:46 (event-log producers; S2b adds none)
HOLDS: yes

CLAIM: run_command is not parallel-safe in a loop
RUN:   Grep 'PARALLEL_SAFE_TOOL_IDS\b.*=' src/probos
FOUND: agentic_loop.py:147-155 (web_search, read_page, http_fetch, search_capabilities, event_log_query)
HOLDS: yes
```

## Prior Art and Blind Spots

- **Internal.** AD-1323 permits (`continue_extension_permits.py`): one compare-and-set per transition, no DELETE, activation only by someone other than the asker -- **adopted** for the store. AD-1206 repair subtype before the fulfiller map -- **adopted** for the router branch. AD-1154 DD-2 voice and dedup -- **adopted** for frames and filing. AD-1154's "approval does not replay" and BF-830's re-execution finding -- **adopted** (no replay). `docs/research/codex-harness-absorption.md` (S1's citation) -- the canonical key is S1's.
- **OpenAI Codex.** Session approvals are keyed narrowly: an `ApprovedForSession` decision is cached per session keyed on the script path for skill scripts, and `apply_patch` session approval is an allowlist of absolute file paths, auto-approving only when every path was approved ([commit #12758 and related, via mirror](https://forge.lthn.ai/core/core-agent-ide/commit/14116ade8d8eb8066cb84b65b63f640a3cdd72e7)). **Adopted:** reuse keyed on an exact canonical identity and bounded by a scope (ours: the work item, not the session). **Adapted:** the scope also ends on a policy digest change and is bound to the approver's authority, which Codex's local single-user cache does not need. Not confirmed from these sources: how Codex keys ordinary shell commands (S1 used `command_canonicalization.rs`).
- **Claude Code permission prompts.** "Don't ask again" for Bash writes a rule to `.claude/settings.local.json` that applies to future sessions in the repository; a compound command saves one rule per subcommand ([permissions docs](https://code.claude.com/docs/en/permissions)). **Rejected** for ProbOS: a persistent cross-scope rule is what AD-1154 standing rules are, and #1530 requires reuse to expire with its scope; the router refuses `grant_standing` for commands. **Considered, deferred:** per-segment approvals for compound commands (S1's canonical key makes a compound command a `script` key, approved whole).
- **Reference projects** (`docs/research/reference-projects.md`, date used 2026-10-16): OpenAI Codex (2026-10-14) and Claude Code (2026-10-16) are current; row update for Claude Code: add "approval persistence scope (don't ask again) for AD-1328 S2b". No overdue project searched.
- **Blind spots.** (1) The mesh path executes a command on every pool member and every red-team agent re-runs it (D3); an approval there cannot be exactly once -- follow-up recommended. (2) `file_action_request` finds then files without a lock (`capability_request.py:821-839`): two concurrent identical asks can file twice; each approval still admits its own runs only. (3) The pending cap is checked before dedup (as AD-1154): a repeat at the cap is refused as inbox-full. (4) A crash between the use commit and the spawn loses that run; a re-issue in a work item reuses. (5) The child environment and PATH can change between filing and approval; the canonical `argv` key includes the resolved program, so a moved program escalates again. (6) The command text in the request payload is bounded (1,200 characters); the Captain approves the canonical key, which covers the full text. (7) `RunCommandTool` already logs full command text on failure (`tools.py:1248`), outside this slice. (8) S2a r2: a bare `/bin/sh` built-in keys as its name, not the `which` path, so `echo x` and `/bin/echo x` are different commands to approval reuse (they run different programs); cmd internals were already `script` keys. (9) S1 r3: restrictive rules also match argument words and a shell word in an argument position is unparseable, so more commands escalate or forbid; a `forbid` still never reaches the service, and the key and digest scope the rest unchanged.

## Mutation campaign of record

Run once by the orchestrator on the committed S2b tree after M1-M4 pass. Anchors are single lines that occur exactly once in the named file; replacements are literal. Record the base commit and each file's sha256; a later candidate reruns only rows whose file changed. Also rerun every S2a row (original campaign and repairs r1/r2) on `execution/command_gate.py`, `cognitive/swe_harness/tools.py` and `agents/shell_command.py` whose anchor still occurs exactly once (those files change); G2's anchor is gone (E1 replaces it).

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| E1 | execution/command_gate.py | `return approved and self.decision == "escalate"` | `return approved` | M3 #3 |
| G-E2 | execution/command_gate.py | `_valid_approval(record["approval"], record["decision"]),  # AD-1328 S2b` | `True,` | M3 #5 |
| G-E3 | execution/command_gate.py | `if decision != "escalate" or type(value) is not dict or set(value) != _APPROVAL_KEYS:` | `if type(value) is not dict or set(value) != _APPROVAL_KEYS:` | M3 #5 `approval_on_forbid` |
| G-E4 | execution/command_gate.py | `"use_id": record["approval"]["use_id"],` | `"use_id": None,` | M3 #5, #12 |
| St1 | execution/command_approvals.py | `"AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",` | `"",` | M1 #4 |
| St2 | execution/command_approvals.py | `use_kind="approved_run" if int(row[0]) == 1 else "reuse",` | `use_kind="reuse",` | M1 #5 |
| St3 | execution/command_approvals.py | `await _rollback(db)  # a failed use record must not leave the increment` | `pass` | M1 #8 |
| S-E1 | execution/command_escalation.py | `if verdict.decision != "escalate" or verdict.canonical is None or verdict.evaluation is None:` | `if verdict.canonical is None or verdict.evaluation is None:` | M2 #3 |
| S-E2 | execution/command_escalation.py | `if row is not None and await self._scope_open(scope.scope_key):` | `if row is not None:` | M2 #7 |
| S-E3 | execution/command_escalation.py | `if self._gate.digest != ask.policy_digest:` | `if False:` | M2 #6, #8 |
| S-E4 | execution/command_escalation.py | `if getattr(decided, "decided_by", None) != CAPTAIN:` | `if False:` | M2 #6 |
| S-E5 | execution/command_escalation.py | `if denied is not None:` | `if False:` | M2 #10 |
| S-E6 | execution/command_escalation.py | `if pending >= self._max_pending:` | `if False:` | M2 #11 |
| R-E1 | routers/capability_requests.py | `return await escalations.fulfil_approval(store, decided) is not None` | `return False` | M3 #6, M4 #1 |
| R-E2 | routers/capability_requests.py | `if command_approval_request(decided) is not None:  # AD-1328 S2b: no standing rule` | `if False:` | M3 #7 |
| Sh-E1 | agents/shell_command.py | `if not report.get(COMMAND_POLICY_REFUSAL_KEY):` | `if True:` | M3 #9 |
| F-E1 | startup/finalize.py | `command_escalations=command_escalations,` | `command_escalations=None,` | M4 #3 |

Equivalent-mutant notes: replacing `if verdict.decision != "escalate" or escalations is None:` in `RunCommandTool._escalate` with `if escalations is None:` is equivalent (S-E1's guard returns the same refusal); not listed. St3: with the rollback removed, the failed transaction leaves `uses` incremented on the open connection; M1 #8 observes it through `get`. No mutant can loop.

## Milestones

| M | Scope | Calls (about) |
|---|---|---|
| Install | Sections 1-14 by script; `gen_ad_ledger.py` (orchestrator) | n/a |
| M1 | `tests/test_ad1328_s2b_approval_store.py` | 90 |
| M2 | `tests/test_ad1328_s2b_escalation_service.py` | 110 |
| M3 | `tests/test_ad1328_s2b_tool_router_shell.py` | 100 |
| M4 | `tests/test_ad1328_s2b_seam_and_wiring.py`, the deliberate edits, then the focused gate and checks (acceptance 7-8) | 120 |
| Campaign | the table above, once, on the committed tree | n/a |

=== BUILDER BRIEFS ===

### Brief M1 -- `tests/test_ad1328_s2b_approval_store.py`

Write tests only; never edit `src/`. Target: `probos.execution.command_approvals`. Implement M1 #1-11 from `prompts/ad-1328-s2b-command-policy-escalation.md` ("Tests"). Real SQLite in `tmp_path`; inject `clock=`; raw-SQL rows through stdlib `sqlite3` only while the store is stopped. Mutants to kill: St1-St3. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2b_approval_store.py -q -n 0`. Stop and report rather than weaken a test.

### Brief M2 -- `tests/test_ad1328_s2b_escalation_service.py`

Write tests only. Target: `probos.execution.command_escalation`. Implement M2 #1-15. Real `SqliteCommandApprovalStore` and `CapabilityRequestStore(db_path=...)` in `tmp_path`; a dict-backed work-item stand-in; gates built with `platform="linux"` and a fake `which`. Check frames against the real `probos.cognitive.decomposer._CAPABILITY_GAP_RE`. Mutants: S-E1..S-E6. Run the file with `-n 0`.

### Brief M3 -- `tests/test_ad1328_s2b_tool_router_shell.py`

Write tests only. Targets: `RunCommandTool` (`src/probos/cognitive/swe_harness/tools.py`), `command_policy_record_of`, `probos.routers.capability_requests._maybe_fulfil_on_approval` / `_maybe_issue_standing_rule`, `ShellCommandAgent.handle_intent`. Implement M3 #1-12. Spawn recorders as S2a M2/M3. Mutants: E1, G-E2, G-E3, G-E4, R-E1, R-E2, Sh-E1. #11 and #12 are measurements of record (D5): write the measured sizes in comments; if #11's maximum exceeds 2,048 or #12's compact envelope exceeds 4,096, stop and report -- do not move a bound. Run the file with `-n 0`, then `tests/test_ad1224_durable_tool_start.py -q -n 0`.

### Brief M4 -- `tests/test_ad1328_s2b_seam_and_wiring.py` and the deliberate edits

Write tests only. Implement M4 #1-6; copy the `wired` fixture and `_approve` from `tests/test_ad1211_approval_fulfils_every_kind.py` (around `:230-324`) rather than importing them. M4 #1 is the seam test of record: one test, real stores, real registry and executor, the real `decide_capability_request`, both paths. Then make the deliberate edits to S2a tests, each with a `# AD-1328 S2b:` comment. Mutant: F-E1. Run the focused gate (acceptance 7) and the four checks (acceptance 8); report every count and exit code.
