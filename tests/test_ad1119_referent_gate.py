"""AD-1119 (#1022): Referent-Grounding Gate (guard G1) tests.

BF-287 discipline: real ``AgentRegistry()``, a real ``tmp_path`` git repo for the
git resolver, a real ``SystemConfig()`` for the flag, ``ward_room=None`` for the
absent-ward-room path. The only stubs are REAL Protocol-implementing classes
(``_RaisingResolver``) and a real minimal ``BaseAgent`` subclass — no MagicMock
at the registry / git / ward-room boundary.

``asyncio_mode = "auto"`` (pyproject) — bare ``async def test_*`` needs no marker.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.referent_gate import (
    AgentResolver,
    GitObjectResolver,
    GroundingVerdict,
    Referent,
    ReferentGroundingGate,
    WardRoomResolver,
    build_default_resolvers,
    extract_referents,
)
from probos.config import SystemConfig
from probos.routers import thread_fanout
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry

_GIT = shutil.which("git")
_requires_git = pytest.mark.skipif(_GIT is None, reason="git binary not available")


# ---------------- BF-287 real fixtures / stubs ----------------


class _RealAgent(BaseAgent):
    """A real (non-mock) BaseAgent subclass for the registry resolver test."""

    agent_type = "oracle_service"

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class _RaisingResolver:
    """A real ReferentResolver whose ``resolve`` always raises (honest-degrade test)."""

    kind = "raising"

    async def resolve(self, token: str) -> bool:
        raise RuntimeError("resolver boom")


class _StrictResolver:
    """A strict resolver that records calls and confirms only configured tokens."""

    kind = "strict"

    def __init__(self, resolved: set[str] | None = None) -> None:
        self._resolved = set(resolved or set())
        self.calls: list[str] = []

    async def resolve(self, token: str) -> bool:
        self.calls.append(token)
        return token in self._resolved


class _StrictProcess:
    """A strict ``Popen`` fake that exits only after ``kill`` when requested."""

    def __init__(self, *, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.spawned = threading.Event()
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            raise AssertionError("wait() called before the strict fake exited")
        return self.returncode


def _init_git_repo(root: Path) -> str:
    """Init a real git repo at ``root``, commit a file, return the full HEAD sha."""

    def _run(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    _run("init")
    _run("config", "user.email", "test@probos.local")
    _run("config", "user.name", "ProbOS Test")
    _run("config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("referent gate seed\n", encoding="utf-8")
    _run("add", "seed.txt")
    _run("commit", "-m", "seed")
    out = _run("rev-parse", "HEAD")
    return out.stdout.decode().strip()


# ---------------- extraction ----------------


def test_extract_finds_hex_entity_service():
    # entity (record <tok>), then hex, then a service span — in first-seen order.
    # NOTE: "node" is BOTH an entity prefix AND a service trailing keyword, so a
    # sentence-initial "The node ..." would match the service regex ("The"); this
    # text deliberately uses "record" for the entity to demonstrate the three
    # kinds without that incidental collision.
    text = "Please check record alpha_1 and e77acec7 for the Oracle membership."
    refs = extract_referents(text)
    kinds = [(r.kind, r.token) for r in refs]
    assert kinds == [
        ("entity", "alpha_1"),
        ("hex", "e77acec7"),
        ("service", "Oracle"),
    ]


def test_extract_excludes_code_spans_and_decimals():
    # hex inside a fenced block, hex inside inline code, a plain decimal, and
    # ordinary prose are all excluded; "" -> [].
    fenced = "look here:\n```\nsha abcdef1 in a fence\n```\nand `beef1234` inline."
    assert extract_referents(fenced) == []
    assert extract_referents("the batch of 1234567 items completed") == []
    assert extract_referents("just some ordinary prose with no ids at all") == []
    assert extract_referents("") == []


def test_extract_dedupes_first_seen_and_caps():
    # Same token twice -> one Referent, first-seen wins; ordering is positional.
    refs = extract_referents("e77acec7 then again e77acec7 and node bravo_2")
    assert [(r.kind, r.token) for r in refs] == [
        ("hex", "e77acec7"),
        ("entity", "bravo_2"),
    ]


def test_extract_rejects_ordinary_verb_after_entity_prefix():
    text = (
        "node is healthy; record shows progress; entity was removed; "
        "NODE ARE stable; RECORD SHOWED results; ENTITY SHOWING activity; "
        "node has capacity; record does exist; entity will recover; "
        "node this time and record the result; node seems healthy; "
        "node appears stable; record indicates progress; record exists; "
        "entity may recover; node not found; record of changes; entity to update; "
        "node id is missing; node id was present; node id shows activity"
    )
    assert extract_referents(text) == []


def test_extract_preserves_known_valid_entity_identifiers():
    cases = {
        "node oracle_probe": [("entity", "oracle_probe", "strong")],
        "node id oracle_probe": [("entity", "oracle_probe", "strong")],
        "node oracle": [("entity", "oracle", "implicit")],
        "record alpha": [("entity", "alpha", "implicit")],
        "entity atlas": [("entity", "atlas", "implicit")],
        "record alpha_1": [("entity", "alpha_1", "strong")],
        "entity alpha-2": [("entity", "alpha-2", "strong")],
        "entity abcdef1": [("hex", "abcdef1", "strong")],
    }
    for text, expected in cases.items():
        assert [
            (ref.kind, ref.token, ref.claim_confidence)
            for ref in extract_referents(text)
        ] == expected


def test_extract_bare_conceptual_locator_is_implicit():
    refs = extract_referents("node identity distribution")

    assert [(ref.token, ref.kind, ref.claim_confidence) for ref in refs] == [
        ("identity", "entity", "implicit")
    ]


def test_extract_conceptual_matrix_is_implicit_without_bogus_service_names():
    cases = {
        "node identity distribution": "identity",
        "node membership review": "membership",
        "Node provenance analysis.": "provenance",
        "node cluster topology": "cluster",
        "node set changes": "set",
        "node health status": "health",
        "record retention policy": "retention",
        "entity relationship model": "relationship",
        "The node membership distribution": "membership",
        "Node membership distribution": "membership",
        "Service node status": "status",
    }

    for text, token in cases.items():
        refs = extract_referents(text)
        assert [(ref.token, ref.kind, ref.claim_confidence) for ref in refs] == [
            (token, "entity", "implicit")
        ]


def test_extract_strong_assertion_matrix():
    cases = {
        "check e77acec7": ("e77acec7", "hex"),
        "check node e77acec7": ("e77acec7", "hex"),
        "check node id oracle": ("oracle", "entity"),
        "check node id oracle_probe": ("oracle_probe", "entity"),
        "check node oracle_probe": ("oracle_probe", "entity"),
        "check record alpha_1": ("alpha_1", "entity"),
        "check entity alpha-2": ("alpha-2", "entity"),
        "check node alpha2": ("alpha2", "entity"),
        'check node "oracle"': ("oracle", "entity"),
        "check node 'atlas'": ("atlas", "entity"),
        'check node "ORACLE"?': ("ORACLE", "entity"),
        "check Oracle membership": ("Oracle", "service"),
        "check oracle_service telemetry": ("oracle_service", "service"),
    }

    for text, (token, kind) in cases.items():
        refs = extract_referents(text)
        assert [(ref.token, ref.kind, ref.claim_confidence) for ref in refs] == [
            (token, kind, "strong")
        ]


def test_extract_quotes_are_identifiers_but_backticks_remain_code():
    refs = extract_referents('node "oracle" and record \'atlas\'')
    assert [(ref.token, ref.claim_confidence) for ref in refs] == [
        ("oracle", "strong"),
        ("atlas", "strong"),
    ]
    excluded = (
        "node `oracle`; `node oracle`; ```\nnode oracle\n```; "
        'node "oracle; record \'atlas; entity "oracle\'; entity "two words"; '
        "node 'two words'; node id `oracle_probe`"
    )
    assert extract_referents(excluded) == []


@pytest.mark.parametrize(
    "text",
    [
        "node id `oracle_probe` for review",
        "node `oracle` for review",
        "node id ```\noracle_probe\n``` for review",
        "node ```\noracle\n``` for review",
    ],
)
async def test_extract_code_at_identifier_position_cannot_bridge_to_later_prose(
    text: str,
):
    assert extract_referents(text) == []

    verdict = await ReferentGroundingGate([]).evaluate(text)

    assert verdict.results == {}
    assert verdict.unresolved == ()
    assert verdict.ambiguous == ()
    assert verdict.cues == {}


def test_extract_code_barriers_preserve_surrounding_source_order():
    refs = extract_referents(
        "record alpha_1 then node id `oracle_probe` for review then entity beta_2"
    )

    assert [(ref.token, ref.kind) for ref in refs] == [
        ("alpha_1", "entity"),
        ("beta_2", "entity"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "node id oracle for review",
        "node\n\tid\r\n oracle for review",
    ],
)
def test_extract_explicit_identifier_preserves_legitimate_whitespace(text: str):
    refs = extract_referents(text)

    assert [(ref.token, ref.kind, ref.claim_confidence) for ref in refs] == [
        ("oracle", "entity", "strong")
    ]


def test_extract_preserves_case_punctuation_and_exact_token_dedupe():
    refs = extract_referents("NODE ORACLE, then node id ORACLE. then node oracle?")

    assert [(ref.token, ref.claim_confidence) for ref in refs] == [
        ("ORACLE", "strong"),
        ("oracle", "implicit"),
    ]
    assert refs[0].raw == "node id ORACLE"


def test_extract_promotes_in_place_without_downgrade_and_preserves_order():
    promoted = extract_referents(
        "node oracle then e77acec7 then node id oracle then node atlas"
    )
    assert [(ref.token, ref.kind, ref.claim_confidence) for ref in promoted] == [
        ("oracle", "entity", "strong"),
        ("e77acec7", "hex", "strong"),
        ("atlas", "entity", "implicit"),
    ]
    assert promoted[0].raw == "node id oracle"

    not_downgraded = extract_referents("node id oracle then node oracle")
    assert len(not_downgraded) == 1
    assert not_downgraded[0].claim_confidence == "strong"
    assert not_downgraded[0].raw == "node id oracle"


def test_extract_cross_kind_priority_promotes_explicit_entity_in_first_position():
    refs = extract_referents(
        "Oracle membership then e77acec7 then node id Oracle"
    )

    assert [(ref.token, ref.kind, ref.claim_confidence) for ref in refs] == [
        ("Oracle", "entity", "strong"),
        ("e77acec7", "hex", "strong"),
    ]
    assert refs[0].raw == "node id Oracle"

    exact_repro = extract_referents("Oracle membership then node id Oracle")
    assert len(exact_repro) == 1
    assert exact_repro[0].kind == "entity"
    assert exact_repro[0].raw == "node id Oracle"

    quoted = extract_referents('Oracle membership then node "Oracle"')
    assert len(quoted) == 1
    assert quoted[0].kind == "entity"
    assert quoted[0].raw == 'node "Oracle"'


def test_extract_priority_never_downgrades_explicit_and_keeps_hex_overlap():
    service_later = extract_referents("node id Oracle then Oracle membership")
    assert len(service_later) == 1
    assert service_later[0].kind == "entity"
    assert service_later[0].raw == "node id Oracle"

    machine_then_explicit = extract_referents(
        "node Oracle_1 then node id Oracle_1"
    )
    assert len(machine_then_explicit) == 1
    assert machine_then_explicit[0].raw == "node id Oracle_1"

    hex_overlap = extract_referents("node id e77acec7")
    assert len(hex_overlap) == 1
    assert hex_overlap[0].kind == "hex"
    assert hex_overlap[0].raw == "e77acec7"


def test_extract_cap_still_allows_later_promotion_of_admitted_token():
    tokens = [f"referent{suffix}" for suffix in "abcdefghijklmnopqrst"]
    text = " ".join(f"node {token}" for token in tokens)
    text += " node overflow node id referenta"

    refs = extract_referents(text)

    assert [ref.token for ref in refs] == tokens
    assert len(refs) == 20
    assert refs[0].claim_confidence == "strong"
    assert refs[0].raw == "node id referenta"


def test_extract_service_role_filter_preserves_genuine_service_forms():
    assert extract_referents("The node is stable") == []
    assert [
        (ref.token, ref.kind, ref.claim_confidence)
        for ref in extract_referents("Oracle membership and oracle_service telemetry")
    ] == [
        ("Oracle", "service", "strong"),
        ("oracle_service", "service", "strong"),
    ]


async def test_evaluate_unconfirmed_implicit_is_ambiguous_without_action():
    resolver = _StrictResolver()
    gate = ReferentGroundingGate([resolver])

    verdict = await gate.evaluate("node identity distribution")

    assert verdict.results == {"identity": "UNRESOLVED"}
    assert verdict.ambiguous == ("identity",)
    assert verdict.unresolved == ()
    assert verdict.cues == {}
    assert verdict.has_unresolved is False
    assert resolver.calls == ["identity"]


async def test_evaluate_known_implicit_resolves_through_existing_authority():
    first = _StrictResolver()
    second = _StrictResolver({"oracle"})
    gate = ReferentGroundingGate([first, second])

    verdict = await gate.evaluate("node oracle")

    assert verdict.results == {"oracle": "RESOLVED"}
    assert verdict.ambiguous == ()
    assert verdict.unresolved == ()
    assert verdict.cues == {}
    assert first.calls == ["oracle"]
    assert second.calls == ["oracle"]


async def test_evaluate_known_implicit_resolves_via_real_registry():
    registry = AgentRegistry()
    await registry.register(_RealAgent(pool="oracle", agent_id="oracle-agent-01"))
    gate = ReferentGroundingGate([AgentResolver(registry, None)])

    verdict = await gate.evaluate("node oracle")

    assert verdict.results == {"oracle": "RESOLVED"}
    assert verdict.ambiguous == ()
    assert verdict.unresolved == ()


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("node id oracle", "oracle"),
        ('node "oracle"', "oracle"),
        ("node oracle_probe", "oracle_probe"),
        ("check e77acec7", "e77acec7"),
        ("Oracle membership", "Oracle"),
    ],
)
async def test_evaluate_strong_unknown_is_actionable_and_gap_safe(
    text: str,
    token: str,
):
    gate = ReferentGroundingGate([_StrictResolver()])

    verdict = await gate.evaluate(text)

    assert verdict.results == {token: "UNRESOLVED"}
    assert verdict.unresolved == (token,)
    assert verdict.ambiguous == ()
    assert token in verdict.cues
    assert is_capability_gap(verdict.cues[token]) is False


async def test_evaluate_genuine_service_resolves_through_existing_pool_authority():
    registry = AgentRegistry()
    await registry.register(
        _RealAgent(pool="Oracle", agent_id="oracle-service-agent")
    )
    gate = ReferentGroundingGate([AgentResolver(registry, None)])

    verdict = await gate.evaluate("Oracle membership")

    assert verdict.results == {"Oracle": "RESOLVED"}
    assert verdict.unresolved == ()
    assert verdict.ambiguous == ()


# ---------------- resolvers (real git + real registry) ----------------


@_requires_git
async def test_git_resolver_resolves_real_object(tmp_path):
    sha = _init_git_repo(tmp_path)
    resolver = GitObjectResolver(repo_root=tmp_path)
    # Direct: full sha AND an 8-char abbreviation both resolve.
    assert await resolver.resolve(sha) is True
    assert await resolver.resolve(sha[:8]) is True
    # Through the gate: the full sha (extractable) is marked RESOLVED.
    gate = ReferentGroundingGate([resolver])
    verdict = await gate.evaluate(f"Investigate {sha} now.")
    assert verdict.results.get(sha) == "RESOLVED"
    assert sha not in verdict.unresolved
    assert verdict.has_unresolved is False


@_requires_git
async def test_git_resolver_uses_threaded_popen_not_asyncio_subprocess(
    tmp_path, monkeypatch
):
    sha = _init_git_repo(tmp_path)

    async def _forbidden_async_subprocess(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("selector loops do not support subprocess transport")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _forbidden_async_subprocess)
    resolver = GitObjectResolver(repo_root=tmp_path)
    assert await resolver.resolve(sha) is True
    assert await resolver.resolve(sha[:8]) is True


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="WindowsSelectorEventLoopPolicy is Windows-only",
)
@_requires_git
def test_git_resolver_resolves_under_real_windows_selector_policy(tmp_path):
    sha = _init_git_repo(tmp_path)
    previous_policy = asyncio.get_event_loop_policy()
    selector_policy_type = getattr(asyncio, "WindowsSelectorEventLoopPolicy")
    selector_policy = selector_policy_type()
    loop: asyncio.AbstractEventLoop | None = None

    async def _resolve_both() -> tuple[bool, bool]:
        resolver = GitObjectResolver(repo_root=tmp_path)
        return await resolver.resolve(sha), await resolver.resolve(sha[:8])

    try:
        asyncio.set_event_loop_policy(selector_policy)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        assert loop.run_until_complete(_resolve_both()) == (True, True)
    finally:
        if loop is not None:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            asyncio.set_event_loop(None)
            loop.close()
        asyncio.set_event_loop_policy(previous_policy)

    assert asyncio.get_event_loop_policy() is previous_policy


async def test_git_resolver_argv_is_shell_free_and_option_terminated(
    tmp_path, monkeypatch
):
    recorded: dict[str, Any] = {}
    process = _StrictProcess(returncode=1)
    event_loop_thread_id = threading.get_ident()

    def _popen(args: list[str], **kwargs: Any) -> _StrictProcess:
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        recorded["thread_id"] = threading.get_ident()
        return process

    monkeypatch.setattr(
        "probos.cognitive.referent_gate.subprocess.Popen",
        _popen,
    )
    resolver = GitObjectResolver(repo_root=tmp_path)
    assert await resolver.resolve("--help") is False
    assert recorded["args"] == [
        "git",
        "cat-file",
        "-e",
        "--",
        "--help^{object}",
    ]
    assert isinstance(recorded["args"], list)
    assert recorded["kwargs"] == {
        "cwd": str(tmp_path),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": False,
    }
    assert recorded["thread_id"] != event_loop_thread_id


async def test_git_resolver_timeout_kills_and_reaps(tmp_path, monkeypatch):
    process = _StrictProcess()
    monkeypatch.setattr(
        "probos.cognitive.referent_gate.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    resolver = GitObjectResolver(repo_root=tmp_path, timeout=0.01)
    assert await resolver.resolve("e77acec7") is False
    assert process.kill_calls == 1
    assert process.wait_calls == 1


async def test_git_resolver_cancellation_kills_reaps_and_reraises(
    tmp_path, monkeypatch
):
    process = _StrictProcess()

    def _popen(*args: Any, **kwargs: Any) -> _StrictProcess:
        process.spawned.set()
        return process

    monkeypatch.setattr(
        "probos.cognitive.referent_gate.subprocess.Popen",
        _popen,
    )
    resolver = GitObjectResolver(repo_root=tmp_path, timeout=30.0)
    task = asyncio.create_task(resolver.resolve("e77acec7"))
    assert await asyncio.to_thread(process.spawned.wait, 1.0) is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.kill_calls == 1
    assert process.wait_calls == 1


def test_git_resolver_loop_shutdown_cancel_all_is_bounded_and_reaps_once(
    tmp_path, monkeypatch
):
    process = _StrictProcess()
    tasks: list[asyncio.Task[bool]] = []
    runner_errors: list[BaseException] = []

    def _popen(*args: Any, **kwargs: Any) -> _StrictProcess:
        process.spawned.set()
        return process

    monkeypatch.setattr(
        "probos.cognitive.referent_gate.subprocess.Popen",
        _popen,
    )
    resolver = GitObjectResolver(repo_root=tmp_path, timeout=30.0)

    async def _leave_resolve_pending_for_runner_shutdown() -> None:
        task = asyncio.create_task(resolver.resolve("e77acec7"))
        tasks.append(task)
        deadline = asyncio.get_running_loop().time() + 1.0
        while not process.spawned.is_set():
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("strict Popen fake did not start")
            await asyncio.sleep(0.001)

    def _run_and_shutdown_loop() -> None:
        try:
            asyncio.run(_leave_resolve_pending_for_runner_shutdown())
        except BaseException as exc:
            runner_errors.append(exc)

    runner = threading.Thread(target=_run_and_shutdown_loop, daemon=True)
    runner.start()
    runner.join(timeout=3.0)

    assert runner.is_alive() is False
    assert runner_errors == []
    assert len(tasks) == 1
    assert tasks[0].cancelled() is True
    assert process.kill_calls == 1
    assert process.wait_calls == 1


async def test_agent_resolver_resolves_real_agent():
    registry = AgentRegistry()
    agent = _RealAgent(pool="science", agent_id="oracle-agent-01")
    await registry.register(agent)
    resolver = AgentResolver(registry, None)  # callsign_registry absent
    assert await resolver.resolve("oracle-agent-01") is True  # by agent id
    assert await resolver.resolve("science") is True  # by pool
    assert await resolver.resolve("nonexistent-token") is False
    # Through the gate (the pool name "science" is not hex/entity/service, so use
    # the agent id which the entity regex will not pick up either -> assert the
    # resolver path directly is the meaningful check above).


async def test_ward_room_resolver_none_returns_false():
    resolver = WardRoomResolver(None)  # runtime.ward_room is None until start()
    assert await resolver.resolve("engineering") is False


# ---------------- headline: fabricated hex is UNRESOLVED with a safe cue ----------------


@_requires_git
async def test_fabricated_hex_unresolved_with_safe_cue(tmp_path):
    # A real repo (so git is available and answers), but e77acec7 is NOT an
    # object in it; empty registry; ward_room=None -> UNRESOLVED + safe cue.
    _init_git_repo(tmp_path)
    resolvers = build_default_resolvers(
        registry=AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
        repo_root=tmp_path,
    )
    gate = ReferentGroundingGate(resolvers)
    verdict = await gate.evaluate(
        "Oracle Health Check investigation on e77acec7 please."
    )
    assert verdict.results.get("e77acec7") == "UNRESOLVED"
    assert "e77acec7" in verdict.unresolved
    assert verdict.has_unresolved is True
    cue = verdict.cues["e77acec7"]
    assert cue  # non-empty
    assert "e77acec7" in cue
    # The cue must NOT read as a decomposer capability gap (AD-981b safety).
    assert is_capability_gap(cue) is False


# ---------------- honest-degrade ----------------


async def test_raising_resolver_does_not_bubble(caplog):
    gate = ReferentGroundingGate([_RaisingResolver()])
    with caplog.at_level(logging.WARNING):
        verdict = await gate.evaluate("check e77acec7 now")
    # The gate does not raise; the referent falls through to UNRESOLVED.
    assert verdict.results.get("e77acec7") == "UNRESOLVED"
    assert "e77acec7" in verdict.unresolved
    assert any(
        "AD-1119" in r.getMessage() and "raised" in r.getMessage()
        for r in caplog.records
    )


@_requires_git
async def test_git_resolver_non_repo_returns_false(tmp_path):
    # tmp_path is NOT a git repo (no git init) -> git errors -> False, not raise.
    resolver = GitObjectResolver(repo_root=tmp_path)
    assert await resolver.resolve("e77acec7") is False
    gate = ReferentGroundingGate([resolver])
    verdict = await gate.evaluate("investigate e77acec7 urgently")
    assert verdict.results.get("e77acec7") == "UNRESOLVED"


@_requires_git
async def test_git_resolver_nonrepo_and_missing_git_degrade_false(
    tmp_path, monkeypatch, caplog
):
    resolver = GitObjectResolver(repo_root=tmp_path)
    with caplog.at_level(logging.DEBUG):
        assert await resolver.resolve("e77acec7") is False
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)

    caplog.clear()

    def _missing_git(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(
        "probos.cognitive.referent_gate.subprocess.Popen",
        _missing_git,
    )
    with caplog.at_level(logging.DEBUG):
        assert await resolver.resolve("e77acec7") is False
    assert any(
        record.levelno == logging.DEBUG and "git unavailable" in record.getMessage()
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


async def test_evaluate_empty_text_is_empty_verdict():
    gate = ReferentGroundingGate([_RaisingResolver()])
    verdict = await gate.evaluate("")
    assert isinstance(verdict, GroundingVerdict)
    assert verdict.results == {}
    assert verdict.unresolved == ()
    assert verdict.cues == {}
    assert verdict.has_unresolved is False


# ---------------- observe-only wiring (default-OFF byte-identity + flag-ON) ----------------


async def test_observe_off_is_noop(monkeypatch, caplog):
    """Default-OFF golden: no gate is built, no git runs, no AD-1119 log emitted.

    The flag-gated first-line early-return is the byte-identity guarantee.
    """
    calls = {"n": 0}
    real_build = thread_fanout.build_default_resolvers

    def _spy(**kwargs: Any):
        calls["n"] += 1
        return real_build(**kwargs)

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _spy)
    runtime = SimpleNamespace(
        config=SystemConfig(),  # grounding.referent_gate_enabled is False (default)
        registry=AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
    )
    thread = SimpleNamespace(id="t-off")
    with caplog.at_level(logging.WARNING):
        result = await thread_fanout._observe_referent_grounding(
            runtime, thread, "seed with e77acec7"
        )
    assert result is None
    assert calls["n"] == 0  # no gate built when the flag is off
    assert not any("AD-1119" in r.getMessage() for r in caplog.records)


@_requires_git
async def test_observe_on_logs_unresolved(tmp_path, monkeypatch, caplog):
    """Flag-ON: exactly one AD-1119[observe] WARNING for the unresolved token;
    the helper returns None and mutates nothing it was passed."""
    _init_git_repo(tmp_path)
    real_build = thread_fanout.build_default_resolvers

    def _build(**kwargs: Any):
        # Pin the git resolver to the hermetic tmp repo (no e77acec7 object).
        kwargs["repo_root"] = tmp_path
        return real_build(**kwargs)

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _build)
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = True
    runtime = SimpleNamespace(
        config=cfg,
        registry=AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
    )
    thread = SimpleNamespace(id="oracle-thread")
    with caplog.at_level(logging.WARNING):
        result = await thread_fanout._observe_referent_grounding(
            runtime, thread, "Investigate e77acec7 immediately."
        )
    assert result is None
    assert thread.id == "oracle-thread"  # observe-only: nothing mutated
    observed = [r for r in caplog.records if "AD-1119[observe]" in r.getMessage()]
    assert len(observed) == 1
    assert "e77acec7" in observed[0].getMessage()


async def test_observe_ambiguous_only_has_no_warning_or_central_selection(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])
    selector_calls = {"n": 0}

    async def _select(*args: Any, **kwargs: Any) -> str | None:
        selector_calls["n"] += 1
        return "identity"

    monkeypatch.setattr(thread_fanout, "_select_central_referent", _select)
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = True
    runtime = SimpleNamespace(
        config=cfg,
        registry=AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
    )
    with caplog.at_level(logging.WARNING):
        result = await thread_fanout._observe_referent_grounding(
            runtime,
            SimpleNamespace(id="ambiguous-thread"),
            "node identity distribution",
        )

    assert result is None
    assert selector_calls["n"] == 0
    assert not any("AD-1119[observe]" in r.getMessage() for r in caplog.records)


async def test_observe_strong_warning_reports_truthful_disabled_disposition(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = True
    runtime = SimpleNamespace(
        config=cfg,
        registry=AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
    )
    with caplog.at_level(logging.WARNING):
        result = await thread_fanout._observe_referent_grounding(
            runtime,
            SimpleNamespace(id="strong-thread"),
            "node id oracle",
        )

    assert result is None
    observed = [r.getMessage() for r in caplog.records if "AD-1119[observe]" in r.getMessage()]
    assert len(observed) == 1
    assert "oracle" in observed[0]
    assert "central=False" in observed[0]
    assert "ground_before_collaborate=False" in observed[0]
    assert "confab_probe=False" in observed[0]
    assert "no behavioral change" not in observed[0]


async def test_observe_on_all_resolved_emits_nothing(monkeypatch, caplog):
    """Flag-ON but every referent resolves (real registered agent) -> no WARNING."""
    registry = AgentRegistry()
    # A hex-shaped agent id so the token is BOTH extractable (hex regex) AND
    # resolvable via the real registry (by id) — proving the "all resolved -> no
    # warning" path rather than "nothing extracted".
    await registry.register(_RealAgent(pool="science", agent_id="beef1234"))

    real_build = thread_fanout.build_default_resolvers

    def _build(**kwargs: Any):
        # Drop the git resolver so this test needs no git binary; the agent
        # resolver alone resolves the token (BF-287 real registry).
        return [AgentResolver(kwargs["registry"], kwargs["callsign_registry"])]

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _build)
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = True
    runtime = SimpleNamespace(
        config=cfg,
        registry=registry,
        callsign_registry=None,
        ward_room=None,
    )
    thread = SimpleNamespace(id="resolved-thread")
    with caplog.at_level(logging.WARNING):
        result = await thread_fanout._observe_referent_grounding(
            runtime, thread, "look at beef1234 please"
        )
    assert result is None
    assert not any("AD-1119[observe]" in r.getMessage() for r in caplog.records)


# ---------------- config ----------------


def test_grounding_config_default_off():
    assert SystemConfig().grounding.referent_gate_enabled is False


def test_referent_and_verdict_are_frozen():
    ref = Referent(token="e77acec7", kind="hex", raw="e77acec7")
    verdict = GroundingVerdict(results={}, unresolved=(), cues={})
    assert ref.claim_confidence == "strong"
    assert verdict.ambiguous == ()
    with pytest.raises(FrozenInstanceError):
        ref.token = "x"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ref.claim_confidence = "implicit"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        verdict.unresolved = ("x",)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        verdict.ambiguous = ("x",)  # type: ignore[misc]
