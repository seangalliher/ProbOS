# AD-1337 S2 (#1560): the producer seam. Every result a tool registry returns is masked before the timing, the post-hooks, the broker and the caller see it

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev1
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev2: section 17, the repair after review round 1 (the priming gate, the rotation fence, the store file's first load)

**Status:** rev1. Rev0 was proven on an oracle tree (section 16); rev1 adds two test cases (N20, N21) and changes no source pair. Batch 1 is S1 + S2 + S3: one PR (`Refs #1560`), one broad gate. S2 must not merge alone. Decision: consult `4bb6d748` (on #1560, comment 7064966284), corrected here in C1 to C5. No Captain condition.

**Base:** `origin/main` (`5d8a5eb4`) plus S1 as committed on the build branch, ending at `53696f68`. S2 uses S1's API exactly as its section 6 gives it.

**Line endings:** every edited file is `i/lf w/crlf` (`git ls-files --eol`). The SEARCH blocks are LF; match and write each file with its own endings. The new test file is LF and ASCII only. No SEARCH contains a character outside ASCII.

**Milestones** (one Builder delegation each; the Builder applies the pairs and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then 7.2 to 7.6 (X1 to X16), then 7.7 to 7.10 (F1 to F12) | HIGH, shared contract (executor behaviour, a new event type) | One full review by the GPT Diff Reviewer, plus `claude-diff-reviewer` |
| M2 | 7.11 (TR1), 7.12 (TR2), then 7.13 (the ledger) | LOW | Delta |

- Commit subjects:
  - M1: `Mask tool results where the registry returns them`
  - M2: `Record the producer seam in the status and decisions entries`
- About 40 Builder tool calls for M1 and 12 for M2.

## 0. Premises (this tree)

| P | Premise | Evidence |
|---|---|---|
| P1 | Every executor path runs `_invoke_once`, and the registry result is bound at `:720-730` before the timing (`:763`) and the post-hooks (`:765-784`) | `executor.py:608-786`; `invoke` `:799-909` (broker-less `:813`, reserved `:852-884`); `_invoke_reserved_body` `:788-797`; `DispatchToolExecutor.invoke` `agentic_dispatch.py:1539-1552`; guard body `:805-946` calls `super()._invoke_reserved_body` at `:921` |
| P2 | Three production executor constructions | `finalize.py:5834-5837`, `agentic_dispatch.py:3013-3016` (per dispatch), `agentic_dispatch.py:972` (`super().__init__`). `executor.py:490` is a docstring. |
| P3 | Dispatch wires durable hooks only, with no `emit_fn` | `agentic_dispatch.py:3068-3073`; `executor.py:1471-1494` |
| P4 | The broker digests only the outcome, the output type and whether an error is present; a `failed` attempt is terminal and a retry of it is suppressed as a duplicate | `effect_broker.py:920-951`; `authority.py:2129-2134` |
| P5 | AD-1224 records take explicit fields, never the `InvocationContext` as a whole | `executor.py:987-995`, `:1069-1088`, `:1216-1231`; no `asdict`/`fields`/`vars` over it in `src` (Absence Verified) |
| P6 | A new member must be declared, or `probos.events` fails at import; a DURABLE member that is not owner-written is routed | `event_persistence.py:1-13`, `:47-108`, `:476-478` |
| P7 | `CredentialStore` is built unconditionally in `ProbOSRuntime.__init__` and never reassigned | `runtime.py:492`, `:740-742`; `rg "\.credential_store = " src` finds only `runtime.py:740` |
| P8 | The store path is set at `finalize.py:4690-4705`, before the executor at `:5834` | read |
| P9 | `get` in a worker thread: the tier and department gates run, the CLI has a 5 s timeout, a missing `gh` returns None, and no access row is written | S1 tree `credential_store.py:290-347`, `:376-385`, `:400-415`; the `github` spec has no `min_tier` (`:107-113`) |
| P10 | `ToolExecutor` spans 479 lines with 12 methods and is not baselined (gate: >500 lines or >15 methods); `WorkItemAgenticExecutor` and `EventType` are baselined by key | `check_architecture_principles.py:187-188`, `:559-569`; `architecture-baseline.yaml:350`, `:675` |
| P11 | S1's N31 pins `masked_credential_values` to two files in `src` | S1 tree `tests/test_ad1337_secret_masking.py:509-516`. No S2 source line may name it. |
| P12 | `MaskedResult.names` is a `frozenset[str]` (iteration order is hash-dependent), and `MaskedResult` is a `NamedTuple` | S1 tree `security/secret_masking.py:84-90` |
| P13 | `CredentialStore.get(name, *, requester="unknown", department=None, tier=None)`; `_log_access` writes `agent_type=requester` when a loop is running | S1 tree `credential_store.py:273-280`, `:400-415` |

## 1. Problem

S1's masker has no caller. A tool's output, such as `gh auth token` run by `run_command` or `cat .env`, reaches the post-hooks, the effect broker, `repair_verification` and the model unmasked. `ToolExecutor.invoke` is not one boundary: `DispatchToolExecutor.invoke` skips it on its non-protected path (P1).

## 2. Overview

| Part | Change |
|---|---|
| `tools/executor.py` | `ToolExecutor(secret_masker=None)` and the `secret_masker` property; the seam in `_invoke_once`; `InvocationContext.secrets_masked` / `.secret_masking_failed`; `_checked_secret_masker`, `_mask_registry_result`, `make_secret_masked_hook`, `wire_secret_masked_event`, `SECRET_MASKED_MAX_NAMES`; `wire_tool_invocation_hooks` calls the wiring |
| `events.py`, `event_persistence.py` | `EventType.SECRET_MASKED`, declared DURABLE and routed |
| `cognitive/agentic_dispatch.py` | The mixin forwards the masker; `_runtime_secret_masker`; each dispatch executor gets the masker and the event hook |
| `startup/finalize.py` | `_wire_secret_masker` (sets `runtime.secret_registry`, `runtime.secret_masker`, `runtime.secret_masking_prime_task`) and `_prime_secret_masking`; the runtime executor gets the masker |
| AD-1195 freeze tests | Counts 395->396 members, 29->30 routed, 37->38 DURABLE, 41->42 declared; one producer row |

**Heavier designs rejected:**
- Mask in `invoke`: it misses the dispatch non-protected path (P1).
- Run the pass in `asyncio.to_thread`: the pool hop costs more than a typical pass (0.026 ms), and the worst measured pass is 22 ms (1 MiB, 50 values).
- An owner-written row with `parent_event_id`: a second writer beside the router (C3).
- A config switch: consult Q6.
- Cancel the priming task at shutdown: the CLI's 5 s timeout bounds it (O5 checks this).

## 3. Consumers checked

| Changed | Consumer | Result |
|---|---|---|
| Result masked before the post-hooks | AD-1224 audit (`classify_tool_error` on the masked error), AD-1168 telemetry, dispatch `_record_tool_result` (`agentic_dispatch.py:3028-3066`), `confinement.record_admitted` (`:944-945`), `_bound_browser_output` and `_with_disposition` (`:937-943`) | Each sees the masked result. A subclass keeps its type (S1 D5). |
| Masked result into the broker | `effect_broker.py:920-951` | A hit leaves the digest unchanged (outcome, type, error presence). A withheld result is recorded `failed`, terminal and duplicate-suppressed, so the tool never runs twice (N6). |
| `self_query` presentation identity | `agentic_loop.py:2730-2874` (`raw_result.output is retained_presentation[0]`, `:2848`) | On a hit the output object changes, the check fails, and the model is told "presentation check failed": fail closed, accepted by consult Q4. **S3 owns this test** (its loop fixtures). |
| `hook_count` | `test_ad448_wrapped_tool_executor.py:199`; `test_ad1224_durable_tool_start.py:819, 822, 828, 2833, 1074` | Unchanged: the event hook is wired only when the executor has a masker, and none of these executors has one |
| New `EventType` | `test_events.py:58, 406, 440`; `test_ad1131...:1953` | Iteration only; unchanged |
| New DURABLE routed member | `test_ad1195_durable_event_seam.py:328-332`; `..._event_persistence_contract.py:394-407, 447, 457, 508-514, 592`; `..._durable_producers.py:35-69, 162, 172`; `..._eventlog_pair_freeze.py:513` | F1 to F12. ACCEPT-1 and the BYTE tests run on the new member automatically. |
| `finalize_startup` | MagicMock rigs (`test_new_crew_auto_welcome.py`, `test_ad1270a_startup_receipts.py:402-531`, `test_ad641d`, `test_bf235`); receipts AST (`test_ad1270a...:364-399`: `begin` (`:4186`) before the first `_wire_`) | A MagicMock store gives no masker and no task, and does not crash; the new call is after `:4186` |
| Real-runtime boots (93 test files) | They now spawn one `gh auth token` in a worker thread unless `GH_TOKEN` resolves | Accepted, bounded by the 5 s timeout; O5 measures it |
| Dispatch golden | `test_ad1152_agentic_correlation.py`; its runtime has no `secret_masker` | Unchanged |
| SRP gate | `ToolExecutor` 479->488 lines, 12->13 methods; `architecture-baseline.yaml` unchanged (sha pin `test_ad1324_srp_layout.py:29`) | Passes (O4) |

**Not checked:** the vessel's own boot, the vessel's `.env`, or `gh` on the vessel. A real `ProbOSRuntime.start()` in a temporary data directory is O7.

## 4. Decisions

- **D1 (seam, (a)).** In `_invoke_once`, right after the registry `try` returns and before `ctx.duration_ms`. Every path in P1 passes it, and the post-hooks, the broker and the caller see the masked result.

  | Path | Masked here? | Why |
  |---|---|---|
  | Registry returned a `ToolResult` (including its own not-found or permission results) | Yes | Tool output |
  | Ambiguous name (`:640-645`), pre-hook abort (`:709`), dispatch guards (`agentic_dispatch.py:856-919`), broker `result=None` (`executor.py:892-895`) | No | Fixed text, the model's own tool name, or a reason code |
  | Registry raised (`:731-761`) | No | Terminal hooks get only `_exception_category`. The exception's text reaches the model as `Tool X failed: ...` and is the render seam's (S3). `ToolLockedDenied.result` is registry text; S3 also covers it. |
  | Registry returned something that is not a `ToolResult` | Withheld | Fail closed |

- **D2 (inline, (b)).** The pass runs on the loop:
  - a pass with no hit costs 0.026 ms on a short text, 3.3 ms on 1 MiB with 10 values, and 22 ms on 1 MiB with 50 values (S1 O6);
  - the first store read moves off the loop with the priming: since section 17 (RC11) its worker also runs one empty masking pass, so the store file loads and the table is built there whichever step resolves `github` (rev1 claimed this, but with `GH_TOKEN` set the priming read no file and the first pass loaded it on the loop); after a load that failed, S1 reads the file on every pass, by design;
  - what would change this: a live p99 above 10 ms, in which case a size-gated `to_thread` follows.
- **D3 (failure, (c)).** S1's withheld result (`MASKING_FAILED_TEXT`, metadata kept) replaces the result, and `ctx.secret_masking_failed = True`.
  - Every post-hook and the broker see it: outcome `failed`, terminal, a retry duplicate-suppressed (P4).
  - Operator signal: S1's ERROR line (exception type only) plus `SECRET_MASKED` with `failed: true`. One event type, not two.
- **D4 (wiring, (d)).**
  - `_wire_secret_masker(runtime=)`, called in `finalize_startup` before `if runtime.tool_registry:`:
    - always sets `runtime.secret_registry = SecretRegistry()` (S4 registers there);
    - sets `runtime.secret_masker` only when `runtime.credential_store` is a real `CredentialStore`, otherwise None plus one WARNING;
    - starts `runtime.secret_masking_prime_task`, which runs `get("github", requester="secret_masking")` in `asyncio.to_thread`, catches every exception (type name only) and never blocks startup. The requester is a system name, never a crew one, because `_log_access` attributes a read by it (P13; N21 pins it).
  - Dispatch passes `_runtime_secret_masker(runtime)`, which turns a MagicMock or a missing attribute into None.
  - `ToolExecutor` refuses any masker that is not a `SecretMasker` (`TypeError`), so a wiring bug cannot pass silently. `secret_masker=None` stays the default for bare test executors.
- **D5 (context, (e)).** Two fields, both `init=False`: `secrets_masked: tuple[str, ...] = ()` (sorted labels, whatever order the masker's `frozenset` iterates in; N20 pins it) and `secret_masking_failed: bool = False`. Set only by the seam, read only by the event hook. The AD-1224 projector and schemas are untouched (P5).
- **D6 (event, (f)).** `EventType.SECRET_MASKED = "secret_masked"`, DURABLE and routed: the runtime's emit writes the events.db row.
  - The payload has exactly eight keys: `seam` (`"producer"`), `tool_id` (the retention-safe `record_tool_id`; None for a strict call), `invocation_id`, `operation_id`, `attempt_id`, `names` (at most 16, sorted), `names_omitted`, `failed`. No agent id, no value, no form, no position.
  - At most one event per call, only on a hit or a withheld result.
  - `wire_secret_masked_event(executor, emit_fn=)` adds the hook only when the executor has a masker and `emit_fn` is set. It is called from `wire_tool_invocation_hooks` (the runtime executor) and in dispatch. That is not lifecycle traffic: it fires only on a hit.
  - The hook calls `emit_fn(EventType.SECRET_MASKED, ...)` directly, because AD-1195's PROD-1 looks for that call shape.
- **D7 (census, (g)).** N19 is an AST check over `src/probos`:
  - each `ToolExecutor(` / `DispatchToolExecutor(` call and each `super().__init__(registry=...)` passes `secret_masker=`, with exactly these sources: `_runtime_secret_masker(runtime)`, the mixin's `secret_masker`, and finalize's `secret_masker`;
  - finalize's name is assigned once, from `_wire_secret_masker(runtime=runtime)`;
  - `ProbOSRuntime.__init__` assigns `self.credential_store = CredentialStore(...)` unconditionally.
  
  Together these make "no masker" impossible in production, while tests keep the default None. S3 extends this census to `AgenticLoop(` and must not duplicate it.

## 5. Tests: new file `tests/test_ad1337_executor_seam.py` (21 cases)

| N | Case |
|---|---|
| N1 | Direct path: output and error masked before every post-hook; metadata identity kept; context fields set |
| N2 | No match: the same result object; no event |
| N3 | Dispatch executor: the masker is forwarded; the non-protected path masks |
| N4 | `_runtime_secret_masker`: a real masker, a missing attribute, a MagicMock |
| N5 | A real `WorkItemAgenticExecutor.run`: the model's second request shows the placeholder and never the token; one `SECRET_MASKED` |
| N6 | Strict broker: masked; then a failed pass is withheld, `failed` and terminal; a retry is suppressed and the tool ran twice in total; strict payload |
| N7 | A failed pass withholds from every post-hook; the event has `failed: true`; no token in the logs |
| N8 | A non-`ToolResult` registry answer is withheld |
| N9 | Pre-hook abort and a registry raise never call the masker |
| N10 | Bare executor: identity; non-maskers refused; `InvocationContext` defaults and `init=False` |
| N11 | Payload: exact keys, a 16-label cap, nothing emitted when nothing was masked |
| N12 | Strict payload has no tool id; an emit failure never raises |
| N13 | The event hook is wired only with a masker and an emitter; `wire_tool_invocation_hooks` gives 2 hooks |
| N14 | Real emit, then router, then events.db: row recorded; no form of the token in the DB bytes |
| N15 | `SECRET_MASKED` is a routed DURABLE member |
| N16 | Finalize builds the masker and registry and primes `github` in a worker thread; the registry is the masker's |
| N17 | A MagicMock store: no masker, no task, a WARNING, no crash |
| N18 | Priming never raises; a missing `gh` leaves the value unprimed; no token in the logs |
| N19 | The construction census (D7) |
| N20 | One pass through the real seam masks three labels (`github` from the store, `vault:a` and `vault:b` from the registry), and the masker hands back its labels in reverse-sorted order every run. `invocation.secrets_masked` and the event's `names` are still the sorted sequence. |
| N21 | Finalize's priming task reads exactly `get("github", requester="secret_masking")`: no department, no tier, never a crew-looking requester |

- **Base (`53696f68`):** collection error `ImportError: cannot import name 'SECRET_MASKED_MAX_NAMES' from 'probos.tools.executor'`.
- **After M1:** 21 passed.

## 6. What S3 and S4 need from S2

- **S3:**
  - emit `SECRET_MASKED` with `seam: "render"` and the same eight keys;
  - test the `self_query` fail-closed case (section 3);
  - extend N19's census to `AgenticLoop(`, reusing its helper.
- **S4:** `runtime.secret_registry.register(...)`; the registry always exists after finalize.

## 7. The contract

### 7.1 New file `tests/test_ad1337_executor_seam.py` (M1, written first)

```python
"""AD-1337 S2 (#1560): the producer seam. Every result a tool registry returns is masked before the timing, the
post-hooks, the broker and the caller see it, and SECRET_MASKED records which labels were masked, never a value.

Contract: prompts/ad-1337-s2-producer-seam.md. The owner (SecretMasker) is S1's; the render seam is S3's.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import probos
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import DispatchToolExecutor, WorkItemAgenticExecutor
from probos.credential_store import CredentialStore
from probos.event_persistence import OWNER_RECORDS, Persistence, is_routed, persistence_of
from probos.events import EventType
from probos.security import secret_masking
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    EnvSecretSource,
    SecretMasker,
    SecretRegistry,
    secret_forms,
)
from probos.startup import finalize
from probos.substrate.durable_events import ROUTED_VALUES, durable_answer
from probos.substrate.event_log import EventLog
from probos.tools.executor import (
    SECRET_MASKED_MAX_NAMES,
    InvocationContext,
    ToolExecutor,
    make_secret_masked_hook,
    wire_secret_masked_event,
    wire_tool_invocation_hooks,
)
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from tests.test_ad1195_durable_event_seam import _bound_router
from tests.test_ad1195_durable_producers import _BusHost
from tests.test_ad1224_durable_tool_start import _dispatch_runtime, _offering_store
from tests.test_ad1316_governed_effect_broker import _invoke, strict_runtime  # noqa: F401 -- strict_runtime is a fixture

TOKEN = "tok-S2v9Lq4Xw7Rb2Mn6"
CLI_TOKEN = "gho-cli-only-K8d3Pz5Tq1"
VAULT_A = "va-Rk3Wn8Ps1Ty6"
VAULT_B = "vb-Hd5Qm2Lx9Zc4"
PLACEHOLDER = "<secret:github>"
BUILTIN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "PROBOS_DISCORD_TOKEN", "LLM_API_KEY")
_SRC = Path(probos.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _no_builtin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The built-in specs read these names; no test depends on the shell's values."""
    for name in BUILTIN_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test runs gh: the CLI step fails as if gh were not installed (N16 replaces this)."""

    def _run(argv: list[str], **_kwargs: Any) -> None:
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired),
    )


def _store(directory: Path, entries: dict[str, str] | None = None) -> CredentialStore:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "secrets.json"
    if entries is not None:
        path.write_text(json.dumps(entries), encoding="utf-8")
    return CredentialStore(store_path=path)


def _masker(directory: Path) -> SecretMasker:
    """The store names TOKEN ``github``; the environment source is empty, so no shell variable can match."""
    return SecretMasker(
        credential_store=_store(directory, {"github": TOKEN}),
        registry=SecretRegistry(),
        env_source=EnvSecretSource({}),
    )


class _EchoTool:
    """A registered tool that returns the same result object on every call."""

    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "AD-1337 S2 probe"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(
        self, tool_id: str, output: Any = None, *, error: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> None:
        self.tool_id = tool_id
        self.name = tool_id
        self.metadata = metadata if metadata is not None else {}
        self.result = ToolResult(output=output, error=error, metadata=self.metadata)
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return self.result


def _registry(*tools: Any) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


class _StubRegistry:
    """A registry that answers with ``answer`` or raises ``raises``."""

    def __init__(self, *, answer: Any = None, raises: BaseException | None = None) -> None:
        self._answer = answer
        self._raises = raises

    def list_ids(self) -> list[str]:
        return ["echo"]

    async def check_and_invoke(self, agent_id: str, tool_id: str, params: dict[str, Any], **_kwargs: Any) -> Any:
        if self._raises is not None:
            raise self._raises
        return self._answer


class _Events:
    """An emit_fn that keeps (event, payload) pairs; extra arguments are accepted and ignored."""

    def __init__(self) -> None:
        self.pairs: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event: Any, payload: Any = None, *_args: Any, **_kwargs: Any) -> None:
        self.pairs.append((event, dict(payload) if isinstance(payload, dict) else {}))

    def masked(self) -> list[dict[str, Any]]:
        return [payload for event, payload in self.pairs if event is EventType.SECRET_MASKED]


class _CapturingLLM:
    """The dispatch run's model: one call of ``tool_id``, then ``done``; keeps every request."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id
        self.requests: list[Any] = []

    async def complete(self, req: Any, **_kwargs: Any) -> Any:
        from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

        self.requests.append(req)
        if len(self.requests) == 1:
            block = ToolUseBlock(tool_call=ToolCallRequest(name=self._tool_id, arguments={}))
            return SimpleNamespace(content_blocks=[block], content="", tokens_used=1)
        return SimpleNamespace(content_blocks=[], content="done", tokens_used=1)


def _raise_values(_store: CredentialStore) -> tuple[tuple[str, str], ...]:
    raise RuntimeError(TOKEN)


# -- N1 to N5: where the seam sits ------------------------------------------------------------------------------


async def test_the_direct_path_masks_output_and_error_before_every_post_hook(tmp_path: Path) -> None:
    tool = _EchoTool("echo", {"lines": [f"token={TOKEN}"], "count": 1}, error=f"warning {TOKEN}")
    executor = ToolExecutor(registry=_registry(tool), secret_masker=_masker(tmp_path))
    seen: list[tuple[InvocationContext, ToolResult]] = []
    executor.add_post_hook(lambda ctx, result: seen.append((ctx["invocation"], result)))

    result = await executor.invoke("agent-1", "echo", {})

    assert result.output == {"lines": [f"token={PLACEHOLDER}"], "count": 1}
    assert result.error == f"warning {PLACEHOLDER}"
    assert result.metadata is tool.metadata
    [(invocation, observed)] = seen
    assert observed is result
    assert (invocation.secrets_masked, invocation.secret_masking_failed) == (("github",), False)


async def test_no_match_returns_the_registry_result_and_emits_nothing(tmp_path: Path) -> None:
    tool = _EchoTool("echo", "nothing to hide here")
    executor = ToolExecutor(registry=_registry(tool), secret_masker=_masker(tmp_path))
    events = _Events()
    assert wire_secret_masked_event(executor, emit_fn=events) is True
    seen: list[InvocationContext] = []
    executor.add_post_hook(lambda ctx, _result: seen.append(ctx["invocation"]))

    result = await executor.invoke("agent-1", "echo", {})

    assert result is tool.result
    assert (seen[0].secrets_masked, seen[0].secret_masking_failed) == ((), False)
    assert events.pairs == []


async def test_the_dispatch_executor_forwards_the_masker_and_masks_on_its_non_protected_path(tmp_path: Path) -> None:
    masker = _masker(tmp_path)
    tool = _EchoTool("echo", f"token={TOKEN}")
    executor = DispatchToolExecutor(registry=_registry(tool), secret_masker=masker)
    assert executor.secret_masker is masker
    assert executor.protected_effects_enabled is False  # premise: invoke goes straight to _invoke_reserved_body

    result = await executor.invoke("agent-1", "echo", {})

    assert result.output == f"token={PLACEHOLDER}" and tool.calls == 1


def test_the_runtime_masker_reaches_a_dispatch_executor_only_when_it_is_real(tmp_path: Path) -> None:
    masker = _masker(tmp_path)
    assert agentic_dispatch._runtime_secret_masker(SimpleNamespace(secret_masker=masker)) is masker
    assert agentic_dispatch._runtime_secret_masker(SimpleNamespace()) is None
    assert agentic_dispatch._runtime_secret_masker(MagicMock()) is None


async def test_a_dispatch_run_shows_the_model_the_placeholder_and_emits_secret_masked(tmp_path: Path) -> None:
    tool = _EchoTool("echo_dispatch", f"token={TOKEN}")
    runtime = _dispatch_runtime(
        registry=_registry(tool), event_log=None, perm_store=await _offering_store("agent-s2", "echo_dispatch"),
    )
    runtime.secret_masker = _masker(tmp_path)
    events = _Events()
    runtime.emit_event = events
    llm = _CapturingLLM("echo_dispatch")

    result = await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="agent-s2", instructions="Test instructions.", task_text="use the probe", runtime=runtime,
    )

    assert result.final_text == "done" and tool.calls == 1
    shown = repr(llm.requests[1])
    assert PLACEHOLDER in shown and TOKEN not in shown
    [payload] = events.masked()
    assert (payload["names"], payload["seam"], payload["failed"]) == (["github"], "producer", False)
    assert TOKEN not in json.dumps(events.pairs, default=repr)


# -- N6 to N9: the broker, failure, and the paths that never reach the registry ----------------------------------


async def test_the_broker_path_masks_before_the_broker_and_a_withheld_attempt_is_terminal(
    strict_runtime: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, broker, registry, _ = strict_runtime
    tool = _EchoTool("echo_strict", f"token={TOKEN}")
    registry.register(tool)
    executor = ToolExecutor(registry=registry, effect_broker=broker, secret_masker=_masker(tmp_path / "masker"))
    events = _Events()
    assert wire_secret_masked_event(executor, emit_fn=events) is True

    masked = await _invoke(executor, "echo_strict", "logical-masked")
    assert masked.output == f"token={PLACEHOLDER}"
    assert masked.metadata["effect_outcome"] == "result"

    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)
    withheld = await _invoke(executor, "echo_strict", "logical-withheld")
    assert (withheld.output, withheld.error) == (None, MASKING_FAILED_TEXT)
    assert withheld.metadata["effect_outcome"] == "failed"
    again = await _invoke(executor, "echo_strict", "logical-withheld", provider_id="another-provider-call")
    assert again.metadata["duplicate_suppressed"] is True
    assert tool.calls == 2

    first, second = events.masked()
    assert first == {
        "seam": "producer", "tool_id": None, "invocation_id": first["invocation_id"],
        "operation_id": masked.metadata["operation_id"], "attempt_id": masked.metadata["attempt_id"],
        "names": ["github"], "names_omitted": 0, "failed": False,
    }
    assert (second["names"], second["failed"], second["operation_id"]) == (
        [], True, withheld.metadata["operation_id"],
    )


async def test_a_failed_pass_withholds_the_output_from_every_post_hook_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)
    tool = _EchoTool("echo", f"token={TOKEN}", metadata={"kept": True})
    executor = ToolExecutor(registry=_registry(tool), secret_masker=_masker(tmp_path))
    events = _Events()
    wire_secret_masked_event(executor, emit_fn=events)
    seen: list[ToolResult] = []
    executor.add_post_hook(lambda _ctx, result: seen.append(result))

    result = await executor.invoke("agent-1", "echo", {})

    assert (result.output, result.error) == (None, MASKING_FAILED_TEXT)
    assert result.metadata is tool.metadata
    assert len(seen) == 1 and seen[0] is result
    assert [(payload["names"], payload["failed"]) for payload in events.masked()] == [([], True)]
    assert TOKEN not in caplog.text


async def test_a_registry_answer_that_is_not_a_tool_result_is_withheld(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    executor = ToolExecutor(registry=_StubRegistry(answer=f"raw {TOKEN}"), secret_masker=_masker(tmp_path))
    events = _Events()
    wire_secret_masked_event(executor, emit_fn=events)

    result = await executor.invoke("agent-1", "echo", {})

    assert type(result) is ToolResult and (result.output, result.error) == (None, MASKING_FAILED_TEXT)
    assert [(payload["names"], payload["failed"]) for payload in events.masked()] == [([], True)]
    assert "returned str, not a ToolResult" in caplog.text and TOKEN not in caplog.text


async def test_the_paths_that_never_reach_the_registry_are_left_to_the_render_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    masker = _masker(tmp_path)
    calls: list[ToolResult] = []
    original = masker.mask_result

    def _spy(result: ToolResult) -> Any:
        calls.append(result)
        return original(result)

    monkeypatch.setattr(masker, "mask_result", _spy)
    aborting = ToolExecutor(registry=_registry(_EchoTool("echo", "x")), secret_masker=masker)
    aborting.add_pre_hook(lambda _ctx: False)
    refused = await aborting.invoke("agent-1", "echo", {})
    assert refused.error == "Pre-hook aborted invocation of echo"

    raising = ToolExecutor(registry=_StubRegistry(raises=RuntimeError("tool failed")), secret_masker=masker)
    with pytest.raises(RuntimeError, match="tool failed"):
        await raising.invoke("agent-1", "echo", {})
    assert calls == []


# -- N10 to N15: the executor's contract and the event ------------------------------------------------------------


async def test_a_bare_executor_masks_nothing_and_a_non_masker_is_refused(tmp_path: Path) -> None:
    tool = _EchoTool("echo", f"token={TOKEN}")
    bare = ToolExecutor(registry=_registry(tool))
    assert bare.secret_masker is None
    assert await bare.invoke("agent-1", "echo", {}) is tool.result
    for bad in (MagicMock(), object(), "masker"):
        with pytest.raises(TypeError):
            ToolExecutor(registry=_registry(), secret_masker=bad)
        with pytest.raises(TypeError):
            DispatchToolExecutor(registry=_registry(), secret_masker=bad)
    context = InvocationContext(agent_id="a", tool_id="t", params={})
    assert (context.secrets_masked, context.secret_masking_failed) == ((), False)
    with pytest.raises(TypeError):
        InvocationContext(agent_id="a", tool_id="t", params={}, secrets_masked=("github",))  # type: ignore[call-arg]


def test_the_event_names_labels_only_bounded_and_nothing_when_nothing_was_masked() -> None:
    events = _Events()
    hook = make_secret_masked_hook(events)
    invocation = InvocationContext(agent_id="agent-1", tool_id="echo", params={"query": TOKEN})
    invocation.record_tool_id = "echo"
    hook({"invocation": invocation}, ToolResult(output="x"))
    assert events.pairs == []

    names = tuple(f"name{index:02d}" for index in range(SECRET_MASKED_MAX_NAMES + 4))
    invocation.secrets_masked = names
    hook({"invocation": invocation}, ToolResult(output="x"))

    assert SECRET_MASKED_MAX_NAMES == 16
    assert events.pairs == [(EventType.SECRET_MASKED, {
        "seam": "producer", "tool_id": "echo", "invocation_id": invocation.invocation_id,
        "operation_id": None, "attempt_id": None,
        "names": list(names[:SECRET_MASKED_MAX_NAMES]), "names_omitted": 4, "failed": False,
    })]
    assert TOKEN not in json.dumps(events.pairs)


def test_a_strict_call_names_no_tool_and_a_failed_emit_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    events = _Events()
    invocation = InvocationContext(
        agent_id="agent-1", tool_id="echo", params={}, operation_id="op-1", attempt_id="at-1",
    )
    invocation.record_tool_id = "echo"
    invocation.secrets_masked = ("github",)
    make_secret_masked_hook(events)({"invocation": invocation}, ToolResult(output="x"))
    [payload] = events.masked()
    assert (payload["tool_id"], payload["operation_id"], payload["attempt_id"]) == (None, "op-1", "at-1")

    def _broken(_event: Any, _payload: dict[str, Any]) -> None:
        raise RuntimeError("bus down")

    make_secret_masked_hook(_broken)({"invocation": invocation}, ToolResult(output="x"))
    assert "SECRET_MASKED could not be emitted" in caplog.text


def test_the_event_hook_is_wired_only_with_a_masker_and_an_emitter(tmp_path: Path) -> None:
    bare = ToolExecutor(registry=_registry())
    assert wire_secret_masked_event(bare, emit_fn=_Events()) is False and bare.hook_count == 0
    masked = ToolExecutor(registry=_registry(), secret_masker=_masker(tmp_path))
    assert wire_secret_masked_event(masked, emit_fn=None) is False and masked.hook_count == 0
    assert wire_tool_invocation_hooks(masked, emit_fn=_Events()) is False
    assert masked.hook_count == 2  # AD-1224's live audit hook, then SECRET_MASKED's


async def test_secret_masked_reaches_events_db_through_the_runtime_emit_with_no_value_form(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.db")
    await log.start()
    try:
        router = _bound_router(log)
        host = _BusHost(router)
        tool = _EchoTool("echo", f"token={TOKEN}")
        executor = ToolExecutor(registry=_registry(tool), secret_masker=_masker(tmp_path / "masker"))
        wire_tool_invocation_hooks(executor, emit_fn=host.emit_event)

        result = await executor.invoke("agent-1", "echo", {})
        stats = await router.drain(wait_budget_s=5.0)

        assert result.output == f"token={PLACEHOLDER}"
        assert (stats.offered, stats.written) == (1, 1)
        answer = await durable_answer(log, EventType.SECRET_MASKED, router=router)
        assert answer.status == "recorded" and answer.row is not None
        payload = answer.row["data"]["payload"]
        assert (payload["names"], payload["seam"], payload["tool_id"], payload["failed"]) == (
            ["github"], "producer", "echo", False,
        )
        assert payload["invocation_id"]
        stored = b"".join(path.read_bytes() for path in sorted(tmp_path.glob("events.db*")))
        assert b"github" in stored
        assert [form for form in secret_forms(TOKEN) if form.encode("utf-8") in stored] == []
    finally:
        await log.stop()


def test_secret_masked_is_a_routed_durable_member() -> None:
    assert EventType.SECRET_MASKED.value == "secret_masked"
    assert persistence_of("SECRET_MASKED") is Persistence.DURABLE
    assert is_routed("SECRET_MASKED") and "SECRET_MASKED" not in OWNER_RECORDS
    assert "secret_masked" in ROUTED_VALUES


# -- N16 to N19: startup wiring, priming, and the construction census ---------------------------------------------


async def test_finalize_builds_one_masker_on_the_runtime_and_primes_github_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append((list(argv), threading.get_ident()))
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
    runtime = SimpleNamespace(credential_store=_store(tmp_path))

    masker = finalize._wire_secret_masker(runtime=runtime)

    assert isinstance(masker, SecretMasker) and runtime.secret_masker is masker
    assert isinstance(runtime.secret_registry, SecretRegistry)
    task = runtime.secret_masking_prime_task
    assert isinstance(task, asyncio.Task) and task.get_name() == "secret_masking_prime"
    await task
    assert [argv for argv, _ in calls] == [["gh", "auth", "token"]]
    assert calls[0][1] != threading.get_ident()
    assert masker.mask_text(f"out {CLI_TOKEN}").text == f"out {PLACEHOLDER}"
    with runtime.secret_registry.register("vault:site", "vault-value-123"):
        assert masker.mask_text("vault-value-123").text == "<secret:vault:site>"


async def test_finalize_without_a_real_store_builds_no_masker_and_starts_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = SimpleNamespace(credential_store=MagicMock())
    assert finalize._wire_secret_masker(runtime=runtime) is None
    assert runtime.secret_masker is None and runtime.secret_masking_prime_task is None
    assert isinstance(runtime.secret_registry, SecretRegistry)
    assert "AD-1337: no CredentialStore" in caplog.text


async def test_priming_never_raises_and_a_missing_gh_only_leaves_the_value_unprimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.startup.finalize")
    store = _store(tmp_path)
    await finalize._prime_secret_masking(store)
    assert "github credential primed for masking (found=False)" in caplog.text

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(TOKEN)

    monkeypatch.setattr(store, "get", _boom)
    await finalize._prime_secret_masking(store)
    assert "priming the github credential for masking failed (RuntimeError)" in caplog.text
    assert TOKEN not in caplog.text


def _calls_building_a_tool_executor() -> list[tuple[str, ast.Call]]:
    found: list[tuple[str, ast.Call]] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            named = (isinstance(func, ast.Name) and func.id in {"ToolExecutor", "DispatchToolExecutor"}) or (
                isinstance(func, ast.Attribute) and func.attr in {"ToolExecutor", "DispatchToolExecutor"}
            )
            super_init = (
                isinstance(func, ast.Attribute) and func.attr == "__init__"
                and isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Name)
                and func.value.func.id == "super" and any(k.arg == "registry" for k in node.keywords)
            )
            if named or super_init:
                found.append((path.relative_to(_SRC).as_posix(), node))
    return found


def test_every_tool_executor_construction_passes_the_runtime_masker() -> None:
    sources = sorted(
        (rel, ast.unparse(keyword.value) if keyword is not None else "<missing>")
        for rel, call in _calls_building_a_tool_executor()
        for keyword in [next((k for k in call.keywords if k.arg == "secret_masker"), None)]
    )
    assert sources == [
        ("cognitive/agentic_dispatch.py", "_runtime_secret_masker(runtime)"),
        ("cognitive/agentic_dispatch.py", "secret_masker"),
        ("startup/finalize.py", "secret_masker"),
    ]
    finalize_tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes().decode("utf-8"))
    startup = next(
        node for node in finalize_tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "finalize_startup"
    )
    assigned = [
        ast.unparse(node) for node in ast.walk(startup)
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["secret_masker"]
    ]
    assert assigned == ["secret_masker = _wire_secret_masker(runtime=runtime)"]
    runtime_tree = ast.parse((_SRC / "runtime.py").read_bytes().decode("utf-8"))
    runtime_class = next(n for n in runtime_tree.body if isinstance(n, ast.ClassDef) and n.name == "ProbOSRuntime")
    init = next(n for n in runtime_class.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    stores = [
        ast.unparse(stmt.value.func) for stmt in init.body
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
        and [ast.unparse(t) for t in stmt.targets] == ["self.credential_store"]
    ]
    assert stores == ["CredentialStore"]  # unconditional, so finalize always has a real store to mask with


# -- N20 and N21: the order of the labels, and who the priming read is attributed to ------------------------------


class _ReverseSortedNames(frozenset):
    """A frozenset that iterates in reverse-sorted order, so a seam that does not sort the labels fails every run,
    not only when the hash order happens to differ."""

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(frozenset.__iter__(self), reverse=True))


async def test_the_seam_records_the_labels_of_one_pass_in_sorted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SecretRegistry()
    masker = SecretMasker(
        credential_store=_store(tmp_path, {"github": TOKEN}), registry=registry, env_source=EnvSecretSource({}),
    )
    registry.register("vault:b", VAULT_B)
    registry.register("vault:a", VAULT_A)
    original = masker.mask_result
    reordered: list[frozenset[str]] = []

    def _reverse_names(result: ToolResult) -> Any:
        masked = original(result)
        names = _ReverseSortedNames(masked.names)
        reordered.append(names)
        return masked._replace(names=names)

    monkeypatch.setattr(masker, "mask_result", _reverse_names)
    tool = _EchoTool("echo", f"b={VAULT_B} t={TOKEN} a={VAULT_A}")
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    events = _Events()
    assert wire_secret_masked_event(executor, emit_fn=events) is True
    seen: list[InvocationContext] = []
    executor.add_post_hook(lambda ctx, _result: seen.append(ctx["invocation"]))

    result = await executor.invoke("agent-1", "echo", {})

    assert result.output == f"b=<secret:vault:b> t={PLACEHOLDER} a=<secret:vault:a>"
    [names] = reordered
    assert tuple(names) == ("vault:b", "vault:a", "github")  # premise: the masker's own order is not sorted
    assert seen[0].secrets_masked == ("github", "vault:a", "vault:b")
    [payload] = events.masked()
    assert (payload["names"], payload["names_omitted"]) == (["github", "vault:a", "vault:b"], 0)
    assert all(value not in json.dumps(events.pairs) for value in (TOKEN, VAULT_A, VAULT_B))


async def test_priming_reads_github_as_the_secret_masking_system_requester(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    reads: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _recording_get(*args: Any, **kwargs: Any) -> None:
        reads.append((args, kwargs))
        return None

    monkeypatch.setattr(store, "get", _recording_get)
    runtime = SimpleNamespace(credential_store=store)

    assert isinstance(finalize._wire_secret_masker(runtime=runtime), SecretMasker)
    await runtime.secret_masking_prime_task

    # The requester is how the store attributes a read (_log_access writes agent_type=requester): a system read
    # must never look like a crew member's, and it carries no department or tier.
    assert reads == [(("github",), {"requester": "secret_masking"})]
```

### 7.2 `src/probos/tools/executor.py` (M1)

**X1.** SEARCH (`:37-39`):
```
    from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)
```
REPLACE:
```
    from probos.security.secret_masking import SecretMasker
    from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)
```

**X2.** SEARCH (`:482-483`):
```
    record_completed: bool = field(default=False, init=False)
    start_event_id: int | None = field(default=None, init=False)
```
REPLACE:
```
    record_completed: bool = field(default=False, init=False)
    start_event_id: int | None = field(default=None, init=False)
    # AD-1337 S2: set by the producer seam (_mask_registry_result): the labels it masked, never a value, and
    # whether the pass failed and withheld the output. Read by the SECRET_MASKED post-hook only.
    secrets_masked: tuple[str, ...] = field(default=(), init=False)
    secret_masking_failed: bool = field(default=False, init=False)
```

**X3.** SEARCH (`:502-509`):
```
    def __init__(
        self,
        *,
        registry: Any,
        effect_broker: "GovernedEffectBrokerProtocol | None" = None,
    ) -> None:
        self._registry = registry
        self._effect_broker = effect_broker
```
REPLACE:
```
    def __init__(
        self,
        *,
        registry: Any,
        effect_broker: "GovernedEffectBrokerProtocol | None" = None,
        secret_masker: "SecretMasker | None" = None,
    ) -> None:
        self._registry = registry
        self._effect_broker = effect_broker
        self._secret_masker = _checked_secret_masker(secret_masker)  # AD-1337 S2: None masks nothing
```

**X4.** SEARCH (`:761-765`):
```
            raise

        ctx.duration_ms = max(0.0, (time.perf_counter() - ctx.start_time) * 1000)

        for hook in self._post_hooks:
```
REPLACE:
```
            raise

        if self._secret_masker is not None:  # AD-1337 S2: the producer seam, before the timing and every post-hook
            result = _mask_registry_result(self._secret_masker, ctx, result)
        ctx.duration_ms = max(0.0, (time.perf_counter() - ctx.start_time) * 1000)

        for hook in self._post_hooks:
```

**X5.** SEARCH (`:956-959`):
```
    @property
    def hook_count(self) -> int:
        """Total registered hooks."""
        return len(self._pre_hooks) + len(self._post_hooks) + len(self._terminal_hooks)
```
REPLACE:
```
    @property
    def hook_count(self) -> int:
        """Total registered hooks."""
        return len(self._pre_hooks) + len(self._post_hooks) + len(self._terminal_hooks)

    @property
    def secret_masker(self) -> "SecretMasker | None":
        """AD-1337 S2: the masker applied to every result the registry returns, or None."""
        return self._secret_masker
```

**X6.** SEARCH (`:967-969`):
```
def _invocation(ctx: dict[str, Any]) -> InvocationContext | None:
    invocation = ctx.get("invocation")
    return invocation if type(invocation) is InvocationContext else None
```
REPLACE:
```
def _invocation(ctx: dict[str, Any]) -> InvocationContext | None:
    invocation = ctx.get("invocation")
    return invocation if type(invocation) is InvocationContext else None


def _checked_secret_masker(masker: Any) -> "SecretMasker | None":
    """AD-1337 S2: the executor's masker is a ``SecretMasker`` or None; anything else is a wiring bug."""
    if masker is None:
        return None
    from probos.security.secret_masking import SecretMasker

    if not isinstance(masker, SecretMasker):
        raise TypeError("secret_masker must be a SecretMasker or None")
    return masker


def _mask_registry_result(masker: "SecretMasker", ctx: InvocationContext, result: Any) -> "ToolResult":
    """AD-1337 S2: the producer seam, for every result the registry returns, before the timing, the post-hooks,
    the broker and the caller see it.

    The paths that never reach the registry are not masked here: an ambiguous name, a pre-hook abort and a dispatch
    guard return fixed text, and a raised exception never becomes a ``ToolResult`` here. Its text reaches the model
    as ``Tool X failed: ...``, which the render seam (AD-1337 S3) masks. A pass that fails, or a registry answer that
    is not a ``ToolResult``, withholds the output (fail closed).
    """
    from probos.security.secret_masking import MASKING_FAILED_TEXT
    from probos.tools.protocol import ToolResult

    if not isinstance(result, ToolResult):
        logger.error(
            "AD-1337: tool=%s returned %s, not a ToolResult; the output is withheld",
            ctx.record_tool_id, type(result).__name__,
        )
        ctx.secret_masking_failed = True
        return ToolResult(error=MASKING_FAILED_TEXT)
    masked = masker.mask_result(result)
    ctx.secrets_masked = tuple(sorted(masked.names))
    ctx.secret_masking_failed = masked.failed
    return masked.result
```

**X7.** SEARCH (`:1509-1510`):
```
    executor.add_post_hook(make_audit_hook(emit_fn=emit_fn))
    return wired
```
REPLACE:
```
    executor.add_post_hook(make_audit_hook(emit_fn=emit_fn))
    wire_secret_masked_event(executor, emit_fn=emit_fn)  # AD-1337 S2: inert without a masker
    return wired


#: AD-1337 S2: the most labels one SECRET_MASKED event lists; the rest are counted in ``names_omitted``.
SECRET_MASKED_MAX_NAMES = 16


def make_secret_masked_hook(emit_fn: Callable[[Any, dict[str, Any]], None]) -> PostHook:
    """AD-1337 S2: emit ``SECRET_MASKED`` once for a call whose output the producer seam masked or withheld.

    The payload holds labels (``github``, ``env:NAME``), never a value, a form or a position. It names no agent:
    ``invocation_id`` (ordinary) or ``operation_id`` (strict) is the correlation id of the call's ``TOOL_INVOKED``
    row, which carries the identity in that mode's own form, and a strict call's tool id is left out for the same
    reason. ``SECRET_MASKED`` is a routed DURABLE member, so the runtime's emit writes its events.db row.
    """

    def secret_masked_hook(ctx: dict[str, Any], result: "ToolResult") -> None:
        from probos.events import EventType

        invocation = _invocation(ctx)
        if invocation is None or not (invocation.secrets_masked or invocation.secret_masking_failed):
            return
        names = invocation.secrets_masked
        payload = {
            "seam": "producer",
            "tool_id": invocation.record_tool_id if invocation.operation_id is None else None,
            "invocation_id": invocation.invocation_id,
            "operation_id": invocation.operation_id,
            "attempt_id": invocation.attempt_id,
            "names": list(names[:SECRET_MASKED_MAX_NAMES]),
            "names_omitted": max(0, len(names) - SECRET_MASKED_MAX_NAMES),
            "failed": invocation.secret_masking_failed,
        }
        try:
            emit_fn(EventType.SECRET_MASKED, payload)
        except Exception:
            logger.warning(
                "AD-1337: SECRET_MASKED could not be emitted for tool=%s; the output stays masked",
                payload["tool_id"],
            )

    return secret_masked_hook


def wire_secret_masked_event(
    executor: ToolExecutor,
    *,
    emit_fn: Callable[[Any, dict[str, Any]], None] | None,
) -> bool:
    """AD-1337 S2: add the ``SECRET_MASKED`` post-hook when ``executor`` masks and events can be emitted.

    Inert (False, no hook) for an executor built without a masker, so a bare executor's hook count is unchanged.
    """
    if executor.secret_masker is None or emit_fn is None:
        return False
    executor.add_post_hook(make_secret_masked_hook(emit_fn))
    return True
```

### 7.3 `src/probos/events.py` (M1)

**X8.** SEARCH (`events.py:328`):
```
    SECRET_ROTATED = "secret_rotated"  # AD-456
```
REPLACE:
```
    SECRET_ROTATED = "secret_rotated"  # AD-456
    SECRET_MASKED = "secret_masked"  # AD-1337: tool output had a known credential value masked, or was withheld
```

### 7.4 `src/probos/event_persistence.py` (M1)

**X9.** SEARCH (`event_persistence.py:71`):
```
    "SECRET_ROTATED": _DURABLE,
```
REPLACE:
```
    "SECRET_ROTATED": _DURABLE,
    "SECRET_MASKED": _DURABLE,  # AD-1337: written by the router; the payload holds labels, never a value
```

### 7.5 `src/probos/cognitive/agentic_dispatch.py` (M1)

**X10.** SEARCH (`:89`): `from probos.tools.executor import ToolExecutor, classify_tool_error, wire_durable_tool_records`. REPLACE:
```
from probos.tools.executor import (
    ToolExecutor,
    classify_tool_error,
    wire_durable_tool_records,
    wire_secret_masked_event,
)
```

**X11.** SEARCH (`:969-972`, `_DispatchConfigurationMixin.__init__`):
```
    def __init__(
        self, *, registry: Any, effect_broker: Any = None
    ) -> None:
        super().__init__(registry=registry, effect_broker=effect_broker)
```
REPLACE:
```
    def __init__(
        self, *, registry: Any, effect_broker: Any = None, secret_masker: Any = None
    ) -> None:
        # AD-1337 S2: forwards the masker, so the dispatch executor masks on both of its paths.
        super().__init__(registry=registry, effect_broker=effect_broker, secret_masker=secret_masker)
```

**X12.** SEARCH (`:1531-1532`):
```
class DispatchToolExecutor(
    _DispatchGuardMixin,
```
REPLACE:
```
def _runtime_secret_masker(runtime: Any) -> Any:
    """AD-1337 S2: ``runtime.secret_masker`` when it is a real ``SecretMasker`` (startup/finalize.py builds it),
    else None: a runtime finalize never ran on (a test double) masks nothing, and a ``MagicMock`` attribute is not
    handed to the executor, which would refuse it."""
    from probos.security.secret_masking import SecretMasker

    masker = getattr(runtime, "secret_masker", None)
    return masker if isinstance(masker, SecretMasker) else None


class DispatchToolExecutor(
    _DispatchGuardMixin,
```

**X13.** SEARCH (`:3013-3016`):
```
        executor = DispatchToolExecutor(
            registry=registry,
            effect_broker=getattr(runtime, "effect_broker", None),
        )
```
REPLACE:
```
        executor = DispatchToolExecutor(
            registry=registry,
            effect_broker=getattr(runtime, "effect_broker", None),
            secret_masker=_runtime_secret_masker(runtime),
        )
```

**X14.** SEARCH (`:3070-3073`):
```
        recording_enabled = wire_durable_tool_records(
            executor, event_log=getattr(runtime, "event_log", None),
            work_item_id_provider=work_item_id_provider,
        )
```
REPLACE:
```
        recording_enabled = wire_durable_tool_records(
            executor, event_log=getattr(runtime, "event_log", None),
            work_item_id_provider=work_item_id_provider,
        )
        # AD-1337 S2: SECRET_MASKED for this executor's masked calls. Not lifecycle traffic: at most one event per
        # call, and only when something was masked or withheld.
        wire_secret_masked_event(executor, emit_fn=getattr(runtime, "emit_event", None))
```

### 7.6 `src/probos/startup/finalize.py` (M1)

**X15.** SEARCH (`:712-715`):
```
    return ids


async def _start_recording_reaper(*, runtime: Any, config: "SystemConfig") -> None:
```
REPLACE:
```
    return ids


def _wire_secret_masker(*, runtime: Any) -> Any:
    """AD-1337 S2 (#1560): build the runtime's secret masker and start priming the GitHub value.

    Sets ``runtime.secret_registry`` (always: AD-1337 S4 registers per-run values in it) and ``runtime.secret_masker``,
    and returns the masker for the runtime's ``ToolExecutor``; each dispatch executor reads it from the runtime.
    ``ProbOSRuntime.__init__`` builds ``runtime.credential_store`` unconditionally, so a production runtime always has
    a masker; a runtime without a real store (a test double) gets None and masks nothing.
    """
    from probos.credential_store import CredentialStore
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry

    runtime.secret_registry = SecretRegistry()
    runtime.secret_masker = None
    runtime.secret_masking_prime_task = None
    store = getattr(runtime, "credential_store", None)
    if not isinstance(store, CredentialStore):
        logger.warning("AD-1337: no CredentialStore on the runtime; tool output is not masked")
        return None
    runtime.secret_masker = SecretMasker(
        credential_store=store, registry=runtime.secret_registry, env_source=EnvSecretSource(),
    )
    runtime.secret_masking_prime_task = asyncio.create_task(
        _prime_secret_masking(store), name="secret_masking_prime",
    )
    return runtime.secret_masker


async def _prime_secret_masking(store: Any) -> None:
    """AD-1337 S2: resolve the GitHub credential once, in a worker thread, so a token only ``gh auth token`` knows is
    masked from the first tool call; ``get`` keeps it for the masker, which reads it on every pass.

    The read keeps ``get``'s department and tier gates. It writes no access row (``_log_access`` needs a running loop
    in its own thread), and the value goes to the masker only, as the masker's own store read does. A failure, or no
    ``gh``, only means a CLI-only token is masked after its first ``get``; startup never waits on this task.
    """
    try:
        value = await asyncio.to_thread(store.get, "github", requester="secret_masking")
    except Exception as exc:
        logger.warning("AD-1337: priming the github credential for masking failed (%s)", type(exc).__name__)
        return
    logger.info("AD-1337: github credential primed for masking (found=%s)", value is not None)


async def _start_recording_reaper(*, runtime: Any, config: "SystemConfig") -> None:
```

*Corrected by section 17 (2026-11-21):* the docstring above says a CLI-only token is masked "from the first tool call". With X15 alone that held only for a call made after the priming finished: review round 1 (F1) found the priming still pending when `start()` returned. RC11 marks the masker priming before the task starts and makes the worker end it, and RC9 holds every registry call until then, for at most 6 s.

**X16.** SEARCH (`:5828-5837`):
```
    # AD-423c: Wire tool registry into onboarding service
    if runtime.tool_registry:
        runtime.onboarding.set_tool_registry(runtime.tool_registry)

        # AD-448: Wrapped Tool Executor
        from probos.tools.executor import ToolExecutor, wire_tool_invocation_hooks
        tool_executor = ToolExecutor(
            registry=runtime.tool_registry,
            effect_broker=getattr(runtime, "effect_broker", None),
        )
```
REPLACE:
```
    # AD-1337 S2: the secret masker, after the credential store's path is set (AD-456 above), so its first read loads
    # the right store. Every tool executor masks with it: this one below, and each dispatch's from runtime.secret_masker.
    secret_masker = _wire_secret_masker(runtime=runtime)

    # AD-423c: Wire tool registry into onboarding service
    if runtime.tool_registry:
        runtime.onboarding.set_tool_registry(runtime.tool_registry)

        # AD-448: Wrapped Tool Executor
        from probos.tools.executor import ToolExecutor, wire_tool_invocation_hooks
        tool_executor = ToolExecutor(
            registry=runtime.tool_registry,
            effect_broker=getattr(runtime, "effect_broker", None),
            secret_masker=secret_masker,
        )
```

### 7.7 `tests/test_ad1195_durable_event_seam.py` (M1)

**F1.** SEARCH (`:327-332`):
```
    # and BOOT_CAMP_PHASE_ADVANCE (AD-638 phases 2 and 3), another: 396 -> 395.
    assert len(EventType) == 395
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 366)
    assert {m.value for m in _ROUTED} == ROUTED_VALUES
    assert sum(1 for p in DECLARATIONS.values() if p is Persistence.DURABLE) == 37
```
REPLACE:
```
    # and BOOT_CAMP_PHASE_ADVANCE (AD-638 phases 2 and 3), another: 396 -> 395.
    # AD-1337 S2 (#1560) added SECRET_MASKED, a routed DURABLE member: 395 -> 396, 29 -> 30, 37 -> 38.
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 30
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (30, 366)
    assert {m.value for m in _ROUTED} == ROUTED_VALUES
    assert sum(1 for p in DECLARATIONS.values() if p is Persistence.DURABLE) == 38
```

### 7.8 `tests/test_ad1195_event_persistence_contract.py` (M1)

**F2.** SEARCH (`:394`): `# DECL-4: the 29 routed values of the contract's DURABLE table (section 3.8), plus AD-1326's.` REPLACE: `# DECL-4: the 30 routed values of the contract's DURABLE table (section 3.8), plus AD-1326's and AD-1337's.`

**F3.** Same file. SEARCH (`:406-407`):
```
    "procedure_challenge_decided",
})
```
REPLACE:
```
    "procedure_challenge_decided",
    "secret_masked",
})
```

**F4.** SEARCH (`:447`):
```
    """DECL-1: 395 members = 41 declared + 354 grandfathered, disjoint.
```
REPLACE:
```
    """DECL-1: 396 members = 42 declared + 354 grandfathered, disjoint (AD-1337 S2 declared SECRET_MASKED).
```

**F5.** SEARCH (`:457`):
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (395, 41, 354)
```
REPLACE:
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 42, 354)
```

**F6.** Same file. SEARCH (`:508-510`):
```
    """DECL-4: 37 DURABLE (8 owner, 29 routed), 4 OPERATIONAL, 0 DIAGNOSTIC."""
    counts = Counter(ep.DECLARATIONS.values())
    assert counts == {Persistence.DURABLE: 37, Persistence.OPERATIONAL: 4}
```
REPLACE:
```
    """DECL-4: 38 DURABLE (8 owner, 30 routed), 4 OPERATIONAL, 0 DIAGNOSTIC."""
    counts = Counter(ep.DECLARATIONS.values())
    assert counts == {Persistence.DURABLE: 38, Persistence.OPERATIONAL: 4}
```

**F7.** Same file. SEARCH (`:514-515`):
```
    assert len(ROUTED_VALUES) == 29
    operational = {name for name, cls in ep.DECLARATIONS.items() if cls is Persistence.OPERATIONAL}
```
REPLACE:
```
    assert len(ROUTED_VALUES) == 30
    operational = {name for name, cls in ep.DECLARATIONS.items() if cls is Persistence.OPERATIONAL}
```

**F8.** SEARCH (`:592`):
```
    assert len(EventType) == 395  # AD-1270 (#1324) slice 4c: BOOT_CAMP_PHASE_ADVANCED and BOOT_CAMP_PHASE_ADVANCE deleted
```
REPLACE:
```
    assert len(EventType) == 396  # AD-1270 (#1324) slice 4c deleted two members; AD-1337 S2 (#1560) added SECRET_MASKED
```

### 7.9 `tests/test_ad1195_durable_producers.py` (M1)

**F9.** SEARCH (`:68-69`):
```
    "PROCEDURE_CHALLENGE_DECIDED": ("cognitive/procedure_challenger.py",),
}
```
REPLACE:
```
    "PROCEDURE_CHALLENGE_DECIDED": ("cognitive/procedure_challenger.py",),
    "SECRET_MASKED": ("tools/executor.py",),
}
```

**F10.** SEARCH (`:162`):
```
    assert len(_ROUTED) == 29
```
REPLACE:
```
    assert len(_ROUTED) == 30
```

**F11.** SEARCH (`:172`):
```
    assert len(durable) == 37
```
REPLACE:
```
    assert len(durable) == 38
```

### 7.10 `tests/test_ad1195_eventlog_pair_freeze.py` (M1)

**F12.** SEARCH (`:513`):
```
    assert len(OWNER_RECORDS) == 8 and len(ROUTED_VALUES) == 29
```
REPLACE:
```
    assert len(OWNER_RECORDS) == 8 and len(ROUTED_VALUES) == 30
```

### 7.11 `PROGRESS.md` (M2)

**TR1.** SEARCH (the whole line `:1`; it occurs once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1337 S2 (2026-11-21), #1560 -- the producer seam: every result a tool registry returns is masked before the timing, the post-hooks, the broker and the model see it.** `ToolExecutor(secret_masker=)` masks in `_invoke_once` right after the registry returns, so the direct, broker and `DispatchToolExecutor` paths (both modes) are covered; a failed pass, or a registry answer that is not a `ToolResult`, withholds the output, and under the broker the attempt ends `failed` and is never run again. `startup/finalize.py` builds `runtime.secret_registry` and `runtime.secret_masker`, passes the masker to the runtime's executor and to each dispatch's, and resolves the GitHub credential once in a worker thread. New `EventType.SECRET_MASKED`, a routed DURABLE member: labels only, never a value, at most one per call. Measured by `tests/test_ad1337_executor_seam.py` (21 cases): a real dispatch run shows the model `<secret:github>` and never the token; with no match the registry's own result object comes back; no form of the token reaches events.db; a census fails on any tool executor built without the runtime's masker. Not measured: the live cost of a pass. The render seam is AD-1337 S3, in the same PR. Contract `prompts/ad-1337-s2-producer-seam.md`.
```

### 7.12 `DECISIONS.md` (M2)

**TR2.** SEARCH: the whole line S1's TR2 added; it occurs once on `53696f68` and is ASCII:
```
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
```
REPLACE:
```markdown
- *Producer seam (S2).* `ToolExecutor._invoke_once` masks every result the registry returns, before `duration_ms`, the post-hooks (AD-1224's record, AD-1168's telemetry, dispatch's observers), the broker and the caller. Not in `invoke`: `DispatchToolExecutor.invoke` skips it on its non-protected path. The paths that never reach the registry (an ambiguous name, a pre-hook abort, a dispatch guard) return fixed text; a raised exception's text is the render seam's (S3). Inline, not in a thread: S1's oracle measured 0.026 ms for a short text and 22 ms for 1 MiB with 50 values.
- *Failure (S2).* A failed pass, or a registry answer that is not a `ToolResult`, withholds the output; every post-hook and the broker see `tool output withheld: secret masking failed`. Under the broker the attempt finishes `failed` and is terminal, so a retry with the same logical key is suppressed and the tool does not run twice.
- *Wiring (S2).* `finalize` builds `runtime.secret_registry` (always) and `runtime.secret_masker` (when the runtime's `CredentialStore` is real, which `ProbOSRuntime.__init__` makes unconditional) and passes the masker to the runtime's executor; each dispatch executor takes it from the runtime. A construction census fails on an executor built without `secret_masker=`. A test double without a real store gets no masker.
- *Priming (S2).* `get("github", requester="secret_masking")` runs once in a worker thread at startup, so a token only `gh auth token` knows is masked from the first call. It keeps `get`'s gates and writes no access row (`_log_access` needs a loop in its thread; the value goes to the masker only). A failure, or no `gh`, only delays masking of a CLI-only token to its first `get`.
- *Event (S2).* `SECRET_MASKED`, a routed DURABLE member, at most one per call and only when something was masked or withheld: labels (at most 16, the rest counted), `invocation_id` or `operation_id` to join the call's `TOOL_INVOKED` row, no agent id, and no tool id for a strict call. Not an owner row with `parent_event_id` (consult 4bb6d748): the router already records security-control events, and the correlation id joins the AD-1224 chain.
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
```

*Corrected by section 17 (2026-11-21):* TR2's *Priming (S2)* bullet ("masked from the first call") was false as built (review round 1, F1). RC18 replaces it with the gate, the warm-up and the bound, and adds the *Rotation fence (S2)* bullet.

### 7.13 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit any regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. No `roadmap.md` row (this is an AD).

## 8. Issue texts

None for S2. S1's section 8 covers the batch.

## 9. What this does NOT change

- S1's files (`security/secret_masking.py`, `credential_store.py`), `command_env.py`, `runtime.py`, `startup/shutdown.py`. Section 17 (the round-1 repair) changes both S1 files: RC5 to RC7 and RC12 to RC15.
- `AgenticLoop`, `reply_pipeline.py`, the offload path, the census of routes (all S3).
- The registry, the broker, the authority, the AD-1224 record schemas and `StrictEffectPrivacyProjector`, `ToolResult.metadata`, config and profiles, HXI, `architecture-baseline.yaml`.

## 10. Mutation rows (one campaign on the M1 candidate; restore between rows)

Rows S1m to S20m were run on the oracle against rev0's tests (section 16, O8); rev1 changes no source pair and no rev0 test, so those kills stand. For rev1, run only S21m and S22m, plus any earlier row whose source file's blob differs from section 16's record.

| Row | Mutant | Killed by |
|---|---|---|
| S1m | Move the seam after the post-hook loop | N1 (`observed is result`), N7 |
| S2m | Mask in `invoke`'s broker-less branch instead of `_invoke_once` | N3, N5 |
| S3m | `_mask_registry_result` returns `dataclasses.replace(masked.result)` | N2 |
| S4m | Drop `ctx.secret_masking_failed = masked.failed` | N6, N7 |
| S5m | Return a non-`ToolResult` as is | N8 |
| S6m | Hook emits when `secrets_masked` is empty | N2, N11 |
| S7m | Hook keeps `tool_id` for a strict call | N6, N12 |
| S8m | `names` uncapped | N11 |
| S9m | `wire_secret_masked_event` ignores a None masker | N13 |
| S10m | `wire_tool_invocation_hooks` drops its wiring call | N13, N14 |
| S11m | Dispatch drops its `wire_secret_masked_event` call | N5 |
| S12m | `"SECRET_MASKED": _OPERATIONAL` | N14, N15, F1 |
| S13m | finalize passes `secret_masker=None` | N19 |
| S14m | Dispatch passes `secret_masker=None` | N5, N19 |
| S15m | Mixin's `super().__init__` drops `secret_masker=` | N3, N19 |
| S16m | `_wire_secret_masker` drops its `isinstance` check | N17 |
| S17m | Priming calls `store.get` on the loop | N16 |
| S18m | `_prime_secret_masking` without `try` | N18 |
| S19m | `_checked_secret_masker` returns its argument unchecked | N10 |
| S20m | `_runtime_secret_masker` returns the raw attribute | N4 |
| S21m | `_mask_registry_result`: `ctx.secrets_masked = tuple(masked.names)` (no `sorted`) | N20 (the reverse-sorted `frozenset` makes it fail on every run) |
| S22m | `_prime_secret_masking`: `requester="agent-1"` in place of `requester="secret_masking"` | N21 |

## 11. Verified Against Codebase (2026-11-21, `5d8a5eb4`; S1 tree `ob11c`)

```
rg -n "class InvocationContext|def __init__|async def _invoke_once|def hook_count|def _invocation|def wire_tool_invocation_hooks|def wire_durable_tool_records" src/probos/tools/executor.py
  466, 502, 608, 957, 967, 1497, 1471
read executor.py:608-786 (seam :761-765), 788-909, 956-964 (class end), 1191-1261, 1471-1510
rg -n "^class _DispatchGuardMixin|^class _DispatchConfigurationMixin|^class DispatchToolExecutor|super\(\)\.__init__\(registry" src/probos/cognitive/agentic_dispatch.py
  804, 949, 1531, 972
read agentic_dispatch.py:89, 805-946, 969-972, 1539-1552, 3013-3016, 3028-3073
read finalize.py:10, 35, 674-715, 4186, 4690-4716, 5828-5864
rg -n "SECRET_ROTATED" src/probos/events.py src/probos/event_persistence.py   events.py:328; event_persistence.py:71
read event_persistence.py:47-108, 471-478; durable_events.py:59, 210-247, 399-410
read effect_broker.py:920-951; authority.py:2129-2134
read (ob11c) credential_store.py:73-113, 147-164, 290-347, 349-387, 400-415, 433-461; security/secret_masking.py:36-90, 182-365
read runtime.py:492, 734-742, 2034-2039
rg -n "hook_count" tests   test_ad448...:199; test_ad1224...:819, 822, 828, 1074, 2833
rg -n "== 395|== 29|== 37|\b41\b" tests/test_ad1195_*.py   seam:328-332; contract:394, 447, 457, 508-514, 592; producers:162, 172; pair_freeze:513
read tests/test_ad1224_durable_tool_start.py:883-971; tests/test_ad1316_governed_effect_broker.py:145-213, 512-547
read tests/test_ad1270a_startup_receipts.py:347-399; check_architecture_principles.py:160-188, 555-569; test_ad1324_srp_layout.py:29
git ls-files --eol (all eleven edited files)   i/lf w/crlf

rev1 (S1 head b1337b 3e8248b0; oracle copy ob11f):
grep "class MaskedResult|names:|def register|class SecretHandle|^DEFAULT_FLOOR|^_LABEL_RE" b1337b src/probos/security/secret_masking.py
  :84 class MaskedResult(NamedTuple); :89 names: frozenset[str]; :188-205 SecretHandle (no __del__); :216 register(self, name, value);
  :43 DEFAULT_FLOOR: int = 8; :70 _LABEL_RE [A-Za-z0-9_.:-]{1,64}
read b1337b secret_masking.py:342-354 (_values: store, then registry, then env; labels via secret_label)
read b1337b credential_store.py:273-280   get(self, name, *, requester="unknown", department=None, tier=None)
read b1337b credential_store.py:400-415   _log_access writes agent_type=requester
grep "requester=|tuple\(sorted\(masked\.names\)\)" ob11f finalize.py, executor.py, tests/test_ad1337_*.py
  finalize.py:751 to_thread(store.get, "github", requester="secret_masking"); executor.py:1017 tuple(sorted(masked.names));
  tests: secret_masking.py:459, 485, 493 only
grep "requires-python" pyproject.toml   >=3.12 (frozenset subclass __iter__ is honoured by tuple() and sorted())
```

## Absence Verified (2026-11-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other `ToolExecutor` construction, subclass or alias | `rg "\bToolExecutor\("`, `rg "ToolExecutor as \|= ToolExecutor\b\|= DispatchToolExecutor\b"`, `rg "class \w+\([^)]*ToolExecutor"` in `src/probos` | `finalize.py:5834`; `executor.py:490` (docstring); `agentic_dispatch.py:3013`; bases `:1531-1536` only | yes |
| No other `super().__init__(... registry=...)` | multiline `rg "super\(\)\.__init__\([^)]*\bregistry\s*="` | `agentic_dispatch.py:972` | yes |
| No S2 name exists yet | `rg "secret_masker\|SECRET_MASKED\|secret_masked\|secrets_masked\|secret_registry\|secret_masking_prime" src tests` (main) | none; on ob11c only the S1 test name `:509` | yes |
| Nothing serialises `InvocationContext` as a whole | `rg "asdict\(\|fields\(InvocationContext\|vars\(invocation\|invocation\.__dict__"` over executor, dispatch, effect files | none | yes |
| No test pins the executor signature, its fields, or the finalize executor's hooks | `rg "signature\((Dispatch)?ToolExecutor\|InvocationContext\.__dataclass_fields__\|_tool_executor\.hook_count\|_post_hooks\["` in tests | `test_ad1154:1966` (`_park_or_admit` only) | yes |
| No test replaces `DispatchToolExecutor` with a class lacking the new keyword | `rg "DispatchToolExecutor"` in tests (monkeypatch) | subclasses only (`test_ad1153:654`, `test_ad1224:1072`) | yes |
| No test spec-mocks `CredentialStore` | `rg "spec=CredentialStore\|create_autospec\(CredentialStore"` | none | yes |
| `ToolExecutor` is not baselined | `rg "executor" docs/development/architecture-baseline.yaml` | only `WorkItemAgenticExecutor`, `CrewTaskExecutor`, `CrewSessionFinalizer` | yes |
| No S2 source line names `masked_credential_values` (S1's N31) | after M1: `rg -l masked_credential_values src` | expected: two files | checked in section 12 |
| rev0's tests pin neither the requester of the priming read nor the order of more than one label | Grep `requester=` in `ob11f/tests/test_ad1337_*.py`; read rev0 7.1 (N1, N6 mask `github` only; N11 sets `secrets_masked` by hand) | three hits, all in S1's file (`:459`, `:485`, `:493`) | yes: O8's two survivors |
| The new names do not collide | Grep `_ReverseSorted\|labels_it_masked\|system_requester` in `ob11f` tests and src | none | yes |

## 12. Deterministic checks

- **Focused gate, `-n 0`:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on:
  - `tests/test_ad1337_executor_seam.py`, `tests/test_ad1337_secret_masking.py`
  - `tests/test_ad448_wrapped_tool_executor.py`, `tests/test_ad1224_durable_tool_start.py`, `tests/test_ad1316_governed_effect_broker.py`, `tests/test_ad1316_real_effect_routes.py`, `tests/test_ad1328_s2a_run_command_tool.py`
  - `tests/test_ad856_agentic_dispatch.py`, `tests/test_ad1153_browser_agentic_loop.py`, `tests/test_ad1189_deferred_tool_schemas.py`, `tests/test_ad1208_cost_bounded_turns.py`, `tests/test_ad1152_agentic_correlation.py`, `tests/test_ad1343_stop_seam_inventory.py`
  - `tests/test_ad1195_durable_event_seam.py`, `tests/test_ad1195_event_persistence_contract.py`, `tests/test_ad1195_durable_producers.py`, `tests/test_ad1195_eventlog_pair_freeze.py`, `tests/test_events.py`
  - `tests/test_finalize.py`, `tests/test_ad597_finalize.py`, `tests/test_ad1270a_startup_receipts.py`, `tests/test_new_crew_auto_welcome.py`, `tests/test_ad641d_deliberation.py`, `tests/test_bf235_stale_identity_cache.py`, `tests/test_runtime.py`
  - `tests/test_layer_boundaries.py`, `tests/test_ad1270b_architecture_fitness.py`, `tests/test_ad1324_srp_layout.py`, `tests/test_ad1184_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` exits 0.
- `rg -l masked_credential_values src` finds only `credential_store.py` and `security/secret_masking.py`.
- `git diff 53696f68 -- src/probos/security/ src/probos/credential_store.py src/probos/runtime.py src/probos/startup/shutdown.py src/probos/cognitive/swe_harness/ docs/development/architecture-baseline.yaml` is empty (rev1, at `089895c1`; section 17 changes `security/secret_masking.py` and `credential_store.py`, see 17.13).
- The new test file is ASCII only.
- Broad gate, once for batch 1 after S3: `scripts/run_test_gate.py --label ad-1337-1560 --receipt logs/gates/ad-1337-1560.receipt.json`.

## 13. Prior art and blind spots

- **Internal:**
  - consult `4bb6d748` Q1 (seams), Q5 (event), Q7 (slices);
  - AD-1224's record chain and `_owner_record_fields` (the correlation ids reused here);
  - AD-1195 (routed DURABLE members);
  - the finalize start-task convention (`finalize.py:5313`, `:1828`).
- **External:** no new search. This is ProbOS-specific plumbing of S1's researched design:
  - the GitHub Actions runner masks at its log producer, which is the same shape as the producer seam;
  - reference projects checked 2026-11-21: OpenHands was last reviewed 2026-10-15 with a 90-day interval, so it is not overdue, and no row needs an update.
- **Blind spots named:**
  - a producer-seam hit breaks the `self_query` presentation identity (fail closed; S3 tests it);
  - every real-runtime test boot may spawn `gh auth token` once (O5);
  - a priming task still in flight at shutdown is not cancelled (bounded by the 5 s timeout);
  - a secret containing an error-signature word could change `classify_tool_error`'s category of a masked error (cosmetic);
  - `ToolLockedDenied.result` text is left to S3;
  - the order of labels in a durable row would otherwise follow `frozenset` hash order (N20 pins it sorted);
  - a system read attributed to a crew-looking requester would misattribute the store's access row (N21).

## 14. Diff Reviewer: properties to verify

1. With a masker, every result `check_and_invoke` returns passes `_mask_registry_result` before `ctx.duration_ms`, any post-hook, the broker and the caller, on every path in P1. Without a masker, behaviour and `hook_count` are unchanged.
2. No value, form or position reaches a log line, an event payload, `InvocationContext` or an exception message. The payload has exactly the eight keys in D6, with labels only, in sorted order.
3. A failed pass, or a non-`ToolResult`, withholds the output; post-hooks and the broker see the withheld result; nothing raises out of the seam.
4. Every production executor construction passes the runtime's masker; the masker's type is enforced; a test double gets None, never a crash.
5. Priming runs off the loop, reads `github` as the system requester `secret_masking` with no department or tier, keeps `get`'s gates, never raises into or blocks startup, and is stored on the runtime. Since section 17: every registry call waits for it (at most 6 s), its worker loads the store file, and a `rotate` during its `get` is not undone.
6. The only event-type changes are `SECRET_MASKED` (DURABLE, routed) and the matching AD-1195 counts. AD-1224 schemas, the strict projector and `architecture-baseline.yaml` are unchanged. `ToolExecutor` stays at or under 500 lines and 15 methods.
7. The paths that never reach the registry are unchanged.

## 15. Acceptance

- [ ] Section 5's prediction holds: a collection error on `53696f68`, then 21 passed after M1; the focused gate is green (predicted after M2's regenerated ledger: 1622 passed, 3 skipped across section 12's 29 files).
- [ ] Mutation rows S1m to S22m are killed by the named cases (S1m to S20m by section 16's campaign of record; S21m and S22m on the rev1 candidate).
- [ ] The `rg` and diff checks of section 12 hold, and `check_architecture_principles.py --check` passes.
- [ ] TR1 and TR2 are applied; the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-21, scratch trees detached at `53696f68`, the committed S1 candidate with its repair, with this contract's pairs applied; rev0 was proved first on a tree at `3e8248b0`, then rev1 here)

Every pair of section 7 was applied to scratch worktrees by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed). Each test run went through `run_pytest_homeguard.ps1` and each probe through `run_probe_homeguard.ps1` (a redirected, empty home). A bare `pytest` was not used: it imports the main checkout's `src` and fails for the wrong reason. Results:

| O | Result |
|---|---|
| O1 | All 31 operations (the new test file, X1 to X16, F1 to F12, TR1, TR2) are found by `contract_tools.py list`; every SEARCH occurs exactly once on `53696f68`, and the tool's dry run on the build tree itself agrees. Blobs after the pairs: tests `352c61cc`, `executor.py` `da56450e`, `agentic_dispatch.py` `ba907a02`, `finalize.py` `15bfec78`, `events.py` `342015b2`, `event_persistence.py` `bd9c7b50`, PROGRESS `275e9f95`, DECISIONS `8f73345b` (the ledger pair is regenerated by M2). |
| O2 | The new test file alone on `53696f68`: **a collection error**, `ImportError: cannot import name 'SECRET_MASKED_MAX_NAMES' from 'probos.tools.executor'`, from the oracle's own tree (the right reason). |
| O3 | After the pairs: **21 passed** (rev0 gave 19; N20 and N21 are rev1's cases). |
| O4 | `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); `ToolExecutor` is 479 to 488 lines and 12 to 13 methods (an AST count). |
| O5 | **The cost of a real boot** (section 13's blind spot). `tests/test_runtime.py`, 29 tests that boot a real runtime, `-n 0`, four runs interleaved on a quiet host: base (S1 as repaired) 234 s and 216 s; candidate (S2 rev1 on it) 211 s and 218 s. The candidate is 4.9 percent faster on average, which is noise, so section 13's rescope rule (more than 10 percent) is not met and the prime task is not changed. An earlier set of runs (205, 469, 410, 489 s) overlapped a mutation campaign on the same host and is void: base ran 410 s against 205 s before it. |
| O6 | S1's file (93 cases), S2's new file (21), the four AD-1195 files and `tests/test_events.py`: **722 passed**. |
| O7 | **A real boot** (`ProbOSRuntime.start()` in a temp data directory whose `secrets.json` holds a GitHub token or is empty, on this tree; `gh` replaced by a recorder scoped to `probos.credential_store`, not the global module; probe `probe_b11s2_boot.py`). In both modes `runtime.secret_masker` is the runtime executor's masker; the post-hooks are `[audit, audit, secret_masked, failure]` (hook count 7); the prime task finished. With a stored token no `gh` call was made and that token is masked `<secret:github>`; with none, `gh auth token` ran once, in a worker thread, and the CLI token is masked `<secret:github>`; a value the masker does not know (the other token) stays as it is. One `secret_masked` row in events.db each time (payload keys `attempt_id, failed, invocation_id, names, names_omitted, operation_id, seam, tool_id`; the router leaves `agent_id` and `correlation_id` NULL, and the payload's `invocation_id` equals the correlation id of the call's `tool_started` and `tool_invoked` rows); neither token is in the events.db bytes or in any captured log line; no `secret_masking` task is pending after `stop()` (3.3 to 3.7 s). |
| O8 | **The mutation campaign** (`audit\rows_ad1337s2.py`: your S1m to S20m with S2m split in two, plus my extra rows X*, with X1 and X16 as rev1's S21m and S22m): **killed 38, differs 0, survived 0, invalid 0** (38 rows over the unmutated baseline of 21 passing cases, run on `53696f68` with this contract's pairs applied). Every row you named is killed by its named cases, and the two survivors of rev0's campaign are killed now: X1 (your S21m, `tuple(sorted(masked.names))` to `tuple(masked.names)`) by N20 and X16 (your S22m, `requester="agent-1"`) by N21. |
| O9 | **The 29 files of section 12**, four workers each, on the oracle with the pairs and the regenerated ledger pair (M2's step): **1631 passed, 3 skipped** under the default embeddings (1,192 s) and **1631 passed, 3 skipped** under `PROBOS_EMBEDDINGS=local` (1,177 s): the 1,620 of rev0's gate, S1's 9 new cases (the list holds `tests/test_ad1337_secret_masking.py`) and rev1's N20 and N21. The three skips are the two POSIX-only refusal cases and the BF-657 MagicMock test. Section 15 predicts 1,622, a number written before S1's repair added cases to a file this list includes; 1,631 is the figure of record. |

**What the orchestrator changed in the Architect's rev1:** nothing in the pairs, the tests or the rows; this section replaces the placeholder, and the `Answers to (a)-(i)` tail of the answer is not part of the contract.

**What these checks do not show.**
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`, and S3 (the render seam) is not in this slice.
- A `gh` that is installed and slow, or absent: the boot probe replaces `gh` with a recorder; the priming test N18 covers a missing `gh`, and the real `gh auth token` took 0.1 to 1.0 s here.
- The full suite: it runs once for the batch after S3.

---

## 17. Repair after review round 1 (2026-11-21)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev2

**Base.** The Builder starts from the batch head `25944b39`. Every SEARCH below occurs exactly once both there and on `089895c1`. S3 (`089895c1..25944b39`) does not touch `executor.py`, `finalize.py`, `credential_store.py` or `tests/test_ad1337_executor_seam.py`. In `secret_masking.py`, S3 only inserted `secret_masker_of` and `mask_route_result` at `:198-223`, and no anchor here is inside that region. `secret_masking.py` and `credential_store.py` are S1's files, byte-identical at `410bcc9a` and `089895c1`. Every edited file is `i/lf w/crlf`: match and write each with its own endings. ASCII only.

**Milestones** (one Builder delegation each; the Builder runs no test):

| M | Content | Commit subject |
|---|---|---|
| M3 | 17.3 (RC1 to RC4, tests first), then RC5 to RC15 | `Hold tool calls until the masking priming ends, and fence a rotation against a read in flight` |
| M4 | RC16 to RC18, then `gen_ad_ledger.py` and `--check` as in 7.13 | `Record the priming gate and the rotation fence` |

### 17.1 Findings and decisions

| Finding | Severity / reach | Decision | Pairs |
|---|---|---|---|
| F1: the priming is still pending when `start()` returns, so a call in the window is unmasked (`probe_b11s2_window.py`) | P1, ordinary | Gate every registry call on the masker's priming, bounded and failing open | RC1, RC2, RC4 to RC11 |
| F2: a `get` in flight republishes a value a `rotate` replaced (`credential_store.py:352-353`) | P2, API or probe only; a regression of S2's worker | A per-name generation fence under `_publish_lock` | RC4, RC12 to RC15 |
| F3: with `GH_TOKEN` set, the priming reads no file and the first pass loads it on the loop | P3, ordinary; a false claim | The worker runs one empty masking pass | RC4, RC11 |
| (seam) S3's routes past the executor are not gated | P3, narrow | A follow-up for S3's review; not changed here | none |

**Behaviour of the gate:**
- **Loop blocked.** The worker ends the priming by writing an attribute, without the loop, and waiting calls resume when the loop runs. If the loop was blocked past the bound and the priming had not ended, the next poll ends it with one WARNING.
- **Several waiting calls.** Each polls on its own, and all resume within one poll of the end: 25 ms since section 18 (RE1), plus up to one 15.625 ms clock tick on Windows. *Corrected by section 18 (2026-11-21):* this said 10 ms, a poll below the Windows clock resolution that checks once per loop pass while the loop has other work (review round 2, F1).
- **Shutdown.** Unchanged: the prime task is held and not cancelled, and `gh` is bounded at 5 s. A waiting call is cancelled with its own task.
- **Strict broker.** The wait happens inside a reserved attempt, well under the 120 s lease (`config.py:3871`).
- **Timing.** The wait counts in `duration_ms`.
- **No masker.** A bare executor, or a masker nobody primes, never waits.

### 17.2 Rejected designs

- **Join the priming at the end of `start()`.** Costs 0.02 to 0.9 s of boot (measured), up to 5 s with a hung `gh`, and silently reopens if a later AD calls tools earlier in boot.
- **Withhold every result while the priming is pending.** Turns the first second into withheld results.
- **Wait in `asyncio.to_thread(event.wait)`.** Holds one pool thread per waiting call.
- **An `asyncio.Event` on the masker.** Ties S1's thread-agnostic class to one loop.
- **Re-resolve after a fenced read.** Runs the CLI again (up to 5 s) for a value that was current when the call began.
- **Reuse `_store_lock` for the fence.** Invites nesting with `_load_store`, and S1's test replaces that lock.
- **Change `del self._cache[name]` to `pop`.** Not needed: the only worker-thread `get` is the priming, which runs at boot with no expired entry.

### 17.3 `tests/test_ad1337_executor_seam.py`

**RC1.** SEARCH:
```
def _raise_values(_store: CredentialStore) -> tuple[tuple[str, str], ...]:
    raise RuntimeError(TOKEN)
```
REPLACE:
```
def _raise_values(_store: CredentialStore) -> tuple[tuple[str, str], ...]:
    raise RuntimeError(TOKEN)


class _PrimingPolls:
    """Stands in for a masker's ``priming_pending``: records each answer and sets ``held`` once ``count`` answers
    have held a call, so a test knows the calls are waiting without sleeping."""

    def __init__(self, masker: SecretMasker, monkeypatch: pytest.MonkeyPatch, *, count: int) -> None:
        self.original = masker.priming_pending
        self.count = count
        self.answers: list[bool] = []
        self.held = asyncio.Event()
        monkeypatch.setattr(masker, "priming_pending", self)

    def __call__(self) -> bool:
        answer = self.original()
        self.answers.append(answer)
        if sum(self.answers) >= self.count:
            self.held.set()
        return answer


async def _held(polls: _PrimingPolls, calls: list[asyncio.Task[Any]]) -> bool:
    """Whether ``polls`` saw its count of held answers while every call in ``calls`` was still waiting. A gate that
    lets a call through makes that call finish first, so this returns False instead of hanging."""
    held = asyncio.ensure_future(polls.held.wait())
    done, _ = await asyncio.wait({held, *calls}, return_when=asyncio.FIRST_COMPLETED)
    if held not in done:
        held.cancel()
    return held in done and not any(call.done() for call in calls)
```

**RC2.** (N16, replaced: it no longer awaits the priming before calling the executors.) SEARCH:
```
async def test_finalize_builds_one_masker_on_the_runtime_and_primes_github_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append((list(argv), threading.get_ident()))
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
    runtime = SimpleNamespace(credential_store=_store(tmp_path))

    masker = finalize._wire_secret_masker(runtime=runtime)

    assert isinstance(masker, SecretMasker) and runtime.secret_masker is masker
    assert isinstance(runtime.secret_registry, SecretRegistry)
    task = runtime.secret_masking_prime_task
    assert isinstance(task, asyncio.Task) and task.get_name() == "secret_masking_prime"
    await task
    assert [argv for argv, _ in calls] == [["gh", "auth", "token"]]
    assert calls[0][1] != threading.get_ident()
    assert masker.mask_text(f"out {CLI_TOKEN}").text == f"out {PLACEHOLDER}"
    with runtime.secret_registry.register("vault:site", "vault-value-123"):
        assert masker.mask_text("vault-value-123").text == "<secret:vault:site>"
```
REPLACE:
```
async def test_finalize_primes_github_off_the_loop_and_every_executor_waits_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[tuple[list[str], int]] = []

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append((list(argv), threading.get_ident()))
        entered.set()
        assert release.wait(10.0)  # gh answers only after the tool calls below are waiting
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
    runtime = SimpleNamespace(credential_store=_store(tmp_path))
    tools = (_EchoTool("echo", f"cli={CLI_TOKEN}"), _EchoTool("echo", f"cli={CLI_TOKEN}"))
    try:
        masker = finalize._wire_secret_masker(runtime=runtime)

        assert isinstance(masker, SecretMasker) and runtime.secret_masker is masker
        assert isinstance(runtime.secret_registry, SecretRegistry)
        task = runtime.secret_masking_prime_task
        assert isinstance(task, asyncio.Task) and task.get_name() == "secret_masking_prime"
        assert masker.priming_pending() is True  # marked before the task can run
        assert await asyncio.to_thread(entered.wait, 10.0)  # the priming is inside gh, as on a real boot
        polls = _PrimingPolls(masker, monkeypatch, count=2)
        # Built as finalize builds the runtime's executor and as dispatch builds its own (N19 pins both sources).
        executors = (
            ToolExecutor(registry=_registry(tools[0]), secret_masker=runtime.secret_masker),
            DispatchToolExecutor(
                registry=_registry(tools[1]), secret_masker=agentic_dispatch._runtime_secret_masker(runtime),
            ),
        )
        window = [asyncio.create_task(executor.invoke("agent-1", "echo", {})) for executor in executors]
        assert await _held(polls, window) is True
        assert [tool.calls for tool in tools] == [0, 0]  # held before the registry, so a raising tool is held too
    finally:
        release.set()
    await task
    assert polls.original() is False  # the worker ended the priming
    results = await asyncio.gather(*window)
    assert [result.output for result in results] == [f"cli={PLACEHOLDER}"] * 2
    assert [tool.calls for tool in tools] == [1, 1]
    assert [argv for argv, _ in calls] == [["gh", "auth", "token"]]
    assert calls[0][1] != threading.get_ident()
    assert masker.mask_text(f"out {CLI_TOKEN}").text == f"out {PLACEHOLDER}"
    with runtime.secret_registry.register("vault:site", "vault-value-123"):
        assert masker.mask_text("vault-value-123").text == "<secret:vault:site>"
```

**RC3.** (N18: the new signature, and a failed priming releases the gate.) SEARCH:
```
    caplog.set_level(logging.INFO, logger="probos.startup.finalize")
    store = _store(tmp_path)
    await finalize._prime_secret_masking(store)
    assert "github credential primed for masking (found=False)" in caplog.text

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(TOKEN)

    monkeypatch.setattr(store, "get", _boom)
    await finalize._prime_secret_masking(store)
    assert "priming the github credential for masking failed (RuntimeError)" in caplog.text
    assert TOKEN not in caplog.text
```
REPLACE:
```
    caplog.set_level(logging.INFO, logger="probos.startup.finalize")
    store = _store(tmp_path)
    masker = SecretMasker(credential_store=store, registry=SecretRegistry(), env_source=EnvSecretSource({}))
    masker.begin_priming()
    await finalize._prime_secret_masking(store, masker)
    assert "github credential primed for masking (found=False)" in caplog.text
    assert masker.priming_pending() is False

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(TOKEN)

    monkeypatch.setattr(store, "get", _boom)
    masker.begin_priming()
    await finalize._prime_secret_masking(store, masker)
    assert "priming the github credential for masking failed (RuntimeError)" in caplog.text
    assert masker.priming_pending() is False  # a failed priming releases the waiting calls too
    assert TOKEN not in caplog.text
```

**RC4.** (N22 to N24, appended after N21.) SEARCH:
```
    # The requester is how the store attributes a read (_log_access writes agent_type=requester): a system read
    # must never look like a crew member's, and it carries no department or tier.
    assert reads == [(("github",), {"requester": "secret_masking"})]
```
REPLACE:
```
    # The requester is how the store attributes a read (_log_access writes agent_type=requester): a system read
    # must never look like a crew member's, and it carries no department or tier.
    assert reads == [(("github",), {"requester": "secret_masking"})]


# -- N22 to N24: the priming's bound, a read across a rotation, and where the store file first loads -------------


async def test_a_priming_that_never_ends_holds_a_call_only_until_its_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _masker(tmp_path)
    assert masker.priming_pending() is False  # nothing primes it, so no call waits (every bare executor, N10)
    for bad in (0, -1.0):
        with pytest.raises(ValueError):
            masker.begin_priming(bad)
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(secret_masking, "time", SimpleNamespace(monotonic=lambda: clock.now))
    masker.begin_priming(secret_masking.DEFAULT_PRIMING_TIMEOUT_S)
    assert masker.priming_pending() is True
    masker.end_priming()
    masker.end_priming()  # a second end is harmless
    assert masker.priming_pending() is False

    masker.begin_priming(secret_masking.DEFAULT_PRIMING_TIMEOUT_S)  # and nothing ever ends it
    polls = _PrimingPolls(masker, monkeypatch, count=2)
    tool = _EchoTool("echo", f"token={TOKEN}")
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    call = asyncio.create_task(executor.invoke("agent-1", "echo", {}))
    try:
        assert await _held(polls, [call]) is True  # two answers from one call: the gate keeps checking
        assert tool.calls == 0
    finally:
        clock.now += secret_masking.DEFAULT_PRIMING_TIMEOUT_S
    result = await asyncio.wait_for(call, timeout=10.0)
    assert result.output == f"token={PLACEHOLDER}" and tool.calls == 1  # it runs, masked with what is known
    assert polls.original() is False
    assert caplog.text.count("secret priming did not finish") == 1


def test_a_get_in_flight_cannot_undo_a_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        entered.set()
        assert release.wait(10.0)
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
    store = _store(tmp_path)
    got: list[str | None] = []
    reader = threading.Thread(target=lambda: got.append(store.get("github", requester="secret_masking")))
    reader.start()
    try:
        assert entered.wait(10.0)  # the get is in the CLI step: it found no stored value
        assert store.rotate("github", TOKEN) is True
    finally:
        release.set()
        reader.join(10.0)
    assert not reader.is_alive() and got == [CLI_TOKEN]  # the value that was current when the get began
    assert store.get("github", requester="test") == TOKEN  # the rotation stands
    masker = SecretMasker(credential_store=store, registry=SecretRegistry(), env_source=EnvSecretSource({}))
    assert masker.mask_text(f"{CLI_TOKEN} {TOKEN}").text == f"{CLI_TOKEN} {PLACEHOLDER}"


async def test_priming_loads_the_store_file_off_the_loop_whichever_step_resolves_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", CLI_TOKEN)  # get answers at the environment step, before the store file
    reads: list[int] = []
    original = probos.credential_store._read_store_file

    def _recording_read(path: Path) -> dict[str, str]:
        reads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr("probos.credential_store._read_store_file", _recording_read)
    runtime = SimpleNamespace(credential_store=_store(tmp_path, {"vault": VAULT_A}))

    masker = finalize._wire_secret_masker(runtime=runtime)
    await runtime.secret_masking_prime_task

    assert len(reads) == 1 and reads[0] != threading.get_ident()  # loaded once, in the priming's worker thread
    assert masker.mask_text(f"{VAULT_A} {CLI_TOKEN}").text == f"<secret:vault> {PLACEHOLDER}"
    assert len(reads) == 1  # the first pass on the loop read no file
```

### 17.4 `src/probos/security/secret_masking.py`

**RC5.** SEARCH:
```
import re
import threading
from collections.abc import Callable, Mapping
```
REPLACE:
```
import re
import threading
import time
from collections.abc import Callable, Mapping
```

**RC6.** SEARCH:
```
#: What the caller gets instead of the text or the output when a pass fails.
MASKING_FAILED_TEXT: str = "tool output withheld: secret masking failed"
```
REPLACE:
```
#: Not measured: how long a tool call waits for the startup priming (AD-1337 S2) before it runs without it. The
#: priming's CLI step has a 5 s timeout (``CredentialStore._resolve``); the extra second covers the store file's load.
DEFAULT_PRIMING_TIMEOUT_S: float = 6.0

#: What the caller gets instead of the text or the output when a pass fails.
MASKING_FAILED_TEXT: str = "tool output withheld: secret masking failed"
```

**RC7.** SEARCH:
```
        self._table: tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]] | None = None

    def mask_text(self, text: str) -> MaskOutcome:
```
REPLACE:
```
        self._table: tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]] | None = None
        # AD-1337 S2: while the startup priming runs, the monotonic time it stops being waited for; None otherwise.
        # One attribute, read and replaced whole, so the worker thread and the loop need no lock.
        self._priming_deadline: float | None = None

    def begin_priming(self, timeout_s: float = DEFAULT_PRIMING_TIMEOUT_S) -> None:
        """AD-1337 S2: a value is being primed. ``priming_pending`` is True until ``end_priming``, or for at most
        ``timeout_s`` seconds. ``ValueError`` unless ``timeout_s`` is positive."""
        if not timeout_s > 0:
            raise ValueError("timeout_s must be positive")
        self._priming_deadline = time.monotonic() + timeout_s

    def end_priming(self) -> None:
        """AD-1337 S2: the priming has finished, or failed. Safe from any thread and more than once."""
        self._priming_deadline = None

    def priming_pending(self) -> bool:
        """AD-1337 S2: whether a tool call should wait for the priming. Past its bound this ends the priming, with
        one WARNING: the call then runs, masked with every value the masker knows without it."""
        deadline = self._priming_deadline
        if deadline is None:
            return False
        if time.monotonic() < deadline:
            return True
        self._priming_deadline = None
        logger.warning("AD-1337: secret priming did not finish in time; tool calls no longer wait for it")
        return False

    def mask_text(self, text: str) -> MaskOutcome:
```

### 17.5 `src/probos/tools/executor.py`

**RC8.** SEARCH:
```
from __future__ import annotations

import hashlib
```
REPLACE:
```
from __future__ import annotations

import asyncio
import hashlib
```

**RC9.** SEARCH:
```
                return aborted

        try:
            if effect_permit is None:
```
REPLACE:
```
                return aborted

        await _await_secret_priming(self._secret_masker)  # AD-1337 S2: the registry runs after the startup priming
        try:
            if effect_permit is None:
```

**RC10.** SEARCH:
```
    masked = masker.mask_result(result)
    ctx.secrets_masked = tuple(sorted(masked.names))
    ctx.secret_masking_failed = masked.failed
    return masked.result
```
REPLACE:
```
    masked = masker.mask_result(result)
    ctx.secrets_masked = tuple(sorted(masked.names))
    ctx.secret_masking_failed = masked.failed
    return masked.result


#: AD-1337 S2: how often a registry call waiting for the masker's startup priming checks it again.
_SECRET_PRIMING_POLL_S = 0.01


async def _await_secret_priming(masker: "SecretMasker | None") -> None:
    """AD-1337 S2: hold a registry call while the masker's startup priming runs.

    A token only ``gh auth token`` knows reaches the masker only when the priming's ``get`` returns, so a call made
    in that window is held before the registry runs, which covers a result and a raised exception's text alike. It
    polls, so it holds no worker thread and works on any loop. The masker bounds the wait
    (``DEFAULT_PRIMING_TIMEOUT_S``) and then lets every call through; without a masker, or with one nobody primes,
    nothing waits.
    """
    while masker is not None and masker.priming_pending():
        await asyncio.sleep(_SECRET_PRIMING_POLL_S)
```

*Corrected by section 18 (2026-11-21):* RC10's `_SECRET_PRIMING_POLL_S = 0.01` is below the Windows loop's 15.625 ms clock resolution, so a waiting call checked the priming once per loop pass whenever the loop had other ready work (review round 2, F1). RE1 raises it to 0.025 and RE2 names it in the docstring. RC1's `_held` used `asyncio.ensure_future`; RE4 replaces it with `asyncio.create_task` (F2).

### 17.6 `src/probos/startup/finalize.py`

**RC11.** No line here may name S1's store-values function (S1's N31 is a text scan). SEARCH:
```
    runtime.secret_masker = SecretMasker(
        credential_store=store, registry=runtime.secret_registry, env_source=EnvSecretSource(),
    )
    runtime.secret_masking_prime_task = asyncio.create_task(
        _prime_secret_masking(store), name="secret_masking_prime",
    )
    return runtime.secret_masker


async def _prime_secret_masking(store: Any) -> None:
    """AD-1337 S2: resolve the GitHub credential once, in a worker thread, so a token only ``gh auth token`` knows is
    masked from the first tool call; ``get`` keeps it for the masker, which reads it on every pass.

    The read keeps ``get``'s department and tier gates. It writes no access row (``_log_access`` needs a running loop
    in its own thread), and the value goes to the masker only, as the masker's own store read does. A failure, or no
    ``gh``, only means a CLI-only token is masked after its first ``get``; startup never waits on this task.
    """
    try:
        value = await asyncio.to_thread(store.get, "github", requester="secret_masking")
    except Exception as exc:
        logger.warning("AD-1337: priming the github credential for masking failed (%s)", type(exc).__name__)
        return
    logger.info("AD-1337: github credential primed for masking (found=%s)", value is not None)
```
REPLACE:
```
    runtime.secret_masker = SecretMasker(
        credential_store=store, registry=runtime.secret_registry, env_source=EnvSecretSource(),
    )
    # AD-1337 S2: every registry call waits for the priming (the masker bounds the wait), so the first one is masked
    # with what the priming adds. Marked before the task exists, so no call can run between the two.
    runtime.secret_masker.begin_priming()
    runtime.secret_masking_prime_task = asyncio.create_task(
        _prime_secret_masking(store, runtime.secret_masker), name="secret_masking_prime",
    )
    return runtime.secret_masker


def _prime_secret_masking_worker(store: Any, masker: Any) -> str | None:
    """AD-1337 S2: the priming's worker-thread body.

    ``get`` keeps the GitHub value for the masker, whichever step resolves it. The empty ``mask_text`` pass then
    loads the store file and builds the masker's pattern table here, so neither happens on the loop at the first
    tool call, even when the environment answered ``get`` before the store file was read. ``end_priming`` runs last
    whatever happened, so a failure releases the tool calls waiting on the priming.
    """
    try:
        return store.get("github", requester="secret_masking")
    finally:
        masker.mask_text("")  # never raises for a str: a failed pass logs its type only (AD-1337 D7)
        masker.end_priming()


async def _prime_secret_masking(store: Any, masker: Any) -> None:
    """AD-1337 S2: resolve the GitHub credential once, in a worker thread, so a token only ``gh auth token`` knows is
    masked from the first tool call: ``_wire_secret_masker`` marks the masker priming, and every registry call waits
    until the worker ends it (``ToolExecutor._invoke_once``), for at most the masker's ``DEFAULT_PRIMING_TIMEOUT_S``.

    The read keeps ``get``'s department and tier gates. It writes no access row (``_log_access`` needs a running loop
    in its own thread), and the value goes to the masker only, as the masker's own store read does. A failure, or no
    ``gh``, only means a CLI-only token is masked after its first ``get``; startup never waits on this task.
    """
    try:
        value = await asyncio.to_thread(_prime_secret_masking_worker, store, masker)
    except Exception as exc:
        logger.warning("AD-1337: priming the github credential for masking failed (%s)", type(exc).__name__)
        return
    logger.info("AD-1337: github credential primed for masking (found=%s)", value is not None)
```

### 17.7 `src/probos/credential_store.py`

No new method: the class stays at 15.

**RC12.** SEARCH:
```
        # AD-1337: the first load can run in a worker thread (S2's priming get) while rotate() runs on the loop.
        self._store_lock = threading.Lock()
```
REPLACE:
```
        # AD-1337: the first load can run in a worker thread (S2's priming get) while rotate() runs on the loop.
        self._store_lock = threading.Lock()
        # AD-1337: rotate() bumps a name's generation, and a get() that began before it (S2's priming get runs in a
        # worker thread) publishes to _cache and _last_resolved only if the generation is unchanged. A lock of its
        # own: nothing holds it while taking _store_lock, so the two never nest.
        self._generations: dict[str, int] = {}
        self._publish_lock = threading.Lock()
```

**RC13.** SEARCH:
```
        self._store[name] = value
        # Invalidate cache so next get(...) resolves fresh.
        self._cache.pop(name, None)
        self._last_resolved.pop(name, None)  # AD-1337: the old value is no longer masked
```
REPLACE:
```
        with self._publish_lock:  # AD-1337: one step, so a get() in flight cannot republish the old value after it
            self._store[name] = value
            self._generations[name] = self._generations.get(name, 0) + 1
            # Invalidate cache so next get(...) resolves fresh.
            self._cache.pop(name, None)
            self._last_resolved.pop(name, None)  # AD-1337: the old value is no longer masked
```

**RC14.** SEARCH:
```
        # Resolution chain
        value = self._resolve(spec)
```
REPLACE:
```
        # Resolution chain. AD-1337: the name's generation is read first, so a rotate() during _resolve is seen
        # below and the value it replaced is not published.
        with self._publish_lock:
            generation = self._generations.get(name, 0)
        value = self._resolve(spec)
```

**RC15.** SEARCH:
```
        if value:
            self._cache[name] = (value, time.monotonic() + self._cache_ttl)
            self._last_resolved[name] = value  # AD-1337: kept past the TTL for the secret masker
```
REPLACE:
```
        if value:
            with self._publish_lock:
                # AD-1337: a rotate() since the generation was read replaced this value. It is still returned (it
                # was current when this call began) but neither cached nor kept for the secret masker.
                if self._generations.get(name, 0) == generation:
                    self._cache[name] = (value, time.monotonic() + self._cache_ttl)
                    self._last_resolved[name] = value  # AD-1337: kept past the TTL for the secret masker
```

### 17.8 `PROGRESS.md`

**RC16.** SEARCH:
```
resolves the GitHub credential once in a worker thread.
```
REPLACE:
```
resolves the GitHub credential once in a worker thread, which also loads the store file; until that priming ends (at most 6 s) every registry call waits for it, so a token only `gh auth token` knows is masked from the first call, and a `rotate` while a `get` is in flight is not undone when that `get` returns.
```

**RC17.** SEARCH:
```
`tests/test_ad1337_executor_seam.py` (21 cases): a real dispatch run
```
REPLACE:
```
`tests/test_ad1337_executor_seam.py` (24 cases): a call made while the priming is inside `gh` waits and is masked, through the runtime's executor and a dispatch executor; a priming that never ends holds a call only until its bound; a `get` in flight across a `rotate` returns its value and leaves the new one current; the store file loads in the priming's thread even when the environment answers `get`; a real dispatch run
```

### 17.9 `DECISIONS.md`

**RC18.** SEARCH (the whole line; it occurs once on `089895c1` and on `25944b39`):
```
- *Priming (S2).* `get("github", requester="secret_masking")` runs once in a worker thread at startup, so a token only `gh auth token` knows is masked from the first call. It keeps `get`'s gates and writes no access row (`_log_access` needs a loop in its thread; the value goes to the masker only). A failure, or no `gh`, only delays masking of a CLI-only token to its first `get`.
```
REPLACE:
```
- *Priming (S2).* `get("github", requester="secret_masking")` runs once in a worker thread at startup, and the same thread then runs one empty masking pass, so the store file loads and the masker's table is built there whichever step resolves the value. Until that thread ends, the masker reports the priming pending and every registry call waits before the registry runs (`ToolExecutor._invoke_once`, a 10 ms poll that holds no thread), for at most `DEFAULT_PRIMING_TIMEOUT_S` (6 s: the CLI's 5 s timeout plus one; not measured); then it runs and one WARNING says so. So a token only `gh auth token` knows is masked from the first call, and startup does not wait: joining the priming at the end of `start()` was rejected, because it costs boot up to the CLI's timeout and relies on nothing calling a tool earlier (review round 1 found the window open at `start()`'s return). It keeps `get`'s gates and writes no access row (`_log_access` needs a loop in its thread; the value goes to the masker only). A failure, or no `gh`, ends the wait at once and only delays masking of a CLI-only token to its first `get`.
- *Rotation fence (S2).* `rotate` replaces the stored value, bumps a per-name generation and drops the cached and last-resolved values in one locked step; a `get` that began before it (the priming runs in a worker thread) returns the value it resolved, but caches it and keeps it for the masker only if the generation is unchanged. Without it, a rotation acknowledged while the priming was in `gh` was undone by the next `get`.
```

### 17.10 Tests and predicted counts

| N | Change | Property |
|---|---|---|
| N16 | Replaced (RC2) | Wiring, then priming held inside `gh`, then a runtime executor and a dispatch executor both wait before the registry, then the priming ends, then both results are masked. The CLI runs on a worker thread. It does not await the priming before the calls. |
| N18 | Extended (RC3) | New signature. A successful priming and a failed one both end the priming. |
| N22 | New | A masker nobody primes never holds a call. `begin_priming` rejects 0 and -1. A priming that never ends holds a call through at least two polls, then lets it through at the bound, masked, with exactly one WARNING. |
| N23 | New | A `get` in flight across a `rotate` returns its own value. The next `get` returns the rotated one, and the masker holds only the current value. |
| N24 | New | With `GH_TOKEN` set, the store file loads once, on the priming's worker. The first pass on the loop reads no file. |

- **Test pairs only (RC1 to RC4) on `089895c1`: 19 passed, 5 failed.**
  - N16: `AttributeError` (`priming_pending`).
  - N18: `AttributeError` (`begin_priming`: the test starts the priming first).
  - N22: `AttributeError`.
  - N23: `CLI_TOKEN != TOKEN` on the second `get`.
  - N24: `reads == []`.
- **All pairs: 24 passed** (24 items, no parametrize).
- S1's file and S3's file (16 cases, 18 items): unchanged counts, all pass.

### 17.11 Mutation rows

Run on the M3 candidate, restoring between rows. Rerun section 10's rows whose file blob changed: S1m to S10m, S13m, S16m to S19m, S21m and S22m (`executor.py`, `finalize.py`). The dispatch and event rows (S11m, S12m, S14m, S15m, S20m) stand.

| Row | Mutant (one line) | Killed by |
|---|---|---|
| R1m | Delete the gate line in `_invoke_once` (RC9) | N16 (`_held` is False), N22 |
| R2m | Move the gate line to just before the seam (after the registry `try`) | N16 (`tool.calls == [0, 0]` fails) |
| R3m | `_await_secret_priming`: `while` to `if` | N22 (only one poll, so the call finishes first) |
| R4m | `priming_pending`: delete `self._priming_deadline = None` in the expiry branch | N22 (WARNING count 2) |
| R5m | `priming_pending`: `if time.monotonic() < deadline:` to `if True:` | N22 (`wait_for` times out) |
| R6m | Worker: delete `masker.end_priming()` | N16 (`polls.original()` is True), N18 |
| R7m | `_wire_secret_masker`: delete `runtime.secret_masker.begin_priming()` | N16 (`priming_pending()` is False at once) |
| R8m | Worker: delete `masker.mask_text("")` (the warm-up) | N24 |
| R9m | Publication: `== generation` to `True` (the fence) | N23 |
| R10m | `rotate`: delete the generation bump | N23 |
| R11m | Publication: `==` to `!=` | N16 (CLI token unmasked); S1's CLI case (`tests/test_ad1337_secret_masking.py:459-465`); `tests/test_credential_store.py::test_cache_ttl` |
| R12m | `begin_priming`: `if not timeout_s > 0:` to `if timeout_s < 0:` | N22 |
| S17m (rerun) | The worker body called on the loop instead of in `to_thread` | N16 (the loop blocks in `gh` for 10 s, then the calls run unmasked) |

The lock's atomicity (`with self._publish_lock:` on both sides) is checked by reading, not by a mutant: the interleaving between the check and the writes cannot be reached without instrumenting the lock.

### 17.12 What this does NOT change

- S3's files: `render_masking.py`, `agentic_loop.py`, `reply_pipeline.py` (its tier-1 browser route is not gated; that is the follow-up for S3's review), `native_builder.py`, `agentic_dispatch.py`.
- `events.py`, `event_persistence.py`, the `SECRET_MASKED` payload, AD-1224 schemas, config, `architecture-baseline.yaml`, `runtime.py`, `startup/shutdown.py`.
- What `CredentialStore.get` and `rotate` return; `_load_store`, `_store_lock`, `_resolve`, and S1's store-values function.
- `_calls_building_a_tool_executor`, `SECRET_MASKED_MAX_NAMES`, `tool_record_identity` (S3 imports all three).

### 17.13 Deterministic checks

- **Focused gate, `-n 0`:**
  - The S2, S1 and S3 test files: `test_ad1337_executor_seam.py`, `test_ad1337_secret_masking.py`, `test_ad1337_render_seam.py`.
  - The credential tests: `test_credential_store.py`, `test_ad456_security_infrastructure.py`, `test_ad456c_per_tier_credentials.py`.
  - The executor and broker tests: `test_ad448_wrapped_tool_executor.py`, `test_ad1224_durable_tool_start.py`, `test_ad1316_governed_effect_broker.py`, `test_ad856_agentic_dispatch.py`.
  - Boot and finalize: `test_finalize.py`, `test_runtime.py`.
  - The censuses: `test_bf892_spawn_env_guard.py`, `test_ad1346_admission_effect_census.py`, `test_ad1346_admission_file_write_census.py`.
  - Architecture: `test_ad1324_srp_layout.py`, `test_ad1270b_architecture_fitness.py`, `test_layer_boundaries.py`, `test_ad1184_ad_ledger.py`.
- `check_architecture_principles.py --check` exits 0. Counts: `ToolExecutor` 489 lines and 13 methods; `CredentialStore` 15 methods; `SecretMasker` 9 methods.
- `rg -l masked_credential_values src` finds exactly `credential_store.py` and `security/secret_masking.py`.
- `git diff 25944b39 --stat` lists only the seven files of 17.3 to 17.9, plus the ledger pair if it is regenerated.

### 17.14 Verified Against Codebase (2026-11-21, `25944b39`)

```
git diff --stat 089895c1 25944b39   no executor.py, finalize.py, credential_store.py, test_ad1337_executor_seam.py
git diff 089895c1 25944b39 -- src/probos/security/secret_masking.py   +28 at :198-223 only (secret_masker_of, mask_route_result)
git diff --stat 410bcc9a 089895c1   DECISIONS, PROGRESS, ledger pair only
grep "^import" executor.py   :14-22 hashlib..uuid (no asyncio); "if effect_permit is None:" :726 only; "return aborted" :723 only
read executor.py:615-806 (registry try :725-768, seam :770-771), :965-1019 (_checked_secret_masker :986, _mask_registry_result :997)
read finalize.py:715-755 (_wire_secret_masker, _prime_secret_masking; to_thread :751)
read credential_store.py:74-108 (_store_lock :97), :152-177, :179-225 (rotate), :281-355 (get; publish :351-353), :357-395 (timeout=5 :388), :441-484
grep "def " credential_store.py   15 methods in CredentialStore (:74 to :429)
read secret_masking.py:26-50, :297-446 (no time import; SecretMasker 6 methods)
read tests/test_ad1337_executor_seam.py:1-628 (N16 :453-478, N18 :491-505, N21 :609-627, _no_cli :71-80)
read tests/test_ad1337_secret_masking.py:615-677 (_ReportingLock replaces _store_lock), :517-522 (N31 text scan)
grep tests/test_ad1337_render_seam.py   :39 imports ToolExecutor, tool_record_identity; :58 imports _calls_building_a_tool_executor
grep config.py   :3871 effect_lease_seconds default 120
git ls-files --eol   all seven files i/lf w/crlf
```

**Absence verified (2026-11-21):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No production `CredentialStore.rotate` caller | `rg "\.rotate\(" src` | `routers/identity.py:229` (`binding.rotate()`, an identity binding) | yes |
| Nothing outside S2's file calls the priming or the wiring | `rg "_prime_secret_masking\|_wire_secret_masker\|secret_masking_prime_task" tests` (and `tests/fixtures`) | `test_ad1337_executor_seam.py` only; fixtures none | yes |
| No test pins `_cache` or `_last_resolved` beyond `clear()` | `rg "_last_resolved\|\._cache" tests` | `test_credential_store.py:45, 85, 131` (`clear()`) | yes |
| No census in fixtures counts `sleep` or `to_thread` in executor or finalize | `rg "sleep\|to_thread" tests/fixtures`; `rg "_prime_secret_masking\|secret_masking" tests/fixtures` | test-local bridges only; none | yes |
| No architecture check on polling | `rg "sleep\|polling\|to_thread" scripts/check_architecture_principles.py` | none | yes |
| No `check_and_invoke` outside `_invoke_once` | `rg check_and_invoke executor.py` | `:727`, `:731` (and docstrings) | yes |

### 17.15 Properties for the round-2 delta reviewer

Review only the repair: `git diff 25944b39..HEAD`, or `089895c1..HEAD` limited to the seven files. Execute, do not only read.

1. **The gate.** With a masker whose priming is pending, `check_and_invoke` is not called on any path until `end_priming` or the bound: direct, broker, and dispatch in both modes. A bare executor, or a masker nobody primes, never waits. A waiting call holds no pool thread, and cancelling it propagates.
2. **The bound.** Expiry lets calls through with exactly one WARNING that holds no value, and the expiry is latched.
3. **The priming.** `begin_priming` runs before `create_task`. The worker's `finally` runs the warm-up, then `end_priming`. A failed `get` releases the gate. Startup does not wait. The requester is still `secret_masking`. finalize.py does not name S1's store-values function.
4. **The warm-up.** The store file loads on the worker whether `get` resolved from the environment or the CLI. The first loop pass reads no file, except on S1's failed-load path, by design.
5. **The fence.** The store write, the bump and both invalidations happen in one `_publish_lock` step. `get` reads the generation under the lock before `_resolve` and publishes only if it is unchanged. `_publish_lock` and `_store_lock` never nest. What `get` and `rotate` return is unchanged. The S1, AD-456 and AD-456c tests pass.
6. **Sizes and contracts.** The section 17.13 counts hold. The only public additions are S1's three masker methods and one constant.
7. **First-hand probes on the candidate:**
   - `probe_b11s2_window.py`: call A returns `<secret:github>`.
   - `probe_b11s2_rotation.py`: the next `get` returns NEW.
   - `probe_b11s2_f3.py` CASE: the priming reads the file on a worker, and the first pass reads nothing.

### 17.16 Acceptance

- [ ] 17.10's predictions hold: 19 passed and 5 failed with the test pairs only, then 24 passed with all pairs. The focused gate in 17.13 is green.
- [ ] R1m to R12m and the reruns listed in 17.11 are killed by the named cases.
- [ ] RC16 to RC18 are applied, and the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### 17.17 The orchestrator's first-hand checks

The 18 operations of this section (RC1 to RC18) were applied to a scratch worktree detached at `25944b39` (the committed S2 head) by `audit\contract_tools.py apply --prefix 17.` (ASCII only), and every check below was run before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (an empty redirected home; BF-919) and each probe through `run_probe_homeguard.ps1`; a bare `pytest` was not used: it imports `D:\ProbOS\src` and fails for the wrong reason.

| R | Result |
|---|---|
| R1 | All 18 operations are found by `contract_tools.py list --prefix 17.`; every SEARCH occurs exactly once on `25944b39` (the code, the test and the tracker pairs alike). The seven files change by +248 -23 lines: `secret_masking.py` 31 and 0, `executor.py` 19 and 0, `finalize.py` 23 and 4, `credential_store.py` 21 and 7, the test file 151 and 10, `PROGRESS.md` one line and `DECISIONS.md` two lines added with one each replaced in place. Blobs after all 18 operations: `executor.py` `68096b19`, `finalize.py` `a8723305`, `credential_store.py` `e6665a0d`, `secret_masking.py` `1e411bb9`, the test file `152843e6`, `PROGRESS.md` `f3bf2427`, `DECISIONS.md` `be163d29`. No added line is non-ASCII. |
| R2 | **The tests alone** (RC1 to RC4 applied, the code pairs not): **5 failed, 19 passed** in 17.5 s, exactly the prediction of 17.10, each for its stated reason: N16 and N22 fail on `AttributeError: 'SecretMasker' object has no attribute 'priming_pending'`; N18 fails on `AttributeError ... 'begin_priming'` (the test starts the priming first; 17.10 said `TypeError` and is corrected above); N23 fails on its second `get`: the superseded value comes back where the rotated one is expected; N24 fails on `assert 0 == 1`, the priming's worker read no file. |
| R3 | After all 18 operations the test file alone: **24 passed** (21 + 3 new, N16 and N18 replaced) in 9.9 s. S1's file (97 cases) and S3's file are not changed by this section; S1's file passes in R6 and R8. |
| R4 | **The three reproductions of review round 1, before and after.** F1 (`probe_b11s2_window.py`, a real `ProbOSRuntime.start()`; the control is call B after the priming ends): before the repair call A, issued while the priming task was pending, returned the CLI-only token unmasked (`token leaked: True`); after it call A returns `<secret:github>` (`token leaked: False`), the CLI ran once, and the token is in no captured log line. F2 (`probe_b11s2_rotation.py`; the control is a `rotate` with no `get` in flight, which returns the new value on both trees): before the repair, with a `get` in flight, `rotate` returned True and the file held the new value, but the next `get` returned the superseded one; after it the next `get` returns the new value. F3 (`probe_b11s2_f3b.py` through the real `_wire_secret_masker`; the control has no `GH_TOKEN` and the CLI answers, its priming reads the file on a worker on both trees): before the repair, with `GH_TOKEN` set, the priming read no file and the first masking pass read it on the loop thread; after it the priming's worker reads the file and the first pass reads none. |
| R5 | **The cost of the window**, measured on real `ProbOSRuntime.start()` boots (`probe_b11s2_remainder.py`; the CLI delayed by 0.0, 0.1, 0.3 and 1.0 s): the priming starts 0.08 to 0.10 s before `start()` returns (boots took 17.8 to 21.6 s), so a join at the end of `start()` would have blocked it 0.00, 0.02, 0.21 and 0.90 s, and the window is open for the first calls (R4's F1). The real `gh auth token` answered in 68 to 217 ms (one outlier of 1202 ms). The gate waits only for a pending priming and only in `_invoke_once`; startup waits for nothing. |
| R6 | **The campaigns** (`audit\mutants_gen.py`; `rows_ad1337s2r1a.py` and `rows_ad1337s2r1b.py`). Part A reruns the 38 rows of the section 16 campaign on the candidate with the S2 test file alone (24 cases): 37 rows, `S20m` dropped because S3 changed what its line holds (S3's campaign covers `secret_masker_of`); S17m, X12 and X16 are re-anchored to their new lines and the killers of N16 are renamed: **killed 37, differed 0, survived 0, invalid 0**. Part B is the section 17.11 rows R1m to R12m plus my extra rows Y1 to Y5, with S1's file and `tests/test_credential_store.py` beside the S2 file (134 baseline cases): **killed 17, differed 0, survived 0, invalid 0**; every named killer failed, R11m by N16, S1's CLI case and `test_cache_ttl`. Y1 (`end_priming` without its reset) is killed by N18 and N22; Y2 (the deadline in the past) by N16 and N22; Y3 (`DEFAULT_PRIMING_TIMEOUT_S` 0.0) by N16, N18 and N24; Y4 (the worker called with no masker) by N16, N18 and N24; Y5 (the generation read as -1) by N16, S1's CLI case and `test_cache_ttl`. The home was empty after each run. |
| R7 | **Static checks.** `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`). `ToolExecutor` 489 lines and 13 methods, `CredentialStore` 386 lines and 15 methods, `SecretMasker` 175 lines and 9 methods (an AST count). `rg -l masked_credential_values src` finds exactly `credential_store.py` and `security/secret_masking.py`. `git diff 25944b39 --stat` lists only the seven files of 17.3 to 17.9. `finalize.py` does not name `masked_credential_values`. |
| R8 | **The consolidated focused set on the candidate** (the 29 files of the focused gate of 17.13 and the twelve more that read the credential store, the executor or the render seam: 41 files, `-n 0`, default embedding mode, a tree with all 18 operations applied): **2356 passed, 5 skipped** in 797 s (the skips are the POSIX-only cases and BF-657's MagicMock test). The process did not exit after its summary: four `aiosqlite` worker threads left by `tests/test_new_crew_auto_welcome.py` keep it alive, and a probe over that file alone on the main baseline `5d8a5eb4` leaves the same four, so the leak is not this change's; the process was ended after the summary. The run repeats on the committed head, in both embedding modes. |
| R9 | **S3 on the repaired S2** (a scratch tree detached at `25944b39`, this section's 18 operations applied, then S3's section 17 repair): every SEARCH of S3's 20 repair pairs (its four tracker pairs included) occurs exactly once in that order, and S2's file, S3's file and `tests/test_ad1320_agentic_budget_awareness.py` together: **121 passed**. |

**What the orchestrator changed in the Architect's section 17:** the failure reason of N18 in 17.10 (`AttributeError`, not `TypeError`: R2); nothing in the pairs, the tests or the rows; this table replaces the placeholder of 17.17.

**What these checks do not show.**
- The route seam the Architect recorded as the follow-up (the Captain's direct-message tier-1 browser route in `reply_pipeline.py` does not pass through the executor, so the priming gate does not hold it: a window of about one to six seconds at boot, on a page that shows the CLI-only token); no test runs it.
- The 6 s bound is the CLI's 5 s timeout plus one; R5 measured the CLI's answer at 68 to 217 ms (one outlier of 1202 ms), never near the bound.
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.

---

## 18. Repair after review round 2 (2026-11-21)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev3

**Base.** The Builder starts from the S3 head. S3's commits after `ef66019b` do not touch `executor.py` or `tests/test_ad1337_executor_seam.py`, so those two files equal `ef66019b`. The anchors in `PROGRESS.md` and `DECISIONS.md` are in S2's own entries, and each occurs exactly once at `ef66019b` and at `1a1a4782`. Every edited file is `i/lf w/crlf`: match and write each with its own line endings. ASCII only.

**Milestones** (one Builder delegation each; the Builder runs no test):

| M | Content | Commit subject |
|---|---|---|
| M5 | 18.4 (RE3 to RE5, tests first), then 18.3 (RE1, RE2) | `Poll the masking priming above the loop's clock resolution` |
| M6 | RE6, RE7, then `gen_ad_ledger.py` and `--check` as in 7.13 | `Record the priming poll interval` |

### 18.1 Findings and decisions

| Finding | Severity / reach | Decision | Pairs |
|---|---|---|---|
| F1: `_SECRET_PRIMING_POLL_S = 0.01` (`executor.py:1025`) is below the Windows loop's 15.625 ms clock resolution. While the loop has other ready work, each waiting call checks the priming once per loop pass (35,144 checks in 141 ms in the orchestrator's probe; 23,570 in 127 ms in the reviewer's). | P2, ordinary (startup); a regression of RC10 | Raise the poll to 25 ms. N25 pins it two ways: above both the host's resolution and 15.625 ms, and at most one check per call per 10 ms on a real, busy loop. N25 also covers a cancelled waiting call. | RE1, RE2, RE3, RE5 |
| F2: `_held` uses `asyncio.ensure_future` (`test_ad1337_executor_seam.py:201`), which Engineering Principles, Async Discipline (`engineering-principles.md:84`) forbids | P3, test standards; a regression of RC1 | `asyncio.create_task` | RE4 |

**Behaviour after the repair:**
- **Latency.** A call waiting in the window resumes within one poll of `end_priming`: 25 ms on Linux, and at most about 31 ms on Windows (25 ms plus one tick). The window itself lasts 70 to 200 ms for a real `gh`.
- **Busy loop.** Each waiting call makes at most one check per clock tick (about 15.6 ms on Windows) or per 25 ms (Linux), whatever else the loop runs.
- **Unchanged:** the bound (`DEFAULT_PRIMING_TIMEOUT_S`, 6 s, one WARNING), cancellation (it lands in `asyncio.sleep`; nothing in `executor.py` catches `CancelledError`), and the rule that a bare executor never waits.

### 18.2 Rejected designs

- **An event per waiter, set from the worker thread** (`call_soon_threadsafe(event.set)`). It would add a public callback API to S1's approved `SecretMasker`, registration and cancellation bookkeeping, and capture of a loop across threads. All of that would buy only an exact wake, which nothing needs at 25 ms. 17.2 already rejected an `asyncio.Event` on the masker. This would change if a consumer needs sub-tick wake latency in the priming window.
- **A poll computed from `time.get_clock_info`** (`max(0.025, 2 * resolution)`). It adds an import and import-time logic for a clock coarser than 15.625 ms, and no supported clock is that coarse. If one appears, N25's host-resolution assertion fails and names it.
- **A first-call fast path plus a longer poll.** The first check already happens before any sleep (`while ... priming_pending()`), so it adds nothing.

### 18.3 `src/probos/tools/executor.py`

**RE1.** SEARCH:
```
#: AD-1337 S2: how often a registry call waiting for the masker's startup priming checks it again.
_SECRET_PRIMING_POLL_S = 0.01
```
REPLACE:
```
#: AD-1337 S2: how often a registry call waiting for the masker's startup priming checks it again. It must exceed
#: the loop's clock resolution (15.625 ms on Windows): asyncio runs a timer due within one resolution on its next
#: pass, so a shorter sleep becomes one check per pass whenever the loop has other ready work (review round 2).
_SECRET_PRIMING_POLL_S = 0.025
```

**RE2.** SEARCH:
```
    in that window is held before the registry runs, which covers a result and a raised exception's text alike. It
    polls, so it holds no worker thread and works on any loop. The masker bounds the wait
    (``DEFAULT_PRIMING_TIMEOUT_S``) and then lets every call through; without a masker, or with one nobody primes,
```
REPLACE:
```
    in that window is held before the registry runs, which covers a result and a raised exception's text alike. It
    polls every ``_SECRET_PRIMING_POLL_S``, so it holds no worker thread and works on any loop. The masker bounds the
    wait (``DEFAULT_PRIMING_TIMEOUT_S``) and then lets every call through; without a masker, or with one nobody primes,
```

### 18.4 `tests/test_ad1337_executor_seam.py`

**RE3.** SEARCH:
```
import subprocess
import threading
from collections.abc import Iterator
```
REPLACE:
```
import subprocess
import threading
import time
from collections.abc import Iterator
```

**RE4.** SEARCH:
```
    held = asyncio.ensure_future(polls.held.wait())
```
REPLACE:
```
    held = asyncio.create_task(polls.held.wait())
```

**RE5.** SEARCH:
```
    assert len(reads) == 1 and reads[0] != threading.get_ident()  # loaded once, in the priming's worker thread
    assert masker.mask_text(f"{VAULT_A} {CLI_TOKEN}").text == f"<secret:vault> {PLACEHOLDER}"
    assert len(reads) == 1  # the first pass on the loop read no file
```
REPLACE:
```
    assert len(reads) == 1 and reads[0] != threading.get_ident()  # loaded once, in the priming's worker thread
    assert masker.mask_text(f"{VAULT_A} {CLI_TOKEN}").text == f"<secret:vault> {PLACEHOLDER}"
    assert len(reads) == 1  # the first pass on the loop read no file


# -- N25: the wait on a real, busy loop ------------------------------------------------------------------------------


async def test_on_a_busy_real_loop_waiting_calls_poll_sparingly_and_a_cancelled_one_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # asyncio runs a timer due within one clock resolution on its next pass, so a poll at or below it (15.625 ms on
    # Windows, about 1 ns on Linux) is one check per pass whenever the loop has other ready work. The first assertion
    # holds that on every host; the poll count below shows it on a coarse clock, and catches a zero sleep anywhere.
    poll_s = probos.tools.executor._SECRET_PRIMING_POLL_S
    assert poll_s > max(time.get_clock_info("monotonic").resolution, 0.015625)
    masker = _masker(tmp_path)
    masker.begin_priming(secret_masking.DEFAULT_PRIMING_TIMEOUT_S)
    polls = _PrimingPolls(masker, monkeypatch, count=5)
    tool = _EchoTool("echo", f"token={TOKEN}")
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    stop, spins = asyncio.Event(), [0]

    async def _spin() -> None:
        """Other ready work, as at startup: while this runs the loop never blocks in its selector."""
        while not stop.is_set():
            spins[0] += 1
            await asyncio.sleep(0)

    loop = asyncio.get_running_loop()
    spinner = asyncio.create_task(_spin())
    started = loop.time()
    calls = [asyncio.create_task(executor.invoke("agent-1", "echo", {})) for _ in range(5)]
    try:
        assert await _held(polls, calls) is True
        calls[4].cancel()
        with pytest.raises(asyncio.CancelledError):
            await calls[4]
        await asyncio.sleep(0.15)  # the window: four calls wait on the real clock while the loop stays busy
        masker.end_priming()
        results = await asyncio.wait_for(asyncio.gather(*calls[:4]), timeout=10.0)
        elapsed = loop.time() - started
    finally:
        masker.end_priming()
        stop.set()
        await asyncio.gather(spinner, *calls, return_exceptions=True)
    assert [result.output for result in results] == [f"token={PLACEHOLDER}"] * 4
    assert tool.calls == 4  # the cancelled call never reached the registry
    assert spins[0] >= 100  # premise: the loop had other ready work throughout the window
    # At most one check per call per 10 ms of the window, plus its first and last: a 25 ms poll makes about one per
    # 15.6 ms tick on Windows and one per 25 ms on Linux; the unrepaired 10 ms poll made tens of thousands on Windows.
    assert len(polls.answers) <= len(calls) * (elapsed / 0.010 + 2), (len(polls.answers), elapsed)
```

N25 sleeps for one 0.15 s window and runs in about 0.2 s. Every task it creates (the spinner and five calls) is held and awaited in `finally`. It patches no global module: `_PrimingPolls` patches one instance attribute. It does not touch `secret_masking.time`, so the masker reads the real clock, and the 6 s bound is never reached.

### 18.5 `PROGRESS.md`

**RE6.** SEARCH:
```
test_ad1337_executor_seam.py` (24 cases): a call made while the priming is inside `gh` waits
```
REPLACE:
```
test_ad1337_executor_seam.py` (25 cases): waiting calls on a busy real loop check the priming at most once per 10 ms each and a cancelled one never runs; a call made while the priming is inside `gh` waits
```

### 18.6 `DECISIONS.md`

**RE7.** SEARCH (a substring of S2's *Priming (S2)* line; it occurs once at `ef66019b` and at `1a1a4782`):
```
a 10 ms poll that holds no thread)
```
REPLACE:
```
a 25 ms poll that holds no thread; it must exceed the loop's clock resolution, 15.625 ms on Windows, because asyncio runs a timer due within one resolution on its next pass, and review round 2 measured a shorter poll checking tens of thousands of times in 0.15 s on a busy loop)
```

### 18.7 Tests and predicted counts

| N | Change | Property |
|---|---|---|
| `_held` | Edited (RE4) | Same behaviour, through `create_task`. N16 and N22 are unchanged. |
| N25 | New (RE3, RE5) | The poll exceeds the host's clock resolution and 15.625 ms. Five calls wait on a real loop that always has ready work. One is cancelled, raises `CancelledError` and never reaches the registry. The other four resume masked after `end_priming`. The check count stays at or below 5 * (elapsed / 10 ms + 2). |

- **Test pairs only (RE3 to RE5) on the base: 24 passed, 1 failed** on every host. N25 fails at its first assertion (`0.01 > 0.015625` is False).
- **All pairs: 25 passed** (25 items, no parametrize).
- **On Windows** (the gate host), the unrepaired poll with N25's first line removed fails the count assertion by two to three orders of magnitude (about 35,000 checks against a bound near 90). The repaired poll makes about 55. **On Linux CI** (`ubuntu-latest`), a 10 ms poll does not spin: the count assertion cannot tell 10 ms from 25 ms (about 85 checks against about 90), and the first assertion carries the property. A zero sleep fails the count on every host.
- S1's file and S3's file: counts unchanged, all pass. Neither exercises the priming wait.

### 18.8 Mutation rows

These rows run on the M5 candidate, restoring between rows. Rerun R1m to R3m (the rows on the wait, whose test helper changed). The other `executor.py` rows (S1m to S10m, S19m, S21m) stand: RE1 and RE2 change a constant and a comment, which cannot revive a mutant at another line. The test changes only add kills.

| Row | Mutant (one line) | Killed by |
|---|---|---|
| R13m | `_SECRET_PRIMING_POLL_S = 0.025` to `= 0.01` | N25: the first assertion on every host, and the count on Windows |
| R14m | `await asyncio.sleep(_SECRET_PRIMING_POLL_S)` to `await asyncio.sleep(0)` | N25: the count, on every host |
| R1m (rerun) | Delete the gate line in `_invoke_once` | N16, N22, N25 (`_held` is False) |
| R2m (rerun) | Move the gate line to just before the seam | N16 |
| R3m (rerun) | `_await_secret_priming`: `while` to `if` | N22. N25 survives it, as expected. |

Cancellation propagation is checked by N25 and by reading, not by a mutant: swallowing `CancelledError` takes more than one changed line. F2 is checked by grep (18.10), not by a mutant.

### 18.9 What this does NOT change

- `secret_masking.py`: `begin_priming`, `end_priming`, `priming_pending` and `DEFAULT_PRIMING_TIMEOUT_S`.
- `finalize.py` and `credential_store.py` (the priming worker, the warm-up, the fence).
- The `ToolExecutor` class: still 489 lines and 13 methods, because the constant and the helper are module-level.
- S3's files and S3's imports from S2's test file: `_calls_building_a_tool_executor`, `_EchoTool`, `_registry`, `_Events`, `_CapturingLLM`.
- The `SECRET_MASKED` payload, events and config.

### 18.10 Deterministic checks

- **Focused gate at `-n 0`:**
  - The three AD-1337 test files.
  - `test_ad448_wrapped_tool_executor.py`, `test_ad1224_durable_tool_start.py`, `test_ad1316_governed_effect_broker.py`, `test_ad856_agentic_dispatch.py`.
  - `test_ad1324_srp_layout.py`, `test_ad1270b_architecture_fitness.py`, `test_ad1184_ad_ledger.py`.
- **Contention:** also run `test_ad1337_executor_seam.py` once at `-n 16` together with the executor and broker files, to show N25 holds under contention.
- `rg -n "ensure_future" tests/test_ad1337_executor_seam.py tests/test_ad1337_secret_masking.py tests/test_ad1337_render_seam.py src/probos/tools/executor.py` finds nothing.
- `rg -n _SECRET_PRIMING_POLL_S src` finds exactly three hits in `executor.py`: the definition, the docstring and the sleep.
- `rg -n "a 10 ms poll" DECISIONS.md` finds nothing.
- `check_architecture_principles.py --check` exits 0, and `ToolExecutor` is 489 lines and 13 methods.
- `git diff <S3 head> --stat` lists only `executor.py`, the S2 test file, `PROGRESS.md` and `DECISIONS.md`, plus the ledger pair if it is regenerated.
- Run N25 with `-W error` and confirm there is no "Task was destroyed but it is pending".

### 18.11 Verified Against Codebase (2026-11-21, `ef66019b`)

```
grep _SECRET_PRIMING_POLL_S|_await_secret_priming (repo)
  executor.py:726 gate call; :1025 constant 0.01; :1028 def; :1038 sleep; prompt :1947, :1950, :1960, :2164
read executor.py:1024-1038      comment, constant, docstring (:1030-1036), while/sleep
read secret_masking.py:335-360  _priming_deadline, begin/end/priming_pending; DEFAULT_PRIMING_TIMEOUT_S :52
read tests/test_ad1337_executor_seam.py:1-240, :479-768   imports :9-21 (no time); _PrimingPolls :179; _held :198-205 (ensure_future :201); N16 :482; N22 :690 (patches secret_masking.time :699); N24 :749-768 (last lines :766-768)
grep "^(async )?def test_"      24 cases
grep CancelledError|except BaseException executor.py   none
grep engineering-principles.md:84   "Never use asyncio.ensure_future()"
git ls-files --eol              executor.py, test file, PROGRESS.md, DECISIONS.md, the prompt: i/lf w/crlf
grep -o "a 10 ms poll that holds no thread)" DECISIONS.md   :1673 only; git show 1a1a4782:DECISIONS.md: count 1
grep -o "(24 cases): a call made while the priming is inside `gh` waits" PROGRESS.md   :5; at 1a1a4782: count 1
git diff --stat ef66019b 1a1a4782   no executor.py or S2 test file
git show 1a1a4782:tests/test_ad1337_render_seam.py   uses executor_tests._EchoTool/_registry/_Events/_CapturingLLM and _calls_building_a_tool_executor; "priming": 0
grep runs-on .github/workflows   ci.yml:17, :116, :143 ubuntu-latest
grep "### 17.6 " prompt          :1963 only; "10 ms" prompt: :95 (masking p99, unrelated), :1556
```

**Absence verified (2026-11-21):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other `ensure_future` in AD-1337 code or tests | Grep `ensure_future\|get_event_loop\(\|run_until_complete` over `tests/test_ad1337_*.py`, `executor.py`, `finalize.py`, `secret_masking.py`, `credential_store.py`, `render_masking.py` | `test_ad1337_executor_seam.py:201` only | yes |
| No other reader of the constant | `rg _SECRET_PRIMING_POLL_S` (repo) | `executor.py:1025`, `:1038`; the prompt | yes |
| No S2 test sleeps on a real clock today | Grep `asyncio\.sleep` in `tests/test_ad1337_*.py` | `test_ad1337_secret_masking.py:486`, `:490` (`sleep(0)`) only | yes |
| PROGRESS states no interval | `grep -c "10 ms" PROGRESS.md` | 0 | yes |
| No `time` name in the S2 test file to shadow | Grep `\btime\b` | `:699`, `setattr(secret_masking, "time", ...)` (a module attribute) | yes |

**Prior art.** This is a repair of ProbOS plumbing, so no reference-project review was done. One search grounded the mechanism: CPython's loop moves timers due within one clock resolution to the ready queue on the next pass ([bpo-20505](https://www.python.org/pipermail/python-bugs-list/2014-February/231867.html), [bpo-31539](https://bugs.python.org/issue31539)). On Windows, `time.monotonic()` (GetTickCount64) is usually about 15.6 ms coarse ([asyncio-platforms](https://chromium.googlesource.com/external/github.com/python/cpython/+/b2b0a337098e60fa9f84df7b53d191fbd8d4fc67/Doc/library/asyncio-platforms.rst)). Adopted: a poll above the resolution.

### 18.12 Properties for the round-3 delta reviewer

Review only the repair: `git diff ef66019b..HEAD -- src/probos/tools/executor.py tests/test_ad1337_executor_seam.py`, plus S2's entries in `PROGRESS.md` and `DECISIONS.md` (S3's entries in those files belong to S3's review). Execute the checks; do not only read.

1. **The poll.** `_SECRET_PRIMING_POLL_S` exceeds `time.get_clock_info("monotonic").resolution` and 15.625 ms. Rerun your `rv-cancel-poll-cost` probe on the candidate: the counts should match your 20 ms control, not the 10 ms rows.
2. **Cancellation.** A waiting call cancelled on the direct path and on the broker path raises `CancelledError` and never calls `check_and_invoke`. The broker's durable state is `cancelled_before_effect`.
3. **Unchanged.** Before `end_priming` or the bound, the registry runs on no path. Expiry still gives exactly one WARNING. A bare executor, or a masker nobody primes, adds no sleep.
4. **N25.** It fails on `ef66019b`'s `executor.py` on every host (first assertion). On Windows it also fails on the count with that assertion removed. It passes on the candidate, leaves no pending task, and sleeps for only one 0.15 s window.
5. **F2.** `_held` uses `create_task`, and the AD-1337 files contain no `ensure_future`.
6. **No shared contract changed.** The constant is private, and the helpers S3 imports are byte-identical. `ToolExecutor` is still 489 lines and 13 methods.

### 18.13 Acceptance

- [ ] 18.7's predictions hold: 24 passed and 1 failed with the test pairs only, then 25 passed with all pairs. The focused gate in 18.10 is green.
- [ ] R13m and R14m are killed by N25, and R1m to R3m are rerun as listed.
- [ ] RE6 and RE7 are applied, and the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### 18.14 The orchestrator's first-hand checks

The 7 operations of this section (RE1 to RE7) were applied to a scratch worktree detached at `1a1a4782` (the S3 head, which the Builder starts from; S2's files there equal `ef66019b`) by `audit\contract_tools.py apply --prefix 18.` (ASCII only), and every check below was run before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (an empty redirected home; BF-919) and each probe through `run_probe_homeguard.ps1`; a bare `pytest` was not used: it imports `D:\ProbOS\src` and fails for the wrong reason. The contract text corrections C1 and C2 were applied first to the committed contract; their SEARCH text occurs once each.

| R | Result |
|---|---|
| R1 | All 7 operations are found by `contract_tools.py list --prefix 18.`; every SEARCH occurs exactly once on `1a1a4782` (the code, the test and the tracker pairs alike), and again on the scratch tree that holds section 17's operations without S3. Four files change by +59 -7 lines: `executor.py` 6 and 4, the test file 51 and 1, `PROGRESS.md` and `DECISIONS.md` one line each replaced in place. Blobs after all 7 operations: `executor.py` `dec8f91d`, the test file `b86c6ce0`, `PROGRESS.md` `4a4f674e`, `DECISIONS.md` `87be6516`. No added line is non-ASCII. |
| R2 | **The tests alone** (RE3 to RE5 applied, the code pairs not): **1 failed, 24 passed** in 20 s, exactly the prediction of 18.7: N25 fails at its first assertion, `assert 0.01 > 0.015625`. |
| R3 | **N25's count assertion alone discriminates here.** With N25's first assertion removed by a scratch edit and the poll still at 10 ms, N25 fails on its count: 5,658 checks against a bound of 80.5 (`5 * (0.141 / 0.01 + 2)`); the premise holds on this host (`ProactorEventLoop`, `time.get_clock_info("monotonic").resolution` 0.015625). After all 7 operations the test file alone: **25 passed**; S1's file, the S2 file and S3's file together: **145 passed** in 52 s (97 + 25 + 23); N25 alone under `-W error`: 1 passed in 4.3 s, with no pending-task warning. |
| R4 | **The finding's reproduction, before and after** (`probe_b11s2_poll.py`, which measures the module's own default; evidence `evidence-b11s2r2-poll-base.txt` and `evidence-b11s2r2-poll-cand.txt`; four tasks awaiting the real `_await_secret_priming` over a real masker for 150 ms). On `1a1a4782` the default is 10 ms: an idle loop makes 44 checks, a loop with other ready work makes **35,832 in 141 ms**. On the candidate the default is 25 ms: an idle loop makes 24 checks and the busy loop **40**. The probe's own table (an interval of 20 ms: 44; 50 ms: 20) shows the same on the busy loop. Reviewer round 2's report is therefore right that the defect needs other ready work: an idle loop makes 44 checks at 10 ms too. |
| R5 | **The campaign** (`audit\mutants_gen.py`, `rows_ad1337s2r2.py`; a tree holding section 17's and this section's operations, the S2 test file alone, 25 baseline cases, all passing): the rows R13m and R14m of 18.8, the reruns of R1m to R3m, and my extra rows Z1 and Z2: 7 rows, **killed 7, differed 0, survived 0, invalid 0**. Every named killer failed: R13m by N25's first assertion and R14m by its count; R1m by N16, N22 and N25; R2m by N16 (and two more); R3m by N22, with N25 passing, as 18.8 says it does; Z1 (the sleep shortened to a tenth of the poll) by N25's count and Z2 (the poll exactly 15.625 ms) by N25's first assertion. The home was empty after each run. |
| R6 | **Static checks.** `rg -n "ensure_future"` over the three AD-1337 test files and `executor.py` finds nothing; `rg -n _SECRET_PRIMING_POLL_S src` finds exactly three lines in `executor.py` (the definition, the docstring and the sleep); `rg -n "a 10 ms poll" DECISIONS.md` finds nothing; `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); `ToolExecutor` is 489 lines and 13 methods (an AST count); `git diff 1a1a4782 --stat` lists only the four files above. `gen_ad_ledger.py --check` is not run here: the trackers change, and M6 regenerates the ledger. |
| R7 | **The focused gate of 18.10** (the three AD-1337 test files, the executor and broker files `test_ad448_wrapped_tool_executor`, `test_ad1224_durable_tool_start`, `test_ad1316_governed_effect_broker` and `test_ad856_agentic_dispatch`, and `test_ad1324_srp_layout`, `test_ad1270b_architecture_fitness` and `test_ad1184_ad_ledger`: 10 files) on the candidate with 4 workers, so that N25 runs while other tests load the host: **520 passed** in 242 s. |
| R8 | **The first repair's committed head** (`ef66019b`), the 41-file consolidated set of S2, `-n 0`, in both embedding modes: **2356 passed, 5 skipped** in each (1099 s and 1090 s), run before this section was drafted; the aiosqlite leak of `tests/test_new_crew_auto_welcome.py` (the same four threads on `5d8a5eb4`) kept both processes alive after their summary lines, and each was ended after its summary. The run repeats on the head this section produces. |

**What the orchestrator changed in the Architect's section 18:** the single `x` multiplication sign of the N25 row in 18.7 (`5 * (elapsed / 10 ms + 2)`; the section must be ASCII); nothing in the pairs, the test or the rows. I added two rows to 18.8 (Z1: the sleep shortened to a tenth of the poll, below the clock resolution; Z2: the poll set to exactly the clock resolution, 0.015625), which exercise N25's two assertions at their boundary.

**What these checks do not show.**
- A Linux host: on `ubuntu-latest` a 10 ms poll does not spin, so the count assertion of N25 cannot tell 10 ms from 25 ms there, and the first assertion carries the property (the Architect's 18.7 says so).
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.

---

## 19. Repair after the broad gate (2026-11-21)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev4

**Base.** The Builder starts from the batch head `33826d30`. Every edited file is `i/lf w/crlf`: match and write each with its own line endings. ASCII only. Brake decision (round four, a repair after a failed gate): **continue**, scope G1 only; one delta review, then one new broad gate of the whole batch.

**Milestones** (one Builder delegation each; the Builder runs no test):

| M | Content | Commit subject |
|---|---|---|
| M7 | 19.4 (RG3 to RG8, tests first), then 19.3 (RG1) | `Let the runtime own the masking priming task` |
| M8 | RG9, RG10, then `gen_ad_ledger.py` and `--check` as in 7.13 | `Record who owns the masking priming` |

### 19.1 Findings and decisions

| Finding | Severity / reach | Decision | Pairs |
|---|---|---|---|
| G1: `_wire_secret_masker` starts the priming with a bare `asyncio.create_task` (`finalize.py:739-741`), so nothing owns it. A stop's AD-824 sweep (`shutdown.py:1373-1399`), which a failed start's rollback (BF-882) runs too, cancels only `runtime._background_tasks` and `_drain_tasks`. A start that fails while the priming is in `gh` leaves `secret_masking_prime <_prime_secret_masking>` pending, and five cases of `tests/test_issue1419_failed_start_rollback.py` fail on `leftovers() == NOTHING_LEFT`. | P2, ordinary (a start that fails, or a stop, while the priming runs); a regression of S2 | The runtime owns the task: `runtime._spawn_background(..., "secret_masking_prime")` (AD-824). A done callback ends the priming window however the task ends. Test doubles get the real owner; production code gets no fallback. | RG1 to RG10 |

**Behaviour after the repair:**
- **Stop and rollback.** Both cancel a running priming in the AD-824 sweep, and the task ends without waiting for its worker thread. The window closes at once (the done callback), so nothing waits up to 6 s on a priming that has gone.
- **The worker thread** cannot be cancelled. It ends by itself within the CLI's 5 s timeout (`credential_store.py:402`). It holds no loop resource: `_log_access` finds no loop in its thread (`:428-437`), and no shutdown step closes the store. The lifecycle fixture excludes executor threads (`runtime_lifecycle.py:71`, `:155`), and `asyncio.run` joins them when the loop closes.
- **Unchanged:** the order (`begin_priming` before the task exists), the bound, the fence, the warm-up, and startup never waiting on the priming.

### 19.2 Rejected designs

- **A `getattr(runtime, "_spawn_background", None)` fallback to `create_task`** (the orchestrator's scratch repair). It is a production branch that exists only for unit tests (an Architect anti-pattern), and it would silently restore G1 for any runtime without the owner. Only three test doubles need the owner (RG5 to RG7).
- **A `start_task_attr` entry in `shutdown.py`'s BF-881 loop.** `_stop_held_start_service` keys on a service attribute (`shutdown.py:453-458`), and the priming has no service. It would also put S2 into `shutdown.py`.
- **Injecting a `background_register` callable** (the `infrastructure.py:59` pattern). It changes `_wire_secret_masker`'s call, which N19 pins by AST (`test_ad1337_executor_seam.py:607`). It buys nothing over the method `finalize` can already reach (`finalize.py:4410`, `:6909`).
- **Amending `_spawn_background`'s "ONLY for loops" docstring.** That would add `runtime.py` to the diff, and the size ratchet measures `ProbOSRuntime`. The rule exists to keep per-event fan-out out. A single bounded startup task that removes itself when it ends (`runtime.py:4073`) is within its purpose, and the comment in RG1 says so.

### 19.3 `src/probos/startup/finalize.py`

**RG1.** SEARCH:
```
    # AD-1337 S2: every registry call waits for the priming (the masker bounds the wait), so the first one is masked
    # with what the priming adds. Marked before the task exists, so no call can run between the two.
    runtime.secret_masker.begin_priming()
    runtime.secret_masking_prime_task = asyncio.create_task(
        _prime_secret_masking(store, runtime.secret_masker), name="secret_masking_prime",
    )
    return runtime.secret_masker
```
REPLACE:
```
    masker = runtime.secret_masker
    # AD-1337 S2: every registry call waits for the priming (the masker bounds the wait), so the first one is masked
    # with what the priming adds. Marked before the task exists, so no call can run between the two.
    masker.begin_priming()
    # AD-824: the runtime owns the task (one bounded task, which leaves the registry when it ends), so a stop's
    # background sweep, which a failed start's rollback (BF-882) runs too, cancels a priming still in ``gh``. The
    # window closes when the task ends, however it ends: a task cancelled before its first step never reaches the
    # worker, whose ``finally`` is the only other ``end_priming``. The worker thread itself ends within the CLI's
    # timeout and holds nothing a teardown closes.
    task = runtime._spawn_background(_prime_secret_masking(store, masker), "secret_masking_prime")
    task.add_done_callback(lambda _task: masker.end_priming())
    runtime.secret_masking_prime_task = task
    return masker
```

The `asyncio` import in `finalize.py` stays: other code in the module uses it (`:770`, `asyncio.to_thread`).

### 19.4 `tests/test_ad1337_executor_seam.py`

**RG3.** SEARCH:
```
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
```
REPLACE:
```
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
```

**RG4.** SEARCH:
```
from probos.events import EventType
from probos.security import secret_masking
```
REPLACE:
```
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.security import secret_masking
```

**RG5.** SEARCH:
```
    return CredentialStore(store_path=path)


def _masker(directory: Path) -> SecretMasker:
```
REPLACE:
```
    return CredentialStore(store_path=path)


def _owning_runtime(store: Any) -> SimpleNamespace:
    """A runtime double with the runtime's own AD-824 owner, as finalize needs: ``_spawn_background`` registers the
    priming in ``_background_tasks``, which a stop's sweep and a failed start's rollback cancel."""
    runtime = SimpleNamespace(credential_store=store, _background_tasks=set(), _drain_tasks=set())
    runtime._spawn_background = MethodType(ProbOSRuntime._spawn_background, runtime)
    return runtime


def _masker(directory: Path) -> SecretMasker:
```

**RG6.** (N16) SEARCH:
```
    runtime = SimpleNamespace(credential_store=_store(tmp_path))
    tools = (_EchoTool("echo", f"cli={CLI_TOKEN}"), _EchoTool("echo", f"cli={CLI_TOKEN}"))
```
REPLACE:
```
    runtime = _owning_runtime(_store(tmp_path))
    tools = (_EchoTool("echo", f"cli={CLI_TOKEN}"), _EchoTool("echo", f"cli={CLI_TOKEN}"))
```

**RG7.** (N21) SEARCH:
```
    monkeypatch.setattr(store, "get", _recording_get)
    runtime = SimpleNamespace(credential_store=store)
```
REPLACE:
```
    monkeypatch.setattr(store, "get", _recording_get)
    runtime = _owning_runtime(store)
```

**RG8a.** (N24) SEARCH:
```
    runtime = SimpleNamespace(credential_store=_store(tmp_path, {"vault": VAULT_A}))
```
REPLACE:
```
    runtime = _owning_runtime(_store(tmp_path, {"vault": VAULT_A}))
```

N19 (`:537`, a `MagicMock` store) is unchanged: it returns before the task exists.

**RG8b.** (N26, new; appended after N25) SEARCH:
```
    assert len(polls.answers) <= len(calls) * (elapsed / 0.010 + 2), (len(polls.answers), elapsed)
```
REPLACE:
```
    assert len(polls.answers) <= len(calls) * (elapsed / 0.010 + 2), (len(polls.answers), elapsed)


# -- N26: the runtime owns the priming --------------------------------------------------------------------------------


async def test_the_runtime_owns_the_priming_so_a_stop_cancels_it_in_gh_and_its_window_closes_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release, worker_done = threading.Event(), threading.Event(), threading.Event()

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        entered.set()
        assert release.wait(10.0)  # gh answers only after the task was cancelled, as when a start fails late
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")

    original_worker = finalize._prime_secret_masking_worker

    def _worker(store: Any, masker: Any) -> str | None:
        try:
            return original_worker(store, masker)
        finally:
            worker_done.set()

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(finalize, "_prime_secret_masking_worker", _worker)
    runtime = _owning_runtime(_store(tmp_path))
    try:
        masker = finalize._wire_secret_masker(runtime=runtime)
        task = runtime.secret_masking_prime_task
        assert runtime._background_tasks == {task} and task.get_name() == "secret_masking_prime"
        assert await asyncio.to_thread(entered.wait, 10.0)  # the priming is inside gh
        # What a stop's AD-824 sweep does, and a failed start's rollback with it (startup/shutdown.py): cancel every
        # registered task, then wait at most 5 s.
        for registered in list(runtime._background_tasks):
            registered.cancel()
        done, still_pending = await asyncio.wait({task}, timeout=5.0)
        assert done == {task} and not still_pending and task.cancelled()  # it did not wait for the worker thread
        assert runtime._background_tasks == set()  # it left the owner's registry
        assert masker.priming_pending() is False  # the window closed with the task, while the worker is still in gh
    finally:
        release.set()
    assert await asyncio.to_thread(worker_done.wait, 10.0)  # the worker ends alone; nothing waits for it
    assert masker.priming_pending() is False
```

N26 holds every task it waits on and sleeps on no real clock. The worker thread is joined through `worker_done` before the test ends. It patches one module attribute, `finalize._prime_secret_masking_worker`, which `_prime_secret_masking` looks up when it is called (`finalize.py:770`), and the existing `credential_store.subprocess`.

### 19.5 `PROGRESS.md`

**RG9.** SEARCH:
```
(25 cases): waiting calls on a busy real loop
```
REPLACE:
```
(26 cases): the runtime owns the priming task, so a stop or a failed start's rollback cancels a priming still in `gh` and its window closes at once; waiting calls on a busy real loop
```

### 19.6 `DECISIONS.md`

**RG10.** SEARCH (in S2's *Priming (S2)* bullet; it occurs once at `33826d30`):
```
only delays masking of a CLI-only token to its first `get`.
```
REPLACE:
```
only delays masking of a CLI-only token to its first `get`. The runtime owns the priming task (`ProbOSRuntime._spawn_background`, AD-824): a stop's background sweep, which a failed start's rollback runs too (BF-882), cancels a priming still in `gh`, and a done callback ends the window however the task ends; the worker thread cannot be cancelled, ends within the CLI's 5 s timeout and holds nothing a teardown closes (the broad gate found an unowned priming task left behind by a failed start).
```

### 19.7 Tests and predicted counts

| N | Change | Property |
|---|---|---|
| N16, N21, N24 | Double built by `_owning_runtime` (RG6 to RG8a) | Same assertions; the task is now registered |
| N26 | New (RG3 to RG5, RG8b) | Registered under its name; a sweep-shaped cancel while in `gh` ends it without waiting for the thread; it leaves the registry; `priming_pending()` is False before `gh` answers; the worker then ends alone |

- **Test pairs only (RG3 to RG8b) on `33826d30`: 25 passed, 1 failed.** N26 fails at `runtime._background_tasks == {task}` (`set()`).
- **All pairs: 26 passed.**
- **`tests/test_issue1419_failed_start_rollback.py`:** the five G1 cases fail on the base and pass on the candidate; every other case passes on both.
- S1's file and S3's file: counts unchanged, all pass.

### 19.8 Mutation rows (on the M7 candidate, restoring between rows)

| Row | Mutant (one line) | Killed by |
|---|---|---|
| G1m | `task = runtime._spawn_background(...)` to `task = asyncio.create_task(_prime_secret_masking(store, masker), name="secret_masking_prime")` | N26 (registry), and the five G1 cases of the AD-1419 file |
| G2m | Delete `task.add_done_callback(lambda _task: masker.end_priming())` | N26 (`priming_pending()` True before `gh` answers). The AD-1419 file survives it, as expected: it checks tasks, not the window |
| G3m | Add `drain_on_shutdown=True` to the `_spawn_background` call | N26 (`_background_tasks` is empty) |
| R6m (rerun) | Worker: delete `masker.end_priming()` | N18 only. N16 no longer kills it, because the callback ends the window when the task ends |
| R7m (rerun) | Delete `masker.begin_priming()` | N16 |
| S17m (rerun) | The worker body called on the loop instead of in `to_thread` | N16 |

The other rows stand: RG1 changes only `_wire_secret_masker`, and the test changes only add kills. That the cancel lands in the `to_thread` await, without waiting for the thread, is checked by N26's `asyncio.wait` timeout and by reading, not by a mutant.

### 19.9 What this does NOT change

- `shutdown.py`, `rollback.py` and `runtime.py`, including `_spawn_background`'s docstring.
- `secret_masking.py`, `executor.py`, `credential_store.py`, and the priming worker and coroutine in `finalize.py`.
- `_wire_secret_masker`'s signature and its call in `finalize_startup` (pinned by N19, `:607`).
- S3's files, and the helpers S3 imports from S2's test file.
- Events, config and schema.
- The pre-existing unowned `loop.create_task` in `CredentialStore._log_access` (`credential_store.py:429`): not in this batch's diff, and not on this path (the worker thread has no loop).

### 19.10 Deterministic checks

- **Focused gate at `-n 0`:**
  - The three AD-1337 test files.
  - `test_issue1419_failed_start_rollback.py`, `test_issue1452_stop_leftovers.py` (BF-881), `test_ad824_shutdown_hygiene.py`, `test_ad825_drain_shutdown.py`, `test_ad1270a_startup_receipts.py`.
  - The `finalize_startup` double users `test_ad641d_deliberation.py` and `test_bf235_stale_identity_cache.py`. Omit `test_new_crew_auto_welcome.py`: its known aiosqlite thread leak keeps the process alive after its summary (18.14 R8).
  - `test_ad1324_srp_layout.py`, `test_ad1270b_architecture_fitness.py`, `test_ad1184_ad_ledger.py`.
- `rg -n "secret_masking_prime" src` finds the name only in `_wire_secret_masker`'s `_spawn_background` call, and no `create_task` with it.
- `rg -n "getattr\(runtime, \"_spawn_background\"" src` finds nothing.
- `check_architecture_principles.py --check` exits 0.
- `git diff 33826d30 --stat` lists only `finalize.py`, the S2 test file, `PROGRESS.md` and `DECISIONS.md`, plus the ledger pair.
- Run N26 with `-W error` and confirm there is no "Task was destroyed but it is pending" and no "coroutine ... was never awaited".

### 19.11 Verified Against Codebase (2026-11-21, `33826d30`)

```
read finalize.py:715-774         _wire_secret_masker; begin :738; create_task :739-741; return :742; worker :745-757 (end_priming :757); to_thread :770; except Exception :771
grep _wire_secret_masker( src    finalize.py:5892 only; finalize_startup called at runtime.py:3722
grep runtime\._[a-z]\w*\( finalize.py   :4410 _populate_watch_roster, :6909 _setup_nats_event_subscriptions
read runtime.py:4016-4074        _spawn_background(coro, name, *, drain_on_shutdown=False); "Use ONLY for loops" :4031; add/discard :4072-4073
grep _background_tasks/_drain_tasks runtime.py   :1548, :1556 (in __init__)
read shutdown.py:1005-1011, :1367-1399   rollback passes :1010; sweep top-level with its own try; guard :914 "and not rollback"
grep ^\s+return\b shutdown.py    no return between :1011 and the end of shutdown()
read shutdown.py:429-459         _stop_held_start_service keys on service_attr
grep credential_store|secret_mask shutdown.py   none
read secret_masking.py:339-360   begin/end (single assignment)/priming_pending
read credential_store.py:402, :422-437   timeout=5; _log_access swallows RuntimeError without a loop
read tests/fixtures/runtime_lifecycle.py:71, :105-156, :245-281   asyncio_ prefix excluded; leftovers; NOTHING_LEFT
read tests/test_ad1337_executor_seam.py:1-62, :84-97, :483-541, :664-818   imports :18 (types), :29-30; _store :84; _masker :92; doubles :498, :537, :678, :762; N19 pin :607; last line :818
grep ^(async )?def test_         25 cases; parametrize: 0
grep tests/test_ad824_shutdown_hygiene.py   ProbOSRuntime._spawn_background(stub, ...) :72, :106, :137, :176
glob tests/*bf881*|*bf882*       none; tests/test_issue1452_stop_leftovers.py, tests/test_issue1419_failed_start_rollback.py exist
grep finalize_startup( tests      ad1270a :531, ad641d :320, bf235 :122, new_crew_auto_welcome; none sets a credential_store
grep -c "only delays masking of a CLI-only token to its first `get`." DECISIONS.md   1 (:1673)
grep "(25 cases): waiting calls on a busy real loop" PROGRESS.md   :5 only
git ls-files --eol                the four files and this prompt: i/lf w/crlf
git diff 5d8a5eb4 33826d30 -U0 -- src | grep -nE "<scheduling and thread patterns>"   2 hits, both the priming
```

Not verified by the Architect: the AD-1419 file's case count and its result on the repaired tree (the orchestrator's run), and the exact ledger commands (as in 7.13).

### 19.12 Properties for the round-4 delta reviewer

Review only the repair: `git diff 33826d30..HEAD -- src/probos/startup/finalize.py tests/test_ad1337_executor_seam.py`, plus S2's lines in `PROGRESS.md` and `DECISIONS.md`. Execute the checks; do not only read.

1. **Ownership.** On a real `ProbOSRuntime`, the priming task is in `_background_tasks` while it runs. Both a normal `stop()` and a failed start's rollback cancel it, and the AD-1419 file reports no leftover task.
2. **The window.** After a cancel, before the first step or while the worker is in `gh`, `priming_pending()` is False at once. On normal completion the order is unchanged: the warm-up, then `end_priming`.
3. **No fallback.** No production path starts the priming without the owner.
4. **The thread.** A cancelled priming's worker ends alone, writes no access row and touches no closed resource. The lifecycle fixture's thread check is unaffected.
5. **N26** fails on `33826d30`'s `finalize.py` and passes on the candidate. It leaves no pending task or thread under `-W error`.
6. **No shared contract changed.** `_wire_secret_masker`'s signature and call, events, config, and the helpers S3 imports are unchanged.

### 19.13 Acceptance

- [ ] 19.7's predictions hold: 25 passed and 1 failed with the test pairs only, then 26 passed. The focused gate in 19.10 is green, including all of `tests/test_issue1419_failed_start_rollback.py`.
- [ ] G1m to G3m are killed as listed, and R6m, R7m and S17m are rerun.
- [ ] RG9 and RG10 are applied, and the ledger is regenerated and checked.
- [ ] One new broad gate of the whole batch, with a receipt, after the delta review.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Prior art.** This is a repair of ProbOS plumbing (task ownership under AD-824), so no reference-project review was done.

### 19.14 The orchestrator's first-hand checks

The 10 operations of this section (RG1 and RG3 to RG10: there is no RG2) were applied to a scratch worktree detached at `33826d30` (the batch head, which the Builder starts from) by `audit\contract_tools.py apply --prefix 19.` (ASCII only), the test pairs first and the code and tracker pairs after them, as 19.7 predicts; every check below was run before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (an empty redirected home; BF-919) and the campaigns through `mutants_gen.py` (the same redirection); a bare `pytest` was not used: it imports `D:\ProbOS\src` and fails for the wrong reason. The brake decision of this section (continue, G1 only) is the Architect's, from consult `3d592f9e`.

| R | Result |
|---|---|
| R1 | All 10 operations are found by `contract_tools.py list --prefix 19.`, and every SEARCH occurs exactly once on `33826d30` at its turn. Four files change by +71 -11 lines: `finalize.py` 11 and 5 (6,957 to 6,963 lines), the test file 58 and 4 (818 to 872 lines), `PROGRESS.md` and `DECISIONS.md` one line each replaced in place; `gen_ad_ledger.py` then rewrites 4 lines of the ledger pair (`--check`: `AD/BF ledger is current`). Blobs after all of it: `finalize.py` `af5df5be`, the test file `ebade1ca`, `PROGRESS.md` `5b7c6095`, `DECISIONS.md` `430278fc`, `open-ads-report.md` `6c85561c`, `ad-ledger-snapshot.json` `f6383cd6`. No added line is non-ASCII. |
| R2 | **The tests alone** (RG3 to RG8b applied, the code pair not): **1 failed, 25 passed** in 15.9 s, exactly the prediction of 19.7: N26 fails at `assert runtime._background_tasks == {task} and ...` with `set()` on the left (the base never registers the task). After RG1, RG9 and RG10: **26 passed** in 9.8 s. |
| R3 | **N26 alone under `-W error`:** 1 passed in 4.4 s, with no pending-task and no never-awaited warning. |
| R4 | **The finding's reproduction, before and after.** The gate's five failures need a slow `gh`. The redirected home makes `gh` fail at once, and under it the base passes the three functions below (10 items: the race is hidden, not absent). `slowgh` is a pytest plugin outside the repository (`G:\tmp\slowgh\slowgh.py`) that makes only the exact argv `gh auth token` sleep 10 s and fail. With it, on `33826d30`, `tests/test_issue1419_failed_start_rollback.py::test_a_real_boot_that_fails_late_is_fully_rolled_back_even_when_one_stop_raises_after_cleaning_up`, `::test_a_real_boot_whose_stop_raises_before_it_cleans_up_still_has_its_connection_closed` and `::test_a_rollback_persists_nothing_a_clean_stop_persists_and_drains_the_audit_log_once` give **6 failed, 4 passed** (182 s), each failure `{'tasks': ['secret_masking_prime <_prime_secret_masking>']} != {'tasks': []}` (the gate's five failures are among the six); on the candidate they give **10 passed** (184 s). Evidence: `evidence-b11fix-1419-slowgh-red.txt` and `evidence-b11g1-1419-slowgh-green.txt`. |
| R5 | **The campaign** (`audit\mutants_gen.py`, `rows_ad1337s2r3.py`; the S2 test file alone, 26 baseline cases, all passing): the rows G1m to G3m, R6m, R7m and S17m of 19.8; my extra row G4m (`runtime.secret_masking_prime_task = None`); the earlier rows on `finalize.py` rerun as they were (S13m, S16m, S18m, X10, X11, X13, X15, X16, R8m, Y4); and X12 and X14 with new locators, because they followed lines RG1 rewrote: 19 rows, **killed 18, differs 1, survived 0, invalid 0**. Every named killer failed: G1m, G2m and G3m by N26 alone; R6m by N18 alone and R7m by N16 alone, as 19.8 says. The one DIFFERS is Y4 (the worker is handed `None` for the masker): it is killed by two cases, but N16, one of its three named killers, no longer fails, because the done callback now closes the window when the task ends even though the worker raised before its own `end_priming` (the same side effect as R6m's). With its named killers corrected to N18 and N24 the row is killed (`evidence-b11g1-campaign-y4.txt`). The home was empty after each run. |
| R6 | **Static checks.** `rg -n '"secret_masking_prime"' src` finds one line (`finalize.py:745`, the `_spawn_background` call); no `create_task` call in `src` carries `_prime_secret_masking`; `rg -n 'getattr\(runtime, "_spawn_background"' src` finds nothing; `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, the same as before the repair); `git diff 33826d30 --stat` lists only the six files of R1. |
| R7 | **The consumers.** `_wire_secret_masker` has one production caller (`finalize.py:5898`, in `finalize_startup`) and five test calls, all in the S2 test file (N16, N17, N21, N24, N26); N16, N21, N24 and N26 give it a real store, and each builds its runtime double with `_owning_runtime`; N17's double holds a `MagicMock` store and returns before the task exists; N19 pins the production call's text by an AST scan. Of the five test files that call `finalize_startup`, four build no `CredentialStore` (`test_ad1270a_startup_receipts.py`, `test_ad641d_deliberation.py`, `test_bf235_stale_identity_cache.py`, `test_new_crew_auto_welcome.py`) and `test_bf908_crew_scope_token.py` only names it in a docstring and in a source-order assertion, so none reaches the spawn. `tests/test_ad824_shutdown_hygiene.py` binds `ProbOSRuntime._spawn_background` to a stub the same way (lines 72 to 176), the precedent for RG5. |
| R8 | **The focused gate of 19.10** (13 files, `-n 0`) on the oracle tree with the repair and the regenerated ledger pair, in both embedding modes, runs after this section is committed; its result is in the pull request text. It is repeated on the Builder's head only if the Builder's blobs differ from R1's. |

**What the orchestrator changed in the Architect's section 19:** nothing in the pairs, the tests or the rows of 19.8 (the section is ASCII). Two remarks on its text, which stands as written: 19.4's note on the unchanged `MagicMock`-store case calls it N19, but it is N17 (N19 is the AST pin of the call, which 19.9 names correctly); and 19.8's "the other rows stand" needed two corrections, both in my campaign file: X12 and X14 follow lines RG1 rewrote and have new locators, and Y4 lost N16 as a killer (R5). The labels RG8a and RG8b needed my pair tool to accept a one-letter suffix; the contract text is unchanged.

**What these checks do not show.**
- A host where `gh` is slow, other than through the plugin: the new broad gate, which runs with the real home, is the first test of that.
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.

---

## 20. Repair after review round 4 (2026-11-21)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev5

**Base.** The Builder starts from the batch head `e12d0a4d`. Every edited file is `i/lf w/crlf`: match and write each with its own line endings. ASCII only. Brake decision (round five, a P1 that regresses section 19's repair): **continue**, scope R4 only; one delta review, then the batch's second broad gate.

**Milestones** (one Builder delegation each; the Builder runs no test):

| M | Content | Commit subject |
|---|---|---|
| M9 | 20.4 (RH2, test first), then 20.3 (RH1) | `Keep the masking window open when a stop cancels the priming` |
| M10 | RH3, RH4, then `gen_ad_ledger.py` and `--check` as in 7.13 | `Record that a cancel does not end the masking window` |

### 20.1 Findings and decisions

| Finding | Severity / reach | Decision | Pairs |
|---|---|---|---|
| R4: section 19's done callback (`finalize.py:746`) ends the priming window when the task ends. A stop's sweep cancels the task while the worker thread is still in `gh` (`asyncio.to_thread` cannot stop it), so a waiting registry call (`executor.py:1039`) is released before the value is primed and returns the raw CLI token. Measured: base `<secret:github>`, `e12d0a4d` the raw value. | P1, ordinary (a tool call waiting during a stop); a regression of section 19 | Delete the callback. The window ends in exactly two ways: the worker's `finally` (`finalize.py:761-763`) or the masker's bound (`secret_masking.py:356-360`). Ownership stays. | RH1 to RH4 |

**Cases after the repair:** (b), a cancel while the worker is in `gh`: calls are held until the worker returns (at most the CLI's 5 s timeout) or the bound. (c), a cancel before a pool thread starts the worker, reachable only on a saturated default executor: calls are released at the bound, unprimed. That is the accepted fail-open of section 17, the same as a hung `gh`. (a) and (d) cannot be reached while tool calls run (consult answer 2026-11-21). On normal completion nothing changes.

### 20.2 Rejected designs

- **O1: keep the callback but skip it on a cancel.** Identical to RH1 on every reachable case. Its only difference is (d), which is unreachable, so it adds a branch with nothing to pin it.
- **O3: fail closed after a cancel** (the reviewer's sketch). A new masker state and new executor behaviour, and it undoes section 17's fail-open bound.
- **O4: a "worker started" flag.** Racy in case (c).
- **`asyncio.shield` around `to_thread`,** so that (c) still primes. It leaves a future nobody owns, for a case that only arises during a stop on a saturated executor and is already bounded.
- **Reverting the ownership.** Brings G1 back.

### 20.3 `src/probos/startup/finalize.py`

**RH1.** SEARCH:
```
    # AD-824: the runtime owns the task (one bounded task, which leaves the registry when it ends), so a stop's
    # background sweep, which a failed start's rollback (BF-882) runs too, cancels a priming still in ``gh``. The
    # window closes when the task ends, however it ends: a task cancelled before its first step never reaches the
    # worker, whose ``finally`` is the only other ``end_priming``. The worker thread itself ends within the CLI's
    # timeout and holds nothing a teardown closes.
    task = runtime._spawn_background(_prime_secret_masking(store, masker), "secret_masking_prime")
    task.add_done_callback(lambda _task: masker.end_priming())
    runtime.secret_masking_prime_task = task
    return masker
```
REPLACE:
```
    # AD-824: the runtime owns the task (one bounded task, which leaves the registry when it ends), so a stop's
    # background sweep, which a failed start's rollback (BF-882) runs too, cancels a priming still in ``gh``. The
    # window is not ended by that cancel: the worker thread cannot be cancelled, and the value is primed only when
    # it returns. Only the worker's ``finally`` or the masker's bound ends it. The thread ends within the CLI's
    # timeout and holds nothing a teardown closes.
    runtime.secret_masking_prime_task = runtime._spawn_background(
        _prime_secret_masking(store, masker), "secret_masking_prime",
    )
    return masker
```

### 20.4 `tests/test_ad1337_executor_seam.py`

**RH2.** SEARCH (N26, from its banner to the end of the file):
```
# -- N26: the runtime owns the priming --------------------------------------------------------------------------------


async def test_the_runtime_owns_the_priming_so_a_stop_cancels_it_in_gh_and_its_window_closes_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release, worker_done = threading.Event(), threading.Event(), threading.Event()

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        entered.set()
        assert release.wait(10.0)  # gh answers only after the task was cancelled, as when a start fails late
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")
```
REPLACE:
```
# -- N26: the runtime owns the priming, and a stop's cancel does not end its window ----------------------------------


async def test_the_runtime_owns_the_priming_and_a_call_after_a_stop_cancels_it_in_gh_waits_for_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release, worker_done = threading.Event(), threading.Event(), threading.Event()

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        entered.set()
        assert release.wait(10.0)  # gh answers only after the cancel and a held call, as when a stop lands in gh
        return SimpleNamespace(returncode=0, stdout=CLI_TOKEN + "\n")
```

**RH2b.** SEARCH:
```
    monkeypatch.setattr(finalize, "_prime_secret_masking_worker", _worker)
    runtime = _owning_runtime(_store(tmp_path))
    try:
        masker = finalize._wire_secret_masker(runtime=runtime)
        task = runtime.secret_masking_prime_task
        assert runtime._background_tasks == {task} and task.get_name() == "secret_masking_prime"
```
REPLACE:
```
    monkeypatch.setattr(finalize, "_prime_secret_masking_worker", _worker)
    # The masker's clock stands still (N22's seam), so its bound cannot pass however slow the host is: here only the
    # worker can end the window. N22 pins the bound itself.
    monkeypatch.setattr(secret_masking, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    runtime = _owning_runtime(_store(tmp_path))
    tool = _EchoTool("echo", f"cli={CLI_TOKEN}")
    try:
        masker = finalize._wire_secret_masker(runtime=runtime)
        task = runtime.secret_masking_prime_task
        assert runtime._background_tasks == {task} and task.get_name() == "secret_masking_prime"
```

**RH2c.** SEARCH:
```
        assert runtime._background_tasks == set()  # it left the owner's registry
        assert masker.priming_pending() is False  # the window closed with the task, while the worker is still in gh
    finally:
        release.set()
    assert await asyncio.to_thread(worker_done.wait, 10.0)  # the worker ends alone; nothing waits for it
    assert masker.priming_pending() is False
```
REPLACE:
```
        assert runtime._background_tasks == set()  # it left the owner's registry
        assert masker.priming_pending() is True  # the cancel did not end the window: the value is not primed yet
        polls = _PrimingPolls(masker, monkeypatch, count=2)
        executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
        call = asyncio.create_task(executor.invoke("agent-1", "echo", {}))
        assert await _held(polls, [call]) is True  # a call made after the cancel waits while the worker is in gh
        assert tool.calls == 0
    finally:
        release.set()
    assert await asyncio.to_thread(worker_done.wait, 10.0)  # the worker ends alone; nothing waits for it
    result = await asyncio.wait_for(call, timeout=10.0)
    assert result.output == f"cli={PLACEHOLDER}" and tool.calls == 1  # released by the worker, masked with its value
    assert polls.original() is False
```

No new import: `secret_masking`, `SimpleNamespace`, `ToolExecutor`, `_registry`, `_EchoTool`, `_PrimingPolls`, `_held` and `PLACEHOLDER` are already in the module (`:18`, `:31`, `:42-45`, `:61`, `:110`, `:132`, `:189`, `:208`). The test sleeps on no wall clock. Its only waits are on events and on the 25 ms poll, so it finishes in well under a second, and the frozen clock takes the 6 s bound out of play.

**Case (a) stays unpinned.** It cannot be reached through a stop or a rollback (20.1), and its outcome is the bound, which N22 pins. If it is ever wanted, the seam is the frozen module clock above. Monkeypatching `DEFAULT_PRIMING_TIMEOUT_S` has no effect: `begin_priming`'s default argument was bound when the module was imported (`secret_masking.py:339`).

### 20.5 `PROGRESS.md`

**RH3.** SEARCH:
```
cancels a priming still in `gh` and its window closes at once; waiting calls on a busy real loop
```
REPLACE:
```
cancels a priming still in `gh`, and a call made after that cancel is still held until the worker returns or the bound passes; waiting calls on a busy real loop
```

### 20.6 `DECISIONS.md`

**RH4.** SEARCH (in S2's *Priming (S2)* bullet, `:1673`; it occurs once at `e12d0a4d`):
```
cancels a priming still in `gh`, and a done callback ends the window however the task ends; the worker thread cannot be cancelled
```
REPLACE:
```
cancels a priming still in `gh`, but that cancel does not end the window: only the worker's `finally` or the bound does, since a task's end is not the value's priming (review round 4 found a done callback that released waiting calls unmasked); the worker thread cannot be cancelled
```

### 20.7 Tests and predicted counts

| N | Change | Property |
|---|---|---|
| N26 | Rewritten (RH2 to RH2c) | Registered under its name; a sweep-shaped cancel while in `gh` ends the task without waiting for the thread; the task leaves the registry; `priming_pending()` is still True after the cancel; a registry call made after the cancel is held while the worker is in `gh`; once released it returns `cli=<secret:github>`, and the tool runs once |

- **Test pairs only, on `e12d0a4d`: 25 passed, 1 failed.** N26 fails at `assert masker.priming_pending() is True` (the callback closed the window).
- **All pairs: 26 passed.**
- `tests/test_issue1419_failed_start_rollback.py`: all pass, as on `e12d0a4d`; it checks tasks, not the window. The slow-gh trio: 10 passed.
- S1's file and S3's file: counts unchanged, all pass.

### 20.8 Mutation rows (one campaign on the M9 candidate, the S2 test file alone, restoring between rows)

| Row | Mutant (one line) | Killed by |
|---|---|---|
| H1m | Re-add `runtime.secret_masking_prime_task.add_done_callback(lambda _task: masker.end_priming())` after the spawn (section 19's RG1) | N26 (`priming_pending() is True` after the cancel) |
| G1m (rerun) | The spawn becomes `asyncio.create_task(_prime_secret_masking(store, masker), name="secret_masking_prime")` | N26 (registry) |
| G3m (rerun) | Add `drain_on_shutdown=True` to the spawn | N26 (`_background_tasks` empty) |
| R6m (rerun) | Worker: delete `masker.end_priming()` | N16, N18 and N26 (N26 at its 10 s `wait_for`). N16 kills it again now the callback is gone |
| R7m (rerun) | Delete `masker.begin_priming()` | N16, N26 |
| Y4 (rerun) | The worker is handed `None` for the masker | N16, N18, N24 (section 19.14 R5 corrected this to N18 and N24; N16 kills it again) |
| S17m (rerun) | The worker body runs on the loop instead of in `to_thread` | N16 |

- **G2m is retired.** Deleting the callback is now the candidate itself, and H1m is its inverse.
- **Relocate first:** every earlier `finalize.py` row whose locator falls in the old lines 740-748 (X12, X14 at least). Rerun the rest of 19.14 R5's `finalize.py` rows unchanged.
- **Not a row:** the O1 callback (`None if done.cancelled() else masker.end_priming()`). It is equivalent to the candidate on every reachable case, so it is expected to survive.

### 20.9 What this does NOT change

- `secret_masking.py`, `executor.py`, `credential_store.py`, `shutdown.py`, `rollback.py` and `runtime.py`.
- The worker, `_prime_secret_masking`, and both their docstrings, which already say the worker or the bound ends the wait.
- `_wire_secret_masker`'s signature and its call (N19, `:607`).
- The ownership (G1 stays repaired).
- The 6 s bound and its single WARNING.
- S3's files and `_calls_building_a_tool_executor`, the one helper S3 imports (`test_ad1337_render_seam.py:71`).
- Events, config and schema.

### 20.10 Deterministic checks

- **Focused gate at `-n 0`:** the list in 19.10 unchanged; it already includes `tests/test_issue1419_failed_start_rollback.py`. Add the slow-gh trio of 19.14 R4, which must give 10 passed.
- `rg -n "add_done_callback" src/probos/startup/finalize.py` finds nothing.
- `rg -n "end_priming\(" src` finds only `secret_masking.py:346` (the definition) and the worker's `finally` in `finalize.py`.
- `rg -n '"secret_masking_prime"' src` finds one line, the `_spawn_background` call.
- Run N26 with `-W error`: no pending-task or never-awaited warning.
- `check_architecture_principles.py --check` exits 0 with the counts of 19.14 R6.
- `git diff e12d0a4d --stat` lists only the four files plus the ledger pair. The ledger diff may be empty: neither replaced clause appears in it. Run `--check` either way.

### 20.11 Verified Against Codebase (2026-11-21, `e12d0a4d`)

```
read finalize.py:715-780        wire; begin :739; spawn :745; callback :746; worker finally :761-763; to_thread :776; except Exception :777
read secret_masking.py:330-361  import time :33; begin :339 (default bound at def); end :346; pending :350-360; time. only :344, :356
read executor.py:726, :1024-1040  wait before the registry; loop exits only on pending False or the caller's cancel
read shutdown.py:1367-1399      sweep cancels _background_tasks/_drain_tasks, wait 5 s
read rollback.py:40-99          rollback awaits create_task(shutdown(..., rollback=True))
read credential_store.py:350-369  _resolve (gh) runs outside _publish_lock
read tests/test_ad1337_executor_seam.py:189-215, :700-729, :830-872   _PrimingPolls; _held; N22 clock seam :709; N26 (last line :872)
grep add_done_callback|end_priming\( finalize.py   :746, :763
grep "and its window closes at once" PROGRESS.md   1 (:5)
grep "a done callback ends the window however the task ends" DECISIONS.md   1
grep its_window_closes_at_once (outside prompts/)   N26's definition only
grep shutdown_default_executor|set_default_executor src   comment only (audio/tts/resident.py:20)
git diff 5d8a5eb4 e12d0a4d -U0 -- src | grep <lifecycle/wait patterns>   finalize.py (callback, worker finally, to_thread), secret_masking.py (window, threading locks), executor.py (:1126 the wait), credential_store.py (two threading locks)
```

Not verified by the Architect: the test counts, the campaign, and the slow-gh trio on the repaired tree (the orchestrator runs them), the ledger commands, and the `i/lf w/crlf` attribute of each file (taken from 19.11).

### 20.12 Properties for the round-5 delta reviewer

Review only the repair: `git diff e12d0a4d..HEAD -- src/probos/startup/finalize.py tests/test_ad1337_executor_seam.py`, plus S2's lines in `PROGRESS.md` and `DECISIONS.md`. Execute the checks; do not only read.

1. **Release.** A call waiting on the priming window is released only when the worker has returned or the bound has passed. This also holds after a stop's cancel and after a failed start's rollback. Rerun round 4's real-runtime `stop()` measurement: the model-facing tool message is `<secret:github>`, and the call is released after the worker returns.
2. **Ownership unchanged.** The task is in `_background_tasks` while it runs. `stop()` and rollback cancel it without waiting for the thread. The AD-1419 file reports no leftover task, and the slow-gh trio gives 10 passed.
3. **One way to end the window.** No production code ends the window except the worker's `finally` and the masker's own bound.
4. **N26** fails on `e12d0a4d`'s `finalize.py` and passes on the candidate. It does not depend on the host's speed, and under `-W error` it leaves no pending task or thread.
5. **No shared contract changed.** Signatures, the call N19 pins, events, config and S3's helper are unchanged.

### 20.13 Acceptance

- [ ] 20.7's predictions hold (25 passed and 1 failed with the test pairs only, then 26 passed), and the focused gate of 20.10 is green.
- [ ] H1m, G1m and G3m are killed as listed. R6m, R7m, Y4 and S17m are rerun with the killers of 20.8, and the relocated rows are rerun.
- [ ] RH3 and RH4 are applied, and the ledger is regenerated and checked.
- [ ] One delta review, then the batch's second broad gate, with a receipt.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Prior art.** None reviewed: this is a ProbOS plumbing repair. It is the general rule that a task's cancellation does not stop work inside `to_thread`.

### 20.14 The orchestrator's first-hand checks

The 6 operations of this section (RH1, RH2, RH2b, RH2c, RH3, RH4) were applied to a scratch worktree detached at `e12d0a4d` (the head the Builder starts from) by `audit\contract_tools.py apply --prefix 20.` (ASCII only), the test pairs first and the others second for R2. A second copy of that tree ran the campaign, so no run touched another's files. Results:

| R | Result |
|---|---|
| R1 | All 6 operations are found by `contract_tools.py list --prefix 20.`, and every SEARCH occurs exactly once on `e12d0a4d` at its turn. Four files change by +23 -12 lines: `finalize.py` 5 and 5 (6,963 lines before and after; blob `e87db7d2b7b1`), the test file 16 and 5 (872 to 883 lines; blob `af1b24d0e1fb`), `PROGRESS.md` and `DECISIONS.md` one line each replaced in place (blobs `2f9896310e53` and `db4d6ba5c477`). The blob after each operation is in the `contract_tools.py checkpoints --prefix 20.` table that the Builder briefs carry. |
| R2 | **The tests alone** (RH2, RH2b and RH2c applied, the code pair not): **1 failed, 25 passed** in 16.2 s, exactly the prediction of 20.7: N26 fails at `assert masker.priming_pending() is True` with `False` on the left, because `e12d0a4d`'s done callback ends the window when the sweep cancels the task. |
| R3 | **All pairs: 26 passed** in 16.5 s. **N26 alone under `-W error`:** 1 passed in 4.6 s, with no pending-task and no never-awaited warning. |
| R4 | **The finding's reproduction, before and after.** The probe is a scratch file (not committed; N26 is its committed form): a real owning runtime double with `_spawn_background`, a `gh` double that blocks on an event, `finalize._wire_secret_masker`, a cancel of the priming task once the worker is inside `gh`, a real `ToolExecutor(secret_masker=masker)` whose registry returns `cli=<the CLI-only token>`, one call made right after the cancel, then the event is released. Base `33826d30` (nothing registers the task, so the same cancel is applied to it directly): window open after the cancel, the call released only after the worker returned, `cli=<secret:github>`. `e12d0a4d`: window closed, the call released **before** the worker returned, and the raw value `gho-cli-only-K8d3Pz5Tq1` reached the caller. The repaired tree: window open, the call released after the worker returned, `cli=<secret:github>`, one registry call. |
| R5 | **The campaign** (`audit\mutants_gen.py`, `rows_ad1337s2r4.py`; the S2 test file alone, 26 baseline cases, all passing): the rows H1m, G1m, G3m, R6m, R7m, X12, X14 and G4m of 20.8, and the eleven earlier rows on `finalize.py` rerun as they were (S13m, S16m, S17m, S18m, X10, X11, X13, X15, X16, R8m, Y4): **19 killed, 0 differ, 0 survived, 0 invalid**, and every named killer failed in every row (R6m by N16, N18 and N26; Y4 by N16, N18 and N24, as 20.8 predicts). The mutation tool replaces one line, so the rows on the three-line spawn are written as one-line edits: G1m turns the first line into a lambda that calls `asyncio.create_task(coro, name=name)`, G3m and X12 edit the second line, G4m sets the attribute to `None` before the spawn, and H1m puts the callback before `return masker` with a semicolon. The row that 20.8 says is not a row, O1m (the callback skipped on a cancel), was run alone: **SURVIVED** (no case failed), as predicted, because it is equivalent to the candidate on every reachable case. The tree was restored after both runs (its four blobs equal R1's). |
| R6 | **Static checks.** `rg -n "add_done_callback" src/probos/startup/finalize.py` finds nothing; `rg -n "end_priming\(" src` finds `finalize.py:763` (the worker's `finally`) and `secret_masking.py:346` (the definition); `rg -n '"secret_masking_prime"' src` finds one line (`finalize.py:746`, the `_spawn_background` call); no `create_task` call in `src` carries `_prime_secret_masking`; `rg -n 'getattr\(runtime, "_spawn_background"' src` finds nothing; `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, the same as before the repair). `git diff e12d0a4d --stat` lists the four files above, and after `gen_ad_ledger.py` the ledger pair too (6 lines in the snapshot and 2 in the report: `captured_at`, `head`, `subject_count`), so the ledger diff is not empty; `gen_ad_ledger.py --check` reports the ledger current. |
| R7 | **The slow-gh proof.** The three functions of `tests/test_issue1419_failed_start_rollback.py` that the broad gate failed in (10 items), run with the `slowgh` pytest plugin (`gh auth token` sleeps 10 s, where the home-guard wrapper's empty home makes `gh` fail at once and hides the race), 3 workers: **10 passed** in 168 s on the repaired tree (176 s on the one-file prototype that preceded it). On `33826d30`, where nothing owns the task, the same run gave 6 failed and 4 passed; `e12d0a4d` gave 10 passed. |
| R8 | **The consumers and the reachability claims.** `_wire_secret_masker` has one production caller (`finalize.py:5898`, in `finalize_startup`) and five test calls, all in the S2 test file (N16, N17, N21, N24, N26; N19 only pins the call's text); the repair changes none of them and no signature. `masker.end_priming()` is called in `src` only by the worker's `finally`, and the masker's bound still ends the window with one WARNING. The claims of 20.1 were read, not assumed: `startup/rollback.py:97-99` creates the rollback's shutdown as a NEW task (`asyncio.create_task(shutdown(..., rollback=True))`), so the priming task, whose first step was scheduled when it was created, runs that step first; `startup/shutdown.py:1385-1391` cancels the registered tasks only after the drain's awaits; and `rg -n "shutdown_default_executor|set_default_executor" src` finds only a comment (`audio/tts/resident.py:20`), so nothing in `src` shuts the default executor down while the loop runs. |
| R9 | **The focused gate of 20.10** (the 13 files of 19.10, `-n 0`) on the oracle tree with the repair and the regenerated ledger pair, in both embedding modes, runs beside this commit; its result is in the pull request text. The slow-gh proof is R7. |

**What the orchestrator changed in the Architect's section 20:** nothing in the pairs, the test or the rows of 20.8 (the section is ASCII). Three remarks on its text, which stands as written. (1) RH2's lead line says its SEARCH runs "from its banner to the end of the file"; the block covers the banner through the `_gh` double (the checkpoint table gives contract lines 61 to 72), which is all the pair needs. (2) 20.10 says the ledger diff may be empty; it is not (R6), and M10 regenerates it as in 7.13. (3) Case (c) of 20.1, a cancel before a pool thread starts the worker on a saturated default executor, is neither pinned by a test nor repaired: the call is released at the bound, as with a hung `gh`, which is the accepted fail-open of section 17.

**What these checks do not show.**
- A saturated default executor (case (c)), a slow host other than through the plugin, and any live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.
- The second broad gate, which runs with the real home, is the first full-suite test of this repair.

---

## 21. Repair after CI (2026-11-23)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-23, rev6 (consult `0315be7c`); assembled by the orchestrator, who adapted pair CI2's SEARCH to the head's text (the Architect's answer assumed the orchestrator's earlier four-line draft was in the tree)

**Base.** The SEARCH texts are the test file as at `108a7fff`, the head of PR #1846; the Builder starts from the commit that adds this section on top of it (no other file differs). The one edited file is `i/lf w/crlf`: match and write it with its own line endings. ASCII only. Brake decision (a regression found by CI after five review rounds and two brakes; a regression that breaks the next run cannot be rescoped): **continue**, scope C1 only; one delta review, then a new canonical gate (this test change invalidates the receipt of the last one), a fast-forward push to the PR's branch, CI and the merge. No `PROGRESS.md` or `DECISIONS.md` entry: the repair is test-only, takes no AD or BF number and makes no architectural decision.

**Milestone** (one Builder delegation; the Builder runs no test):

| M | Content | Commit subject |
|---|---|---|
| M11 | 21.3 (CI1, CI2, CI3) | `Make the archive isolation boot test hermetic against the credential CLI` |

### 21.1 Finding and decision

| Finding | Severity / reach | Decision | Pairs |
|---|---|---|---|
| C1: PR #1846's CI (run 45286572765, Linux, Python 3.12.16) failed `tests/test_bf919_archive_isolation.py::test_a1_a_default_config_boot_opens_this_tests_archive_and_leaves_an_empty_home_empty` at line 103, `assert sorted(home.rglob("*")) == []`, which found `home/.local`, `home/.local/state`, `home/.local/state/gh` and `home/.local/state/gh/device-id`. S2's startup priming (`finalize._wire_secret_masker`; its worker calls `store.get("github", requester="secret_masking")`) reaches the CLI step of `CredentialStore._resolve` (`credential_store.py:396-407`) when neither `GH_TOKEN`, `GITHUB_TOKEN` nor the store holds the token, and runs `["gh", "auth", "token"]` with `trusted_command_env()`, which allows `HOME` (`execution/command_env.py:46`) and not `XDG_STATE_HOME`. A1 points HOME at an empty directory and boots a real runtime, so the real Linux `gh` kept its state there. A Windows gate cannot see it: `gh` writes no such file under `USERPROFILE`. | Blocker (the pull request's CI is red), ordinary reach (every Linux run), a regression of S2's priming | **O1b:** A1 answers the priming at the environment step (`GH_TOKEN`), stands in for the credential store's `subprocess` with a recorder that fails every command, waits for the priming before the stop, and asserts that no command ran. A1 then proves on any platform that a default boot runs no credential CLI, and with the `GH_TOKEN` line removed it fails on Windows too. | CI1 to CI3 |

**Reproduction (orchestrator).** A pytest plugin (`-p ghwrite`, outside the repo) makes only the exact argv `["gh", "auth", "token"]` write `$HOME/.local/state/gh/device-id` and fail, and logs each call; every other `subprocess.run` is untouched. One test each:

| Tree | Plugin | Result |
|---|---|---|
| head `108a7fff` | on | A1 FAILS with the CI's assertion; the plugin log shows the call wrote under the test's home |
| base `5d8a5eb4` | on | passes (the base never runs the CLI at boot) |
| head | off | passes (what every canonical gate saw) |
| head + a one-line `GH_TOKEN` | on | passes; no plugin log (the CLI was never asked) |

This is the follow-up item R23 (tests that boot a real runtime run the developer's real `gh auth token`), raised from Low to Medium with ordinary reach (batch 2's #1820 splice carries its updated text, in 21.9). S2's reviewer briefs called it "recorded for a follow-up" and said the token is never written: true of the token, false of `gh`'s own state under HOME.

### 21.2 Rejected designs

- **O1a: `GH_TOKEN` alone.** It fixes CI, but nothing in the repo detects the line being lost; its proof rests on a plugin outside the repo.
- **O2: a shared autouse fixture** that makes the CLI step inert for every test. This is R23's own repair. It touches the whole suite (54,892 nodes, both embedding modes), so it gets its own review and gate, after this merge.
- **O3: skip the CLI at boot.** No honest criterion exists: the CLI step is the point of the priming (a token only `gh` knows is masked from the first call).
- **O4: run the CLI with an isolated state directory** (`XDG_STATE_HOME` or `GH_CONFIG_DIR`). `gh auth token` needs the operator's configuration directory to find a stored token, so it would break the priming for real operators.
- **O5: exempt `.local/state/gh` in A1's assertion.** It weakens BF-919's guard, whose point is that a boot writes nothing there.

### 21.3 `tests/test_bf919_archive_isolation.py`

**CI1.** SEARCH:
```
import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Any
```
REPLACE:
```
import asyncio
import contextlib
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
```

**CI2.** SEARCH (in A1; it occurs once):
```
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend: this boot needs no model (M2 owns that path)
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
```
REPLACE:
```
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend: this boot needs no model (M2 owns that path)
    # AD-1337 S2: a boot primes the GitHub credential for the secret masker. Answered at the environment step, the
    # priming never reaches the CLI step, whose real `gh` writes its own state under HOME (Linux:
    # ~/.local/state/gh/device-id; PR #1846's CI), a file this test would count as the boot's. The recorder stands in
    # for every command the credential store runs and fails each one, so the test proves on any platform that none ran.
    monkeypatch.setenv("GH_TOKEN", "bf919-a1-not-a-real-token")
    cli_calls: list[list[str]] = []

    def _cli(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        cli_calls.append(list(argv))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_cli, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
```

**CI3.** SEARCH (in A1; it occurs once):
```
    await rt.start()
    try:
        assert isolated_archive_path.is_file(), "the boot opened this test's own archive"
    finally:
        await rt.stop()
    assert _user_version(isolated_archive_path) == ARCHIVE_SCHEMA_VERSION, "and migrated it there"
```
REPLACE:
```
    await rt.start()
    try:
        assert isolated_archive_path.is_file(), "the boot opened this test's own archive"
        priming = rt.secret_masking_prime_task
        assert isinstance(priming, asyncio.Task), "premise: the boot started the secret masker's priming"
        # Waited for before the stop: the stop's sweep cancels the task, not its worker thread, which could still run.
        done, _ = await asyncio.wait({priming}, timeout=10.0)
        assert priming in done, "the priming finished, so its worker thread has run"
    finally:
        await rt.stop()
    assert cli_calls == [], "the boot ran no credential CLI: the priming answered from GH_TOKEN"
    assert _user_version(isolated_archive_path) == ARCHIVE_SCHEMA_VERSION, "and migrated it there"
```

**Why waiting on the task is safe.**
- `_wire_secret_masker` sets `runtime.secret_masking_prime_task` during `finalize_startup` (`finalize.py:728, 745-747, 5898`; `runtime.py:3722`), so the attribute exists once `start()` returns; A1 reads it only after `start()`.
- `_prime_secret_masking` catches `Exception` (`finalize.py:776-780`), so a failing priming still ends the task.
- `asyncio.to_thread` returns only after its worker thread has finished, so "task done" means "worker has run".
- `asyncio.wait` does not cancel on timeout: a hang fails A1 inside 10 s (the suite's timeout is 180 s, `pyproject.toml:190`) and leaves the task to the stop's sweep (`shutdown.py:1387-1396`).
- After the stop the task has been cancelled, so waiting on it there would raise: the wait sits inside the `try`.
- The CLI step uses only `subprocess.run` and `subprocess.TimeoutExpired` (`credential_store.py:399, 406`); the stand-in provides both, and `TimeoutExpired` stays the real class.

### 21.4 Tests and predicted counts

- The file has 7 tests and no parametrization: **7 passed** after the pairs. A1's time is unchanged within noise (its worker now returns from the environment step instead of running the CLI step).
- The suite's node count is unchanged: 54,892 collected, 54,708 passed and 184 skipped on a green gate.
- **Without the pairs, A1 passes on Windows** (as it did in five gates) and fails on Linux CI. That is the defect: the proof on Windows is the mutation row M1, not a red run.

### 21.5 Mutation rows (one campaign on the M11 candidate, the one test file, restoring between rows)

| Row | Mutant | Expected | Killer |
|---|---|---|---|
| M1 | Delete the `setenv("GH_TOKEN", ...)` line | A1 fails on Windows and Linux: `cli_calls == [["gh", "auth", "token"]]` | A1, `assert cli_calls == []` |
| M2 | Delete the `monkeypatch.setattr("probos.credential_store.subprocess", ...)` recorder, keep `GH_TOKEN` | A1 passes: an **equivalent mutant** (with `GH_TOKEN` set the CLI step cannot be reached; the recorder is a tripwire) | none |
| M3 | Apply M1, and weaken the assertion to the wrong argv (`["gh", "api"] not in cli_calls`) | A1 passes: the mutant survives, which shows that only `== []` (any call) kills M1 | reviewer property 3 |
| M4 | Apply M1, and delete the `asyncio.wait` and `assert priming in done` lines | Timing-dependent: the stop can cancel the task before the worker calls the recorder; the wait is what makes M1's kill deterministic | A1 with the wait present |

### 21.6 What this does NOT change

- Everything under `src/`, `PROGRESS.md`, `DECISIONS.md`, the ledger pair and every other test file.
- BF-919's home-emptiness assertion (A1's last line): no exemption for `.local/state/gh`.
- The counts of the AD-1337 files and the node count of the suite.

### 21.7 Deterministic checks

- After the pairs, `git diff --stat` against the commit the Builder started from lists only `tests/test_bf919_archive_isolation.py`, with 23 lines added and 0 removed.
- `tests/test_bf919_archive_isolation.py` alone: 7 passed; also under `-W error`.
- The plugin run of 21.1 on the candidate: A1 passes and no plugin log is created.
- `tests/test_ad1337_secret_masking.py`, `tests/test_ad1337_executor_seam.py`, `tests/test_ad1337_render_seam.py`, `tests/test_credential_store.py` and `tests/test_issue1419_failed_start_rollback.py`: all pass, as on `108a7fff`.
- The edited file stays ASCII; `check_architecture_principles.py --check` and `gen_ad_ledger.py --check` still pass (nothing they read changed).
- A new canonical gate on the committed head, with a receipt, then the push and CI.

### 21.8 Verified Against Codebase (2026-11-23, `108a7fff`)

```
read credential_store.py:117-123, 371-409   github spec (env GH_TOKEN, alias GITHUB_TOKEN, CLI gh auth token); _resolve: config, env, aliases, store, CLI
read execution/command_env.py:46-47          POSIX allowlist holds HOME and XDG_CONFIG_HOME, XDG_CACHE_HOME, XDG_DATA_HOME, not XDG_STATE_HOME
read finalize.py:715-781, 5896-5898          _wire_secret_masker sets runtime.secret_masking_prime_task (:745-747); worker; _prime_secret_masking catches Exception (:776-780)
read runtime.py:3722                         finalize_startup is awaited inside start()
read shutdown.py:1373-1399                   the stop's sweep cancels the registered tasks, not their threads
read tests/test_bf919_archive_isolation.py:69-104   A1: HOME and USERPROFILE redirected, a real default boot, the final home assertion at :103
read tests/test_ad1337_executor_seam.py:66-82, 504-515, 740-742, 762, 774   the SimpleNamespace(run=..., TimeoutExpired=...) scoping and the GH_TOKEN convention
read pyproject.toml:181, 190                 asyncio_mode auto; timeout 180
read ci.yml:36-40, 150-152                   the workflow sets no GH_TOKEN or GITHUB_TOKEN
git diff -U0 5d8a5eb4 108a7fff -- src | grep (subprocess|os.environ|Path.home|expanduser|getcwd|XDG_|sys.platform|to_thread|Popen|...)   only the priming (to_thread) and the masker's environment reads
```

Not verified by the Architect: the CI log itself (read by the orchestrator), the runner's `gh` version and how it writes state, and every count and timing above (predictions; 21.12 measures them).

**Same class (Windows gate versus Linux CI), the Architect's finding:** apart from the priming, S1 to S3 add no external process, file write or HOME, cwd, XDG or platform read to `src`; `ProbOSRuntime` is booted with HOME redirected by no other test (13 files redirect HOME; none boots a runtime or calls `finalize_startup`). Residuals, all folded into R23: a boot that does not wait for the priming can still be inside `gh` after its stop (the stop cancels the task, not the thread), and on Linux `gh` writes state under whatever HOME is set at that moment.

### 21.9 Updated item R23 (for the batch-2 #1820 splice)

R23, **Medium** (was Low): tests that boot a real runtime run the developer's real `gh auth token`. **Reach:** ordinary (every real boot in every test run, on every platform). **Cause:** since AD-1337 S2, `finalize._wire_secret_masker` starts `_prime_secret_masking`, whose worker calls `store.get("github", requester="secret_masking")`; with neither `GH_TOKEN` nor `GITHUB_TOKEN` set and no value in the store file, `CredentialStore._resolve` (`credential_store.py:396-407`) runs the real `["gh", "auth", "token"]` with `trusted_command_env()` (`HOME` allowed, `XDG_STATE_HOME` not). **Evidence:** PR #1846's CI, shard 1, failed A1 of BF-919's `test_bf919_archive_isolation.py` at line 103: Linux `gh` wrote `home/.local/state/gh/device-id` under the test's redirected HOME; reproduced on Windows with a plugin that imitates it (head fails, base passes, head with `GH_TOKEN` passes and never calls the CLI); five Windows canonical gates missed it. A1 is now hermetic (section 21). **What remains:** every other real-boot test still reads the developer's real token into the test process (masked, never written); on Linux `gh` writes state under whatever HOME is set; a boot can wait up to 5 s on a slow `gh`; the stop cancels the task but not its worker thread. **Smallest repair:** an autouse fixture in `tests/conftest.py` that replaces `probos.credential_store.subprocess` with a recorder raising `FileNotFoundError` (the pattern of `test_ad1337_executor_seam.py:73-82`); tests that patch it themselves keep working because their function-scoped patch is applied after the autouse one (including `test_credential_store.py:57, 100` and `test_quality_hardening.py:32`). It needs its own review and a full gate.

### 21.10 Properties for the round-6 delta reviewer

Review only the repair: `git diff 108a7fff..HEAD -- tests/test_bf919_archive_isolation.py` and the contract's section 21. Execute the checks; do not only read.

1. With the `GH_TOKEN` line removed, A1 fails on Windows: the recorder captures the CLI call, so no Linux `gh` is needed to see it.
2. While A1 runs, no real process can start through `probos.credential_store`; the stand-in keeps `TimeoutExpired` as the real exception class, so the CLI step's `except` tuple still works.
3. The CLI assertion rejects every call (`== []`), not one particular argv.
4. A1 waits for the priming before `rt.stop()`, with a bound under the suite's timeout; a timeout fails A1 and does not hang the run or cancel the task out of order.
5. BF-919's home-emptiness assertion is unchanged, with no exemption for `.local/state/gh`.
6. The only code change is in this one test file; nothing under `src/` changes, and the counts of the suite are unchanged.

### 21.11 Acceptance

- [ ] 21.4's predictions hold (7 passed), the plugin run passes with no plugin log, and the checks of 21.7 are green.
- [ ] M1 is killed by A1; M2 is the equivalent mutant (passes); M3 survives as predicted; M4's behaviour is recorded.
- [ ] One delta review, then a new canonical gate with a receipt, a fast-forward push, CI green, and the merge.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Prior art.** None reviewed: a test-isolation repair. The general rule is that a test which asserts that a boot leaves its home empty must also stop the boot from running a real external command.

### 21.12 The orchestrator's first-hand checks

The 3 pairs of this section (CI1, CI2, CI3) were applied to a scratch worktree detached at `108a7fff` by `audit\contract_tools.py apply --prefix 21.` (ASCII only). Further copies of the head ran the comparisons, so no run touched another's files. Results:

| R | Result |
|---|---|
| R1 | **The pairs.** `contract_tools.py list --prefix 21.` finds CI1, CI2 and CI3, and every SEARCH occurs exactly once on `108a7fff` (CI1 90 to 157 characters, CI2 191 to 1,060, CI3 255 to 771). One file changes by +23 -0 lines (194 to 217 lines): blob `3e60141dde8d` to `2a6c196864d5`. The blob after each pair is in the `contract_tools.py checkpoints --prefix 21.` table that the Builder brief carries (`78e57256b9dd`, `8e302391e5ca`, `2a6c196864d5`). The result parses (`ast.parse`), is ASCII, has no line over 120 characters and keeps the file's line endings (its LF and CRLF counts are equal, 217 each). |
| R2 | **The file runs.** `tests/test_bf919_archive_isolation.py` alone, through the home-guard wrapper (an empty redirected home, asserted empty first): **7 passed** in 17.2 s (cold) and 12.3 s (repeat); the head takes 12.1 s, so A1's time is unchanged within noise. Under `-W error`: 7 passed in 12.2 s. |
| R3 | **The finding's reproduction, before and after, under one invocation** (`-p ghwrite`, a pytest plugin outside the repo that makes the exact argv `["gh", "auth", "token"]` write `$HOME/.local/state/gh/device-id` and fail, and logs each such call; the file and its path are the ones the CI log names). The pure head: **1 failed, 6 passed**; A1 fails at the home assertion (`Left contains 4 more items, first extra item: ...\home\.local`) and the plugin log has one line, `gh auth token wrote ...\test_a1_a_default_config_boot_0\home\.local\state\gh\device-id`. The candidate: **7 passed**, and no plugin log exists, so the CLI was never asked. The pure head without the plugin: 7 passed, which is what five canonical gates saw. The probe proves its own premise: the same invocation fails on the head and passes on the candidate, and `-p ghwrite` stops the run if the plugin cannot be imported. |
| R4 | **The campaign** (`audit\mut_b11ci.py`; the one test file; each row applied to a copy of the candidate's file, asserting that its SEARCH occurs once, and restored byte for byte before the next). **M1** (delete the `GH_TOKEN` line): **killed** by A1 alone, `assert [['gh', 'auth', 'token']] == []`, 1 failed and 6 passed, on Windows, where `gh` writes no state under the home: the recorder is what sees the call. **M2** (delete the recorder, keep `GH_TOKEN`): 7 passed, the equivalent mutant of 21.5. **M3** (M1 and the wrong argv): 7 passed, **survived** as 21.5 predicts, which is why the assertion is `== []`. **M4** (M1 without the wait): **killed in 5 of 5 runs** with M1's message; the timing dependence 21.5 allows was not observed here, because the worker reaches the recorder within milliseconds of the boot and the stop's first phase takes about 2 s. The wait stays as the guard for a slower executor. The file's blob after the campaign equals R1's (`2a6c196864d5`). |
| R5 | **The neighbours.** The three AD-1337 files, `test_credential_store.py` and `test_issue1419_failed_start_rollback.py`: **428 passed** on the candidate (244 s) and 428 passed on the head (226 s), with the same single third-party `DeprecationWarning` (`importlib_metadata`) in both. The files that read `prompts/` or the ledger (`test_ad758_program_gate.py`, `test_ad1184_ad_ledger.py`, `test_ad685d_phantom_field_name.py`, `test_captain_invariant_exposure.py`, `test_delegation_policy.py`, `test_for_free_documentation.py`) with the BF-919 file, on the candidate with this contract in place: **55 passed, 1 skipped**, as on the head (the skip is `test_ad685d_phantom_field_name.py:190`, "prompt file not on disk yet"). |
| R6 | **The same-class claim of 21.8, enumerated.** 34 test files mention `HOME`, `USERPROFILE`, `Path.home` or `expanduser`; 302 construct or import the runtime or `finalize`; **2 are in both**: this file and `test_bf911_protected_config_write_refusal.py`, whose `.start()` calls (`:701`, `:902`) are an agent and a writer, not a runtime. The Architect counted 13 HOME-redirecting files by a narrower pattern; the conclusion is the same. `secret_masking_prime_task` has two references in all of `src` (the assignments at `finalize.py:728` and `:745`), none in `scripts`, and five lines in the tests read it (`test_ad1337_executor_seam.py:514, 548, 690, 774, 862`; `:514-515` is the same `isinstance(..., asyncio.Task)` premise that A1 now asserts); `finalize_startup` has one production caller (`runtime.py:3722`, inside `start()`, which `runtime.py:2798` defines). |
| R7 | **Static checks** on the candidate, with this section's contract and the pairs in place: `gen_ad_ledger.py --check` reports "AD/BF ledger is current" (so the ledger pair does not change), and `check_architecture_principles.py --check` passes with `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, the same as the head. |
| R8 | **The anchors of 21.8 were read, not carried over.** `credential_store.py:396-407` is the CLI step (`:399` the `subprocess.run`, `:406` the `except (FileNotFoundError, subprocess.TimeoutExpired, OSError)`); `execution/command_env.py:46-47` allow `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `XDG_DATA_HOME`, not `XDG_STATE_HOME`; `finalize.py:776-780` is `_prime_secret_masking`'s `await asyncio.to_thread(...)` and its `except Exception`; `shutdown.py:1387-1396` cancels the registered tasks and waits 5 s; `test_ad1337_executor_seam.py:73-82` is the `SimpleNamespace(run=..., TimeoutExpired=...)` autouse stand-in and `:762` the `GH_TOKEN` convention; `pyproject.toml:181` and `:190` are `asyncio_mode = "auto"` and `timeout = 180`; `ci.yml:36-40` and `:150-152` are the two `env:` blocks, and `rg -n "GH_TOKEN|GITHUB_TOKEN" .github/workflows/ci.yml` finds nothing; `test_credential_store.py:57, 100` and `test_quality_hardening.py:32` patch `probos.credential_store.subprocess.run` themselves, the consumers that 21.9's autouse fixture must keep working. |

**What the orchestrator changed in the Architect's section 21:** nothing in the three pairs' REPLACE text, the rows of 21.5 or the properties of 21.10. Four remarks on its text. (1) CI2's SEARCH is the two lines of the head; the Architect's answer read a scratch tree that already carried the orchestrator's earlier four-line edit, which the head does not have. (2) 21.4's remark about A1's time, 21.7's count of added lines and the Base sentence say what R1 and R2 measured. (3) M4's "timing-dependent" is a prediction that R4 did not observe; it stays in 21.5 as written. (4) Item R23 of 21.9 is the text for batch 2's #1820 splice; nothing in this section edits that issue.

**What these checks do not show.**
- **Linux.** This host has no WSL, Docker or bash, and the plugin of R3 models the file the CI log names, not `gh`'s source or the runner's version. That the repair cures the CI failure is shown by reading (with `GH_TOKEN` set, `CredentialStore._resolve` returns at the environment step and the CLI step is unreachable) and by R3 and R4 on Windows; the proof on the runner is the pull request's next CI run.
- The full suite on the committed head: the new canonical gate is the first full-suite run of this repair, and it also runs on Windows only.
- Nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.
