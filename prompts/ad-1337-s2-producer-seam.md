# AD-1337 S2 (#1560): the producer seam. Every result a tool registry returns is masked before the timing, the post-hooks, the broker and the caller see it

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21, rev1

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
  - the first store read moves off the loop with the priming;
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

### 7.13 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit any regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. No `roadmap.md` row (this is an AD).

## 8. Issue texts

None for S2. S1's section 8 covers the batch.

## 9. What this does NOT change

- S1's files (`security/secret_masking.py`, `credential_store.py`), `command_env.py`, `runtime.py`, `startup/shutdown.py`.
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
- `git diff 53696f68 -- src/probos/security/ src/probos/credential_store.py src/probos/runtime.py src/probos/startup/shutdown.py src/probos/cognitive/swe_harness/ docs/development/architecture-baseline.yaml` is empty.
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
5. Priming runs off the loop, reads `github` as the system requester `secret_masking` with no department or tier, keeps `get`'s gates, never raises into or blocks startup, and is stored on the runtime.
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
