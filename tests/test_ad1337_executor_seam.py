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
