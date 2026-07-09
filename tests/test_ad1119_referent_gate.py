"""AD-1119 (#1022): Referent-Grounding Gate (guard G1) tests.

BF-287 discipline: real ``AgentRegistry()``, a real ``tmp_path`` git repo for the
git resolver, a real ``SystemConfig()`` for the flag, ``ward_room=None`` for the
absent-ward-room path. The only stubs are REAL Protocol-implementing classes
(``_RaisingResolver``) and a real minimal ``BaseAgent`` subclass — no MagicMock
at the registry / git / ward-room boundary.

``asyncio_mode = "auto"`` (pyproject) — bare ``async def test_*`` needs no marker.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
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
    with pytest.raises(Exception):
        ref.token = "x"  # type: ignore[misc]
    with pytest.raises(Exception):
        verdict.unresolved = ("x",)  # type: ignore[misc]
