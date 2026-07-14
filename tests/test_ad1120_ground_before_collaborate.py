"""AD-1120 (#1023): Ground-Before-Collaborate — cue injection + standing order.

Builds on the shipped AD-1119 gate (``referent_gate.py``, observe-only). AD-1120
turns the *observed* honest-absence cue into an *injected* one — but ONLY when
BOTH ``referent_gate_enabled`` AND ``ground_before_collaborate_enabled`` are True
(the two-flag dependency). Default-OFF the injection path is byte-identical: the
fan-out attaches no ``grounding_cue`` param and the new render hook returns "".

BF-287 discipline (mirrors ``tests/test_ad1119_referent_gate.py``): real
``AgentRegistry()``, a real ``tmp_path`` git repo (``_init_git_repo``) for the
git-available cases, a real ``SystemConfig()`` for the flags, ``_RealAgent`` (a
real ``BaseAgent`` subclass), ``SimpleNamespace`` runtimes. No MagicMock at the
registry / git / ward-room boundary. ``@_requires_git`` marks git-exercising
cases.

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

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.referent_gate import (
    AgentResolver,
    ReferentGroundingGate,
    build_default_resolvers,
)
from probos.config import SystemConfig
from probos.routers import thread_fanout
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry

_GIT = shutil.which("git")
_requires_git = pytest.mark.skipif(_GIT is None, reason="git binary not available")

# The AD-1119 honest-absence wording the injected cue reuses verbatim.
_UNRESOLVABLE = "structurally unresolvable"


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
    (root / "seed.txt").write_text("ground before collaborate seed\n", encoding="utf-8")
    _run("add", "seed.txt")
    _run("commit", "-m", "seed")
    out = _run("rev-parse", "HEAD")
    return out.stdout.decode().strip()


def _make_runtime(
    *,
    referent_gate: bool,
    ground_before_collaborate: bool,
    registry: AgentRegistry | None = None,
) -> SimpleNamespace:
    """A real-config runtime carrying only what the helper reads (BF-287)."""
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = referent_gate
    cfg.grounding.ground_before_collaborate_enabled = ground_before_collaborate
    return SimpleNamespace(
        config=cfg,
        registry=registry if registry is not None else AgentRegistry(),
        callsign_registry=None,
        ward_room=None,
    )


def _pin_repo_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pin the GATE's git resolver to the hermetic tmp repo (the PROBE in
    ``_select_central_cue`` still uses the real repo — the positive control)."""
    real_build = thread_fanout.build_default_resolvers

    def _build(**kwargs: Any) -> Any:
        kwargs["repo_root"] = tmp_path
        return real_build(**kwargs)

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _build)


# ---------------- 1. headline: cue injected for an unresolved hex central ----------------


@_requires_git
async def test_cue_injected_on_unresolved_hex_central(tmp_path, monkeypatch):
    # Both flags ON. Real tmp git repo (git available, but e77acec7 is NOT an
    # object in it) pins the gate -> e77acec7 UNRESOLVED. The probe uses the real
    # repo (positive control) -> git available -> the hex cue survives.
    _init_git_repo(tmp_path)
    _pin_repo_root(monkeypatch, tmp_path)
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=True)
    thread = SimpleNamespace(id="oracle-thread")
    cue = await thread_fanout._observe_referent_grounding(
        runtime, thread, "Investigate e77acec7 immediately."
    )
    assert cue is not None
    assert "e77acec7" in cue
    assert _UNRESOLVABLE in cue  # the AD-1119 honest-absence wording, verbatim
    assert is_capability_gap(cue) is False


# ---------------- 2. determiner / service token is NOT injected ----------------


async def test_no_cue_for_determiner_service_token():
    # BF-667 source grammar suppresses impossible service-role captures and sends
    # bare alphabetic locator tokens through the non-actionable ambiguity lane.
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=True)
    thread = SimpleNamespace(id="det-thread")
    cue = await thread_fanout._observe_referent_grounding(
        runtime, thread, "The membership is degraded."
    )
    assert cue is None
    cue2 = await thread_fanout._observe_referent_grounding(
        runtime, thread, "check node the now"
    )
    assert cue2 is None


async def test_implicit_conceptual_noun_produces_no_cue(monkeypatch):
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=True)
    thread = SimpleNamespace(id="concept-thread")

    cue = await thread_fanout._observe_referent_grounding(
        runtime,
        thread,
        "node identity distribution",
    )
    collision_cue = await thread_fanout._observe_referent_grounding(
        runtime,
        thread,
        "Node membership distribution",
    )

    assert cue is None
    assert collision_cue is None


@pytest.mark.parametrize("seed", ["node id oracle", 'node "oracle"'])
async def test_explicit_unknown_alphabetic_emits_gap_safe_cue(
    seed: str,
    monkeypatch,
):
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=True)

    cue = await thread_fanout._observe_referent_grounding(
        runtime,
        SimpleNamespace(id="explicit-thread"),
        seed,
    )

    assert cue is not None
    assert "oracle" in cue
    assert _UNRESOLVABLE in cue
    assert is_capability_gap(cue) is False


# ---------------- 3. no hex cue when git is unavailable ----------------


async def test_no_hex_cue_when_git_unavailable(monkeypatch):
    # Both flags ON. Report git unavailable by patching the resolver method to
    # always answer False (the gate's git resolver AND the availability probe use
    # the same class). e77acec7 is a fabricated hex -> UNRESOLVED, but the probe
    # reads git-unavailable -> the hex candidate is dropped (fail safe) -> None.
    async def _false(self: Any, token: str) -> bool:
        return False

    monkeypatch.setattr(thread_fanout.GitObjectResolver, "resolve", _false)
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=True)
    thread = SimpleNamespace(id="gitless-thread")
    cue = await thread_fanout._observe_referent_grounding(
        runtime, thread, "Investigate e77acec7 immediately."
    )
    assert cue is None


# ---------------- 4. no cue when the central referent resolves ----------------


async def test_no_cue_when_central_resolves(monkeypatch):
    # Both flags ON. A real registered agent whose id is hex-shaped ("beef1234")
    # so the token is BOTH extractable (hex regex) AND resolvable via the real
    # registry (by id). Drop the git resolver (agent resolver alone) so no git
    # binary is needed. Resolved -> not unresolved -> nothing to inject -> None.
    registry = AgentRegistry()
    await registry.register(_RealAgent(pool="science", agent_id="beef1234"))

    real_build = thread_fanout.build_default_resolvers

    def _build(**kwargs: Any) -> Any:
        return [AgentResolver(kwargs["registry"], kwargs["callsign_registry"])]

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _build)
    runtime = _make_runtime(
        referent_gate=True, ground_before_collaborate=True, registry=registry
    )
    thread = SimpleNamespace(id="resolved-thread")
    cue = await thread_fanout._observe_referent_grounding(
        runtime, thread, "look at beef1234 please"
    )
    assert cue is None


# ---------------- 5. default-OFF: no cue, no injection param ----------------


async def test_default_off_returns_none_no_param(monkeypatch):
    # SystemConfig() -> both flags default False. The AD-1119 first-line early
    # return fires (no gate built, no git). Returns None -> the fan-out attaches
    # no grounding_cue param -> byte-identical injection path.
    calls = {"n": 0}
    real_build = thread_fanout.build_default_resolvers

    def _spy(**kwargs: Any) -> Any:
        calls["n"] += 1
        return real_build(**kwargs)

    monkeypatch.setattr(thread_fanout, "build_default_resolvers", _spy)
    runtime = _make_runtime(referent_gate=False, ground_before_collaborate=False)
    thread = SimpleNamespace(id="off-thread")
    cue = await thread_fanout._observe_referent_grounding(
        runtime, thread, "Investigate e77acec7 immediately."
    )
    assert cue is None
    assert calls["n"] == 0  # no gate built when the flag is off


# ---------------- 6. G1 on / B2 off: observe-only (two-flag dependency) ----------------


@_requires_git
async def test_g1_on_b2_off_still_observe_only(tmp_path, monkeypatch, caplog):
    # referent_gate ON but ground_before_collaborate OFF: the AD-1119 observe log
    # STILL fires (exactly one warning for the unresolved hex), and the AD-1120
    # tail returns None (no injection). Proves the two-flag dependency and that
    # AD-1120 did not regress the AD-1119 observe path.
    _init_git_repo(tmp_path)
    _pin_repo_root(monkeypatch, tmp_path)
    runtime = _make_runtime(referent_gate=True, ground_before_collaborate=False)
    thread = SimpleNamespace(id="observe-only-thread")
    with caplog.at_level(logging.WARNING):
        cue = await thread_fanout._observe_referent_grounding(
            runtime, thread, "Investigate e77acec7 immediately."
        )
    assert cue is None
    observed = [r for r in caplog.records if "AD-1119[observe]" in r.getMessage()]
    assert len(observed) == 1
    assert "e77acec7" in observed[0].getMessage()


# ---------------- 7. render hook: emits the cue on the group param ----------------


def test_block_renders_cue_on_group_param():
    # The hook does not use `self`; call it unbound with a stand-in (mirrors the
    # AD-1082 _conversational_room_outputs_block test).
    observation = {
        "intent": "direct_message",
        "params": {"is_group_chat": True, "grounding_cue": "CUE-XYZ-TOKEN"},
    }
    out = CognitiveAgent._conversational_grounding_cue_block(
        SimpleNamespace(), observation
    )
    assert "CUE-XYZ-TOKEN" in out
    assert out.startswith("\n\n")


# ---------------- 8. render hook: empty without the group param / cue ----------------


def test_block_empty_without_param_or_group():
    me = SimpleNamespace()
    # is_group_chat falsy -> "" (byte-identical when off).
    assert (
        CognitiveAgent._conversational_grounding_cue_block(
            me, {"params": {"grounding_cue": "CUE-XYZ-TOKEN"}}
        )
        == ""
    )
    # group but no cue attached -> "".
    assert (
        CognitiveAgent._conversational_grounding_cue_block(
            me, {"params": {"is_group_chat": True}}
        )
        == ""
    )
    # group but blank cue -> "".
    assert (
        CognitiveAgent._conversational_grounding_cue_block(
            me, {"params": {"is_group_chat": True, "grounding_cue": "   "}}
        )
        == ""
    )
    # no params at all -> "".
    assert CognitiveAgent._conversational_grounding_cue_block(me, {}) == ""


# ---------------- 9. the injected cue is capability-gap-clean ----------------


async def test_cue_is_capability_gap_clean():
    # The injected cue is verdict.cues[token] = the AD-1119 honest-absence string
    # (deterministic; identical regardless of resolvers). Build it with an empty
    # resolver list (git-independent) so every token reads UNRESOLVED.
    gate = ReferentGroundingGate([])
    verdict = await gate.evaluate("Investigate e77acec7 immediately.")
    cue = verdict.cues["e77acec7"]
    assert cue
    assert is_capability_gap(cue) is False


# ---------------- 10. the ship.md standing-order section is gap-clean ----------------


def test_ship_md_section_is_capability_gap_clean():
    ship_md = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "standing_orders"
        / "ship.md"
    )
    text = ship_md.read_text(encoding="utf-8")
    heading = "## Ground Before You Collaborate"
    assert heading in text  # the always-on constitutional norm was appended
    start = text.index(heading)
    # Slice to the next section marker so the assertion targets the AD-1120 prose.
    rest = text[start + len(heading) :]
    cut_candidates = [i for i in (rest.find("\n## "), rest.find("\n<!--")) if i != -1]
    section = rest[: min(cut_candidates)] if cut_candidates else rest
    assert _UNRESOLVABLE in section
    assert is_capability_gap(section) is False


# ---------------- 11. config default OFF ----------------


def test_ground_before_collaborate_config_default_off():
    assert SystemConfig().grounding.ground_before_collaborate_enabled is False
