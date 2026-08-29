"""AD-1284 (BF-779, #1242 findings 1 & 2) — the consensus gate must be reachable,
and where there is no gate that must be declared rather than assumed.

Two halves, matching the two findings:

* **Reachability.** ``mcp_invoke`` shipped a working propose-then-commit runtime
  path that no decomposed plan could reach: the DAG executor special-cased
  ``write_file`` by NAME, ``device.*`` escaped through the tree's only consensus
  subscriber, and ``mcp_invoke`` had neither. It proposed, quorum was evaluated,
  and nothing called ``MCPBridge.invoke``. Built, tested, unreachable.
* **Declaration.** ``requires_consensus=True`` says a vote happens; it has never
  said whether the vote authorizes the act. ``consensus_mode`` says that, and
  defaults to the unflattering answer.

The tests that matter here are the ones that cross the seam end to end
(plan node -> executor -> gated runtime path -> commit performed / not
performed). A test asserting only that ``gated_commit_for("mcp_invoke")`` is not
``None`` would have passed on the broken tree.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import fields
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.decomposer import DAGExecutor
from probos.runtime import ProbOSRuntime
from probos.types import (
    ConsensusOutcome,
    ConsensusResult,
    IntentDescriptor,
    IntentResult,
    TaskDAG,
    TaskNode,
    VerificationResult,
)


# ------------------------------------------------------------------
# Harness
# ------------------------------------------------------------------


class _FakeMcpBridge:
    def __init__(self) -> None:
        self.invocations: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(
        self, server_url: str, tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.invocations.append((server_url, tool, dict(arguments)))
        return {"ok": True}


class _FakeEventLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> str:
        self.rows.append(kwargs)
        return f"row-{len(self.rows)}"


class _GateRuntime:
    """A runtime double carrying the REAL gated-commit machinery.

    Only the broadcast+quorum step is faked; ``gated_commit_for``, the adapters
    and ``submit_*_with_consensus`` are the production functions, so driving the
    DAG executor against this object traverses the whole chain rather than a
    stub of it.
    """

    def __init__(self, outcome: ConsensusOutcome = ConsensusOutcome.APPROVED) -> None:
        self.outcome = outcome
        self.mcp_bridge = _FakeMcpBridge()
        self.event_log = _FakeEventLog()
        self.generic_calls: list[tuple[str, dict[str, Any]]] = []
        self.gated_lookups: list[str] = []
        self.write_calls: list[dict[str, Any]] = []
        self.episodes: list[dict[str, Any]] = []
        self.committed_writes: list[tuple[str, str]] = []
        self.failed_verifications: list[VerificationResult] = []

    # -- the production implementations, delegated so this module still
    # -- imports on a tree where they do not exist yet (the red-first check).
    def gated_commit_for(self, intent: str) -> Any:
        self.gated_lookups.append(intent)
        return ProbOSRuntime.gated_commit_for(self, intent)

    async def _gated_commit_write(
        self, params: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        return await ProbOSRuntime._gated_commit_write(self, params, timeout=timeout)

    async def _gated_commit_mcp_invoke(
        self, params: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        return await ProbOSRuntime._gated_commit_mcp_invoke(
            self, params, timeout=timeout
        )

    async def submit_mcp_invoke_with_consensus(
        self, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        return await ProbOSRuntime.submit_mcp_invoke_with_consensus(
            self, *args, **kwargs
        )

    async def submit_write_with_consensus(
        self, path: str, content: str, timeout: float | None = None, policy: Any = None
    ) -> dict[str, Any]:
        self.write_calls.append(
            {"path": path, "content": content, "timeout": timeout}
        )
        self.committed_writes.append((path, content))
        return {
            "intent": None,
            "results": [],
            "consensus": self._consensus(),
            "verifications": [],
            "committed": True,
        }

    # -- the faked broadcast + quorum step
    async def submit_intent_with_consensus(
        self,
        intent: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.generic_calls.append((intent, dict(params or {})))
        return {
            "intent": None,
            "results": [
                IntentResult(
                    intent_id="i1",
                    agent_id="a1",
                    success=True,
                    result={"proposal": True},
                    confidence=0.9,
                )
            ],
            "consensus": self._consensus(),
            "verifications": list(self.failed_verifications),
        }

    async def submit_intent(
        self, intent: str, params: dict[str, Any], timeout: float | None = None
    ) -> list[IntentResult]:
        self.generic_calls.append((intent, dict(params or {})))
        return [
            IntentResult(
                intent_id="i1", agent_id="a1", success=True,
                result={"ran": True}, confidence=0.9,
            )
        ]

    async def _store_mcp_invoke_episode(self, **kwargs: Any) -> None:
        self.episodes.append(kwargs)

    def _consensus(self) -> ConsensusResult:
        return ConsensusResult(proposal_id="p1", outcome=self.outcome)


def _executor(runtime: _GateRuntime) -> DAGExecutor:
    return DAGExecutor(runtime)  # type: ignore[arg-type]


def _mcp_node() -> TaskNode:
    return TaskNode(
        id="t1",
        intent="mcp_invoke",
        params={
            "server_url": "srv",
            "tool": "do_thing",
            "arguments": {"a": 1},
        },
        use_consensus=True,
    )


def _descriptor(module_path: str, holder: str, intent: str) -> IntentDescriptor:
    """The descriptor as PRODUCTION declares it -- read from the real module."""
    obj = getattr(importlib.import_module(module_path), holder)
    descriptors = obj if isinstance(obj, list) else obj.intent_descriptors
    for desc in descriptors:
        if desc.name == intent:
            return desc
    raise AssertionError(f"{holder} does not declare {intent!r}")


def _resolved_row_runtime(intent: str) -> Any:
    """A double carrying the REAL ``submit_intent_with_consensus``.

    Only its collaborators are faked, so the row and the returned dict are the
    production ones rather than a restatement of the assertion.
    """

    class _Runtime:
        def __init__(self) -> None:
            self.event_log = _FakeEventLog()
            self.red_team_agents: list[Any] = []
            self._emergent_detector = None
            self._last_shapley_values: dict[str, float] = {}
            self.config = SimpleNamespace(
                mesh=SimpleNamespace(signal_ttl_seconds=5.0),
                consensus=SimpleNamespace(verification_timeout_seconds=1.0),
            )
            self.intent_bus = SimpleNamespace(broadcast=self._broadcast)
            self.hebbian_router = SimpleNamespace(
                record_interaction=lambda **kw: None,
                get_weight=lambda *a: 0.5,
            )
            self.quorum_engine = SimpleNamespace(
                evaluate=lambda results, policy=None: ConsensusResult(
                    proposal_id="p1", outcome=ConsensusOutcome.APPROVED
                )
            )

        async def _broadcast(self, msg: Any, timeout: float | None = None):
            return [
                IntentResult(
                    intent_id=msg.id, agent_id="a1", success=True,
                    result={"ok": True}, confidence=0.9,
                )
            ]

        def _emit_event(self, *args: Any, **kwargs: Any) -> None:
            return None

        def consensus_mode_for(self, name: str) -> str:
            return ProbOSRuntime.consensus_mode_for(self, name)

        def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
            return _register_runtime()._descriptors

    assert intent  # the caller names the intent under test
    return _Runtime()


# ------------------------------------------------------------------
# The seam: plan node -> executor -> gated path -> commit
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dag_mcp_invoke_node_commits_on_approved() -> None:
    """The regression for the inert gate. FAILS before AD-1284 with 0 invokes."""
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)
    dag = TaskDAG(nodes=[_mcp_node()])

    await _executor(runtime).execute(dag)

    assert len(runtime.mcp_bridge.invocations) == 1, (
        "a decomposed mcp_invoke reached quorum and committed "
        f"{len(runtime.mcp_bridge.invocations)} times"
    )
    assert runtime.mcp_bridge.invocations[0] == ("srv", "do_thing", {"a": 1})


@pytest.mark.asyncio
async def test_dag_mcp_invoke_node_does_not_commit_on_rejected() -> None:
    """Zero invokes on REJECTED -- and the gated path must be what produced them.

    The zero alone is true on the broken tree for the wrong reason (nothing ever
    invokes), so the premise is asserted: the executor must have consulted the
    table and routed through the gate.
    """
    runtime = _GateRuntime(ConsensusOutcome.REJECTED)
    dag = TaskDAG(nodes=[_mcp_node()])

    await _executor(runtime).execute(dag)

    assert "mcp_invoke" in runtime.gated_lookups, (
        "premise: the executor never consulted the gated-commit table, so a "
        "zero invoke count proves nothing"
    )
    assert runtime.mcp_bridge.invocations == []


@pytest.mark.asyncio
async def test_dag_write_file_still_routes_to_write_gate() -> None:
    """Behaviour preservation: same method, same arguments, same timeout."""
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)
    dag = TaskDAG(nodes=[
        TaskNode(
            id="t1",
            intent="write_file",
            params={"path": "/tmp/x.txt", "content": "hello"},
            use_consensus=True,
        )
    ])

    await _executor(runtime).execute(dag)

    assert runtime.write_calls == [
        {"path": "/tmp/x.txt", "content": "hello", "timeout": 10.0}
    ]
    assert runtime.generic_calls == []


@pytest.mark.asyncio
async def test_dag_run_command_node_takes_generic_path() -> None:
    """Population D is unchanged: no gate, straight to the generic broadcast."""
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)
    dag = TaskDAG(nodes=[
        TaskNode(
            id="t1",
            intent="run_command",
            params={"command": "echo hi"},
            use_consensus=True,
        )
    ])

    await _executor(runtime).execute(dag)

    assert [i for i, _ in runtime.generic_calls] == ["run_command"]
    assert runtime.write_calls == []
    assert runtime.mcp_bridge.invocations == []


@pytest.mark.asyncio
async def test_dag_non_consensus_write_file_is_not_gated() -> None:
    """The table is consulted only when the node asked for consensus."""
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)
    dag = TaskDAG(nodes=[
        TaskNode(
            id="t1",
            intent="write_file",
            params={"path": "/tmp/x.txt", "content": "hello"},
            use_consensus=False,
        )
    ])

    await _executor(runtime).execute(dag)

    assert runtime.write_calls == []
    assert runtime.gated_lookups == []


def test_no_intent_name_is_hardcoded_in_the_executor_dispatch() -> None:
    """The special case IS the defect; it must not come back (acceptance #2).

    One name in one ``if`` is why ``mcp_invoke`` shipped dead. Pins the shape,
    not just the current behaviour.
    """
    import inspect

    source = inspect.getsource(DAGExecutor._execute_node)
    dispatch = source.split("try:", 1)[1].split("elif node.use_consensus", 1)[0]
    for name in ("write_file", "mcp_invoke", "run_command", "device_actuate"):
        assert f'"{name}"' not in dispatch and f"'{name}'" not in dispatch, (
            f"{name} is dispatched by name again; use gated_commit_for"
        )


# ------------------------------------------------------------------
# The table itself
# ------------------------------------------------------------------


@pytest.mark.parametrize("intent", ["write_file", "mcp_invoke"])
def test_gated_commit_for_returns_path_for_gated_intent(intent: str) -> None:
    assert callable(_GateRuntime().gated_commit_for(intent))


@pytest.mark.parametrize(
    "intent",
    ["run_command", "run_python", "install_package", "xlsx_update", "device_actuate"],
)
def test_gated_commit_for_returns_none_for_ungated_intent(intent: str) -> None:
    """Population D has no gate -- and neither does ``device_actuate`` here, which
    commits through its own subscriber bridge."""
    assert _GateRuntime().gated_commit_for(intent) is None


@pytest.mark.parametrize("intent", ["", "no_such_intent_at_all", None])
def test_gated_commit_for_returns_none_for_unregistered_intent(intent: Any) -> None:
    assert _GateRuntime().gated_commit_for(intent) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [None, "not-a-dict", 17, [], {}])
async def test_gated_commit_mcp_invoke_degrades_bad_arguments(arguments: Any) -> None:
    """A malformed ``arguments`` must reach the bridge as ``{}``, not as a
    TypeError raised out of the commit phase."""
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)

    await runtime._gated_commit_mcp_invoke(
        {"server_url": "srv", "tool": "t", "arguments": arguments}, timeout=1.0
    )

    assert runtime.mcp_bridge.invocations == [("srv", "t", {})]


@pytest.mark.asyncio
async def test_gated_commit_write_defaults_missing_params_to_empty() -> None:
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)

    await runtime._gated_commit_write({}, timeout=None)

    assert runtime.write_calls == [{"path": "", "content": "", "timeout": None}]


@pytest.mark.asyncio
async def test_gated_commit_write_does_not_coerce_a_malformed_value() -> None:
    """The gated path must not be the forgiving one.

    An earlier revision wrapped both params in ``str()``. Review measured the
    consequence: the ungated ``commit_write`` failed loudly on ``path=123``,
    while the gated adapter succeeded and wrote a file named ``123`` containing
    the literal ``{k: v}``. A dependency-substituted dict is an upstream
    contract violation, and routing an intent through consensus must not turn
    that into a silent write.
    """
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)

    await runtime._gated_commit_write(
        {"path": 123, "content": {"k": "v"}}, timeout=None
    )

    call = runtime.write_calls[-1]
    assert call["path"] == 123, "the gated path coerced a malformed path"
    assert call["content"] == {"k": "v"}, "the gated path coerced malformed content"


# ------------------------------------------------------------------
# Declaration
# ------------------------------------------------------------------


def test_descriptor_defaults_to_execute_then_vote() -> None:
    """The default is the UNFLATTERING one: a new consensus intent that declares
    nothing is reported as ungated rather than presumed safe."""
    assert IntentDescriptor(name="whatever").consensus_mode == "execute_then_vote"


def test_usage_hint_is_still_the_last_descriptor_field() -> None:
    assert [f.name for f in fields(IntentDescriptor)][-1] == "usage_hint"


@pytest.mark.parametrize(
    "module_path, holder, intent",
    [
        ("probos.agents.file_writer", "FileWriterAgent", "write_file"),
        ("probos.agents.mcp_consensus_proposer", "McpConsensusProposer", "mcp_invoke"),
        (
            "probos.agents.device_consensus_proposer",
            "DeviceConsensusProposer",
            "device_actuate",
        ),
        ("probos.substrate.device_node", "DEVICE_INTENT_DESCRIPTORS", "device.location"),
        ("probos.substrate.device_node", "DEVICE_INTENT_DESCRIPTORS", "device.camera"),
        ("probos.substrate.device_node", "DEVICE_INTENT_DESCRIPTORS", "device.screen"),
    ],
)
def test_propose_commit_intents_declare_it(
    module_path: str, holder: str, intent: str
) -> None:
    assert _descriptor(module_path, holder, intent).consensus_mode == "propose_commit"


def test_build_code_declares_external_gate() -> None:
    """It is not routed through consensus at all; a Captain approval gates the
    merge. Declaring that describes it -- it does not change it."""
    desc = _descriptor("probos.cognitive.builder", "BuilderAgent", "build_code")
    assert desc.consensus_mode == "external_gate"


@pytest.mark.parametrize("intent", ["run_python", "install_package"])
def test_code_runner_intents_declare_execute_then_vote(intent: str) -> None:
    """Pins the BF-763 scope guard. ``run_python`` gets no quorum gate; its
    control is the AD-1278/1280 per-execution audit record. Anyone gating it
    later has to argue with the Captain's decision here."""
    desc = _descriptor("probos.agents.code_runner", "CodeRunnerAgent", intent)
    assert desc.consensus_mode == "execute_then_vote"


def test_run_python_has_no_gated_commit_path() -> None:
    runtime = _GateRuntime()
    assert runtime.gated_commit_for("run_python") is None
    assert not hasattr(ProbOSRuntime, "submit_run_python_with_consensus")


def test_run_command_declares_execute_then_vote() -> None:
    desc = _descriptor("probos.agents.shell_command", "ShellCommandAgent", "run_command")
    assert desc.consensus_mode == "execute_then_vote"


# ------------------------------------------------------------------
# Record and warn, never refuse
# ------------------------------------------------------------------


class _RegisterRuntime:
    """Carries the real gap-register and mode resolver over a fixed descriptor set."""

    def __init__(self, descriptors: list[IntentDescriptor]) -> None:
        self._descriptors = descriptors

    def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
        return self._descriptors

    def log_consensus_gap_register(self) -> None:
        ProbOSRuntime.log_consensus_gap_register(self)

    def consensus_mode_for(self, intent: str) -> str:
        return ProbOSRuntime.consensus_mode_for(self, intent)


def _register_runtime() -> _RegisterRuntime:
    return _RegisterRuntime([
        IntentDescriptor(name="write_file", requires_consensus=True,
                         consensus_mode="propose_commit"),
        IntentDescriptor(name="mcp_invoke", requires_consensus=True,
                         consensus_mode="propose_commit"),
        IntentDescriptor(name="build_code", requires_consensus=True,
                         consensus_mode="external_gate"),
        IntentDescriptor(name="run_command", requires_consensus=True),
        IntentDescriptor(name="run_python", requires_consensus=True),
        IntentDescriptor(name="install_package", requires_consensus=True),
        IntentDescriptor(name="xlsx_update", requires_consensus=True),
        IntentDescriptor(name="read_file", requires_consensus=False),
    ])


def test_startup_warning_names_ungated_consensus_intents(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        _register_runtime().log_consensus_gap_register()

    warnings = [r for r in caplog.records if "BF-779" in r.getMessage()]
    assert len(warnings) == 1, f"expected exactly one gap register, got {len(warnings)}"
    message = warnings[0].getMessage()
    for intent in ("run_command", "run_python", "install_package", "xlsx_update"):
        assert intent in message


def test_startup_warning_omits_gated_intents(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        _register_runtime().log_consensus_gap_register()

    message = [r for r in caplog.records if "BF-779" in r.getMessage()][0].getMessage()
    ungated = message.split("no rollback: ", 1)[1].split(". Intents with", 1)[0]
    assert "write_file" not in ungated
    assert "mcp_invoke" not in ungated
    assert "build_code" not in ungated
    assert "read_file" not in ungated, "a non-consensus intent is not a gap"


def test_startup_warning_is_silent_when_every_gate_is_real(caplog) -> None:
    runtime = _RegisterRuntime([
        IntentDescriptor(name="write_file", requires_consensus=True,
                         consensus_mode="propose_commit"),
        IntentDescriptor(name="read_file", requires_consensus=False),
    ])

    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        runtime.log_consensus_gap_register()

    assert [r for r in caplog.records if "BF-779" in r.getMessage()] == []


@pytest.mark.parametrize(
    "intent, expected",
    [
        ("write_file", "propose_commit"),
        ("build_code", "external_gate"),
        ("run_command", "execute_then_vote"),
        ("not_registered_anywhere", "unknown"),
        ("", "unknown"),
    ],
)
def test_consensus_mode_for_reports_the_declared_mode(
    intent: str, expected: str
) -> None:
    assert _register_runtime().consensus_mode_for(intent) == expected


def test_consensus_mode_is_never_fabricated_for_an_unregistered_intent() -> None:
    """``"unknown"`` is the honest answer; a default here would reintroduce the
    assumption the field exists to remove."""
    assert _register_runtime().consensus_mode_for("phantom") == "unknown"


@pytest.mark.asyncio
async def test_intent_resolved_row_carries_consensus_mode() -> None:
    runtime = _resolved_row_runtime("write_file")

    result = await ProbOSRuntime.submit_intent_with_consensus(
        runtime, intent="write_file", params={}
    )

    row = [r for r in runtime.event_log.rows if r.get("event") == "intent_resolved"][0]
    assert row["data"]["consensus_mode"] == "propose_commit"
    assert result["consensus_mode"] == "propose_commit"


@pytest.mark.asyncio
async def test_intent_resolved_mode_is_unknown_for_unregistered_intent() -> None:
    runtime = _resolved_row_runtime("phantom_intent")

    result = await ProbOSRuntime.submit_intent_with_consensus(
        runtime, intent="phantom_intent", params={}
    )

    row = [r for r in runtime.event_log.rows if r.get("event") == "intent_resolved"][0]
    assert row["data"]["consensus_mode"] == "unknown"
    assert result["consensus_mode"] == "unknown"


@pytest.mark.asyncio
async def test_runtime_does_not_refuse_ungated_consensus_intent() -> None:
    """Design Principle #13(c). ``run_command`` cannot propose without acting;
    blocking it would remove a capability while defending nothing, because the
    vote it would be "enforcing" never authorized anything."""
    runtime = _resolved_row_runtime("run_command")

    result = await ProbOSRuntime.submit_intent_with_consensus(
        runtime, intent="run_command", params={"command": "echo hi"}
    )

    assert result["consensus_mode"] == "execute_then_vote"
    assert result["consensus"].outcome is ConsensusOutcome.APPROVED
    assert len(result["results"]) == 1



@pytest.mark.asyncio
async def test_a_declared_propose_commit_intent_without_a_gate_fails_the_node() -> None:
    """The inert-gate defect, generalised. Review reproduced it.

    A node whose intent DECLARES ``propose_commit`` but has no registered
    gated path used to fall through to ``submit_intent_with_consensus`` and
    report ``completed`` -- the gate consulted, no commit performed, nothing
    said. That is the same shape as `mcp_invoke` proposing into a void. A
    missing registration must surface as a broken node, not a green one.
    """
    runtime = _GateRuntime(ConsensusOutcome.APPROVED)
    runtime.gated_commit_for = lambda intent: None
    runtime.consensus_mode_for = lambda intent: "propose_commit"

    executor = _executor(runtime)
    dag = TaskDAG(nodes=[TaskNode(
        id="t1", intent="device_actuate", params={}, use_consensus=True,
    )])

    await executor.execute(dag)

    node = dag.nodes[0]
    assert node.status != "completed", (
        "a declared propose_commit intent with no gate reported success"
    )
    assert runtime.generic_calls == [], (
        "it fell back to execute-then-vote instead of failing"
    )
