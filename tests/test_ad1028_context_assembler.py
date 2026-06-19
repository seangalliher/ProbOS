"""AD-1028: ContextAssembler seam + AttentionBid + global token budget.

Test layout:
- ``test_dm_golden_*`` / ``test_wr_golden_*`` — the byte-identity regression
  oracle. They build a minimal real ``CognitiveAgent`` (BF-287: real objects,
  not MagicMock at the agent boundary) and assert ``_build_user_message``
  reproduces the captured golden fixtures. Run GREEN against the unmodified
  push-chain (Step 0) and MUST stay green after the refactor with
  ``attention.enabled=False``.
- ``test_assemble_*`` — direct, pure unit tests for ``ContextAssembler``
  (select / order / budget / empty / pin / lazy).
- ``test_attention_config_*`` — config defaults.
- ``test_score_bid_*`` / ``test_task_scoring_*`` — the ``AttentionManager`` bid
  seam + proof the task-scoring path is unchanged.
"""
from __future__ import annotations

from pathlib import Path

from probos.cognitive.attention import (
    AttentionBid,
    AttentionManager,
    ContextAssembler,
    estimate_tokens,
)
from probos.config import AttentionConfig, MemoryConfig, SystemConfig
from probos.types import AttentionEntry
from tests.fixtures.ad1028_golden._capture_golden import (
    dm_observation,
    make_dm_agent,
    make_wr_agent,
    wr_observation,
)

_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "ad1028_golden"


def _bid(
    source: str,
    text: str,
    *,
    salience: float = 0.0,
    token_cost: int | None = None,
    zone_floor: int = 0,
    pin: bool = False,
) -> AttentionBid:
    """Build a bid whose lazy renderer returns ``text``."""
    return AttentionBid(
        source=source,
        render=(lambda _t=text: _t),
        salience=salience,
        token_cost=estimate_tokens(text) if token_cost is None else token_cost,
        zone_floor=zone_floor,
        pin=pin,
    )



# ---------------------------------------------------------------------------
# Golden byte-identity oracle (Step 0 — against the unmodified method)
# ---------------------------------------------------------------------------


async def test_dm_golden_byte_identical() -> None:
    """The DM prompt must equal the captured golden byte-for-byte."""
    expected = (_GOLDEN_DIR / "dm_golden.txt").read_text(encoding="utf-8")
    agent = make_dm_agent()
    actual = await agent._build_user_message(dm_observation())
    assert actual == expected


async def test_wr_golden_byte_identical() -> None:
    """The Ward-Room prompt must equal the captured golden byte-for-byte."""
    expected = (_GOLDEN_DIR / "wr_golden.txt").read_text(encoding="utf-8")
    agent = make_wr_agent()
    actual = await agent._build_user_message(wr_observation())
    assert actual == expected


# ---------------------------------------------------------------------------
# ContextAssembler — pure unit tests (select / order / budget / empty / pin /
# lazy)
# ---------------------------------------------------------------------------


def test_assemble_empty_returns_empty() -> None:
    assert ContextAssembler.assemble([], token_budget=1000) == []


def test_assemble_all_fit_preserves_insertion_order() -> None:
    bids = [
        _bid("a", "alpha", salience=2.0, token_cost=1, zone_floor=0),
        _bid("b", "bravo", salience=1.0, token_cost=1, zone_floor=1),
        _bid("c", "charlie", salience=0.0, token_cost=1, zone_floor=2),
    ]
    assert ContextAssembler.assemble(bids, token_budget=1000) == ["alpha", "bravo", "charlie"]


def test_assemble_orders_survivors_by_zone_floor() -> None:
    # Insertion order a, b, c but zone_floor reverses the emitted order.
    bids = [
        _bid("a", "alpha", salience=1.0, token_cost=1, zone_floor=2),
        _bid("b", "bravo", salience=1.0, token_cost=1, zone_floor=0),
        _bid("c", "charlie", salience=1.0, token_cost=1, zone_floor=1),
    ]
    assert ContextAssembler.assemble(bids, token_budget=1000) == ["bravo", "charlie", "alpha"]


def test_assemble_tiny_budget_drops_lowest_salience_not_truncation() -> None:
    # Each costs 10; budget 20 admits only the two highest-salience bids.
    # The dropped bid is the LOWEST salience ("low"), not the last-inserted.
    bids = [
        _bid("low", "LOW", salience=1.0, token_cost=10, zone_floor=0),
        _bid("high", "HIGH", salience=9.0, token_cost=10, zone_floor=1),
        _bid("mid", "MID", salience=5.0, token_cost=10, zone_floor=2),
    ]
    result = ContextAssembler.assemble(bids, token_budget=20)
    # "low" dropped; survivors emitted in zone_floor order (high then mid).
    assert result == ["HIGH", "MID"]


def test_assemble_never_exceeds_budget() -> None:
    bids = [_bid(f"b{i}", f"text-{i}", salience=float(i), token_cost=10, zone_floor=i) for i in range(10)]
    # Budget 35 admits at most 3 unpinned bids (3*10=30 <= 35, 4*10=40 > 35).
    result = ContextAssembler.assemble(bids, token_budget=35)
    assert len(result) == 3


def test_assemble_pinned_never_dropped_even_under_tiny_budget() -> None:
    pinned = _bid("pinned", "PINNED", salience=0.0, token_cost=1000, zone_floor=0, pin=True)
    unpinned = _bid("unpinned", "UNPINNED", salience=9.0, token_cost=1000, zone_floor=1)
    # Budget 0 — the pinned bid is still kept; the unpinned bid is dropped.
    result = ContextAssembler.assemble([pinned, unpinned], token_budget=0)
    assert result == ["PINNED"]


def test_assemble_dropped_bid_renderer_never_called() -> None:
    calls: list[str] = []

    def _record(tag: str) -> str:
        calls.append(tag)
        return tag

    def _raise() -> str:
        raise AssertionError("dropped bid's renderer must never be called")

    kept = AttentionBid(source="kept", render=(lambda: _record("kept")),
                        salience=9.0, token_cost=10, zone_floor=0)
    dropped = AttentionBid(source="dropped", render=_raise,
                            salience=1.0, token_cost=10, zone_floor=1)
    result = ContextAssembler.assemble([kept, dropped], token_budget=10)
    assert result == ["kept"]
    assert calls == ["kept"]


def test_estimate_tokens_empty_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_nonempty_is_positive_and_scales() -> None:
    assert estimate_tokens("a") == 1
    assert estimate_tokens("a" * 8) == 2
    assert estimate_tokens("a" * 400) == 100


# ---------------------------------------------------------------------------
# AttentionConfig — defaults
# ---------------------------------------------------------------------------


def test_attention_config_defaults_off() -> None:
    cfg = AttentionConfig()
    assert cfg.enabled is False
    assert cfg.token_budget == 120_000


def test_memory_config_nests_attention_default() -> None:
    mem = MemoryConfig()
    assert isinstance(mem.attention, AttentionConfig)
    assert mem.attention.enabled is False


def test_system_config_runs_out_of_box() -> None:
    cfg = SystemConfig()
    assert cfg.memory.attention.enabled is False
    assert cfg.memory.attention.token_budget == 120_000


# ---------------------------------------------------------------------------
# AttentionManager — bid-scoring seam + task-scoring unchanged
# ---------------------------------------------------------------------------


def test_score_bid_returns_fixed_salience_v1() -> None:
    mgr = AttentionManager()
    bid = _bid("x", "hello", salience=3.5)
    assert mgr.score_bid(bid) == 3.5


def test_score_bids_is_identity_over_fixed_priorities_v1() -> None:
    mgr = AttentionManager()
    bids = [_bid("a", "x", salience=1.0), _bid("b", "y", salience=2.0)]
    out = mgr.score_bids(bids)
    assert out is bids
    assert [b.salience for b in bids] == [1.0, 2.0]


def test_task_scoring_path_unchanged() -> None:
    # The AD-1028 bid seam must not disturb the existing task-scoring API.
    mgr = AttentionManager()
    mgr.submit(AttentionEntry(task_id="t1", intent="urgent_task", urgency=0.9))
    mgr.submit(AttentionEntry(task_id="t2", intent="low_task", urgency=0.1))
    batch = mgr.get_next_batch()
    assert [e.task_id for e in batch] == ["t1", "t2"]
    assert mgr.queue_size == 2


# ---------------------------------------------------------------------------
# _resolve_attention_budget — flag gating
# ---------------------------------------------------------------------------


class _Rt:
    """Minimal real runtime stand-in exposing a real SystemConfig."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


def test_resolve_attention_budget_disabled_is_unbounded() -> None:
    from probos.cognitive.cognitive_agent import _UNBOUNDED_ATTENTION_TOKEN_BUDGET

    agent = make_dm_agent()
    agent._runtime = None
    assert agent._resolve_attention_budget() == _UNBOUNDED_ATTENTION_TOKEN_BUDGET


def test_resolve_attention_budget_enabled_uses_config_budget() -> None:
    cfg = SystemConfig()
    cfg.memory.attention.enabled = True
    cfg.memory.attention.token_budget = 500
    agent = make_dm_agent()
    agent._runtime = _Rt(cfg)
    assert agent._resolve_attention_budget() == 500

