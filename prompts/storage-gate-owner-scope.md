# Storage gate owner scope: an episode is compared only with recent episodes of the same owners

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-15
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16: the orchestrator's oracle findings F1 (MU8's killers) and F2 (line cites batch 4 moves).
**Status:** ready to build on the merge of batch 4 (#1792, #1793; head `2b7cb330`, tree `d837f4cf`). Every anchor was read on `76ce0974` (tree `94a967f3`, equal to `a02d218e`'s tree), except the lines in `config/system.yaml`, `docs/development/config-reference.md` and `DECISIONS.md`, which batch 4 moves; those were re-read on `2b7cb330`. Batch 4 changes none of the product or test files this contract edits or runs (`git diff --stat a02d218e 2b7cb330`). **Owning issue:** #1798 (BF-967, already allocated). Commits say `Refs #1798.` This contract is saved as `prompts/storage-gate-owner-scope.md`.
**Dependencies:** #1794 (merged as `aee4a43c`). S2 imports that slice's route harness, `tests/test_mention_fanout_episode_owner.py`.
**Estimated tests:** 10 new tests in a new file, `tests/test_storage_gate_owner_scope.py`: 6 `built` tests and 4 controls. No tests removed or changed.
**Size:** about 20 product lines in one file, `src/probos/cognitive/storage_gate.py`. The rest is tests and trackers.

## 1. Problem

`EpisodicMemory.store` calls the storage gate before it persists an episode (`src/probos/cognitive/episodic.py:2092-2103`). On a `REJECT` it returns `SKIPPED`.

The gate's near-duplicate check works like this:
- It joins the episode's `user_input`, `reflection` and each outcome's `result` (`storage_gate.py:109-121`).
- It splits that text into lowercase words (`similarity.py:17`).
- It compares the word set with every fingerprint in `_recent` (`:123-133`). `_recent` is one deque of size `recent_window` (`:50`).
- A fingerprint has no owner (`_record_fingerprint`, `:210-220`).

At a Jaccard score of 0.95 or more the episode is rejected. The shipped settings are in `config/system.yaml:2035-2040`: enabled, threshold 0.95, utility floor 0.2, window 50, contradiction check on. They equal `StorageGateConfig`'s defaults (`config_models/cognition.py:356-363`).

So an agent loses its own episode whenever another agent's recent episode is alike. The store's own per-agent checks are each scoped to one owner and run after the gate:
- the hourly cap (`_is_rate_limited`, `episodic.py:3298`, called at `:2145`);
- the 30-minute duplicate check (`_is_duplicate_content`, `:3324`, called at `:2150`).

The orchestrator measured this on the @-mention route with the shipped gate (issue comment): three agents give an identical reply. With 55 shared reply words all 3 episodes are stored; with 95 shared reply words only 1 is. For the group fan-out the figure is computed, not measured (issue body): its episodes differ by one callsign word each side, so about 38 shared distinct words reject.

## 2. Solution overview

Each fingerprint carries an owner key: `frozenset(episode.agent_ids)`. `_check_near_duplicate` skips every fingerprint whose key is not equal to the incoming episode's key. Nothing else changes:
- the deque stays one deque, shared by every writer;
- the threshold, the utility check, the event payload and the config fields are the same;
- `_check_contradiction` still reads every owner's fingerprints.

Rejected designs:
- **A deque per owner.** It would reach fingerprints older than the last 50 writes, so it rejects episodes the base accepted. Its memory would also grow with the number of owner sets (D2).
- **Scoping by the first agent id**, as the store's per-agent checks do. A shared episode would reject an episode of one of its owners (D1).
- **A config flag.** The change only admits more episodes and keeps no state. A flag would add a config field to a census and to the config reference, with no reason to switch back (D6).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | **The owner key** is `frozenset(episode.agent_ids)`, compared by equality. One owner compares with that owner's fingerprints. Several owners compare with fingerprints of the same set, in any order. An ownerless episode (an empty key) compares only with ownerless ones. | Equality is the narrowest rule that keeps every owner's copy, and it is one comparison. Several owners on one episode do occur: the perception consumer passes its observers' ids (`perception/consumer.py:1108`). The first-id rule (`episodic.py:3302`, `:3328`) would let one observer's episode reject a co-observer's. A subset rule ("reject when every incoming owner already holds the match") saves at most a row an owner already holds. It also makes the empty key a subset of every key, which needs a special case for ownerless episodes. |
| D2 | **The window** stays one deque of `recent_window`, shared by every writer and filtered by owner. | Every non-empty evaluation appends exactly one fingerprint, as on the base (`storage_gate.py:73`, `:84`, `:101`). So for the same sequence of evaluations the deque holds the same episodes, and every comparison the new check makes, the base made too. The gate therefore never rejects an episode the base accepted, and a same-owner duplicate is reached exactly as before. Memory stays bounded at 50 fingerprints. `recent_count` (`:242-244`) and `snapshot` (`:246-253`) keep their meaning, and so does `test_recent_window_boundary` (`tests/test_ad610_storage_gating.py:204-217`, `recent_count == 2`). The utility check reads no fingerprint (`:135-167`), and the rate check belongs to the store (`episodic.py:3298`), so neither depends on the window. The number of writers does not matter to this choice. |
| D3 | **The contradiction check is not scoped.** Its docstring records why. | It only logs at INFO and never changes the decision (`storage_gate.py:92-107`), so it cannot cost an episode. One visible effect: alike episodes of different owners used to be rejected as near-duplicates before this check ran. They now reach it, so it can log more often (L3). |
| D4 | **Nothing is persisted or rebuilt.** The event payload is unchanged. | `_recent` is created only in `__init__` and appended only by `_record_fingerprint`. `StorageGate` is built only at `startup/cognitive_services.py:318`. `EPISODE_REJECTED` keeps its four keys (`storage_gate.py:228-233`). Its only other listings are the enum (`events.py:394`) and the persistence list (`event_persistence.py:237`). No code reads the fingerprint's shape outside the class (Absence Verified). |
| D5 | **The decision record:** the storage gate's entry in `DECISIONS.md` (`:6591-6596` on `2b7cb330`; the issue cites `:6528-6534` on `5275d008`) is left as written. Its "recent window (50 episodes) for dedup" stays true. A new entry goes directly after it. No config reference or baseline changes. | `docs/development/config-reference.md:2591-2601` (on `2b7cb330`) lists the five fields, which are unchanged. The class grows from 11 to 12 methods, under `SRP_MAX_DIRECT_METHODS = 15` (`scripts/check_architecture_principles.py:188`). |
| D6 | **No flag and no staged default.** This is inside the delegated envelope. | It is reversible (revert, no state) and backward-compatible (no config, schema or payload change). It does exactly what the issue asks. It keeps episodes the base rejected, and only those (D2). The storage gate is a quality filter. The store's security gate is separate (`episodic.py:2118-2129`) and unchanged, so no security, governance or audit control is weakened. |

## 4. Milestones and commits

The Builder is `claude-sonnet-5.5`, with at most about 150 tool calls per milestone. It runs only the focused tests named here. The orchestrator runs the broad gate. Stage only the named files; never use `git add -A`. Every SEARCH must match exactly once at its turn; if one does not, stop and report.

- **M1:** P1-1, the new test file.
  - Then run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_storage_gate_owner_scope.py -n 0 -p no:randomly -q`. Expected: 4 passed, 6 xfailed.
  - Subject: `Storage gate tests: alike episodes of different agents are each stored (expected failures until the gate change)`
  - Body: `Adds six cases that fail on the base at their own assert, marked strict expected failures until the gate change, and four controls that pass on the base. Two cases cross the store seam with the gate at its shipped settings: the group fan-out's episode shape stored directly, and the @-mention route.` Then `Refs #1798.` and the trailer.
- **M2:** P2-1 to P2-5 (`storage_gate.py`) and P2-6 (the test marker becomes a no-op).
  - Then run the section 8.2 command.
  - Subject: `Storage gate compares an episode only with recent episodes of the same owners`
  - Body: `Each fingerprint carries its owner key, the set of the episode's agent ids, and the near-duplicate check reads only fingerprints with an equal key. The window stays one deque shared by every writer, so the gate never rejects an episode the base accepted. The contradiction check still reads every owner and only logs.` Then `Refs #1798.` and the trailer.
- **M3:** P3-1 and P3-2.
  - Then run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if `git status` shows them changed.
  - Then run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q`.
  - Subject: `Trackers for the storage gate's owner-scoped near-duplicate check`
  - Body: `PROGRESS.md and DECISIONS.md entries; ledger regenerated.` Then `Refs #1798.` and the trailer.

The three subjects and bodies above contain no `AD-` or `BF-` token. They contain none of the closing words in any form, and none inside a compound word.

## 5. Behaviour table (after M2)

| Earlier fingerprint's owners | Incoming owners | Compared? |
|---|---|---|
| `["a"]` | `["a"]` | yes (same owner: a repeat is still rejected) |
| `["a"]` | `["b"]` | no (was yes) |
| `["a", "b"]` | `["b", "a"]` | yes |
| `["a", "b"]` | `["a"]` | no (was yes) |
| `[]` | `[]` | yes |
| `["a"]` | `[]` | no (was yes) |

## 6. The contract

### 6.1 M1: new test file

**P1-1** (`tests/test_storage_gate_owner_scope.py`: new file)
```python
"""The storage gate compares an episode only with recent episodes of the same owners (#1798).

``EpisodicMemory.store`` consults the write-time storage gate, whose near-duplicate check rejected an episode alike
to ANY of its last ``recent_window`` fingerprints, whoever owned them: an agent lost its own episode when another
agent's was alike. Each fingerprint now carries its owner key (the set of ``agent_ids``) and the check reads only
fingerprints with an equal key; an ownerless episode compares only with ownerless ones. The window stays one deque
shared by every writer.

Synthetic fixtures only. Until M2 the cases marked ``built`` are strict expected failures: each fails on the base at
its own assert. M2 makes ``built`` a no-op. The unmarked cases are controls that pass on the base and after.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.storage_gate import StorageGate
from probos.config_models import StorageGateConfig
from probos.events import EventType
from probos.types import AnchorFrame, Episode, EpisodeStoreOutcome
from tests.test_mention_fanout_episode_owner import (
    _CREW,
    _Bus,
    _fan_out,
    _fanout_episodes_by_owner,
    _owner,
    _runtime,
    _slot,
)

# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1798: the gate compares across owners until M2")

_ANCHOR = AnchorFrame(channel="chat", trigger_type="group_fanout", participants=["captain"])
_TEXT = "coolant loop two reads warm at the pump bearing after the morning sweep"


def _gate(**overrides: Any) -> tuple[StorageGate, list[tuple[Any, dict[str, Any]]]]:
    events: list[tuple[Any, dict[str, Any]]] = []
    config = StorageGateConfig(**{"utility_floor": 0.0, **overrides})
    gate = StorageGate(config=config, emit_event_fn=lambda event_type, data: events.append((event_type, data)))
    return gate, events


def _episode(owners: list[str], text: str = _TEXT, *, success: bool | None = None) -> Episode:
    return Episode(
        timestamp=time.time(),
        user_input=text,
        outcomes=[] if success is None else [{"success": success}],
        agent_ids=list(owners),
        anchors=_ANCHOR,
    )


# -- the gate ---------------------------------------------------------------------------------------------------


@built
def test_two_owners_word_identical_episodes_are_both_accepted() -> None:
    """MU1: one agent's episode never rejects another agent's."""
    gate, _events = _gate()
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"
    assert gate.evaluate(_episode(["agent-b"])).action == "ACCEPT"


def test_the_same_owners_identical_second_episode_is_still_rejected() -> None:
    """Control. MU2, MU8: an agent's own repeat is rejected, and the event still carries its agent_ids."""
    gate, events = _gate()
    first, repeat = _episode(["agent-a"]), _episode(["agent-a"])
    gate.evaluate(first)
    decision = gate.evaluate(repeat)
    assert (decision.action, decision.reason, decision.duplicate_of) == ("REJECT", "near_duplicate", first.id)
    assert events == [(
        EventType.EPISODE_REJECTED,
        {"episode_id": repeat.id, "agent_ids": ["agent-a"], "reason": "near_duplicate", "importance": 5},
    )]


@built
def test_an_ownerless_episode_is_not_compared_with_an_owned_one() -> None:
    """MU1, MU3, MU8: an owned episode never rejects an ownerless one."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a"]))
    assert gate.evaluate(_episode([])).action == "ACCEPT"


def test_an_ownerless_repeat_is_still_rejected() -> None:
    """Control. MU2: ownerless episodes compare with ownerless ones, as before."""
    gate, _events = _gate()
    first = _episode([])
    gate.evaluate(first)
    decision = gate.evaluate(_episode([]))
    assert (decision.action, decision.duplicate_of) == ("REJECT", first.id)


def test_the_owner_key_ignores_the_order_of_agent_ids() -> None:
    """Control. MU2, MU4, MU5, MU8: a shared episode's repeat, its owners listed in another order, is rejected."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a", "agent-b"]))
    assert gate.evaluate(_episode(["agent-b", "agent-a"])).action == "REJECT"


@built
def test_a_shared_episode_does_not_reject_one_owners_own() -> None:
    """MU1, MU5: an owner set compares only with an equal set; agent-a alone is not agent-a with agent-b."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a", "agent-b"]))
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"


def test_the_window_is_one_window_shared_by_every_owner() -> None:
    """Control. MU6: an owner's fingerprint ages out after ``recent_window`` writes by anyone, as before."""
    gate, _events = _gate(recent_window=2)
    gate.evaluate(_episode(["agent-a"]))
    gate.evaluate(_episode(["agent-b"], "forward array sweep returns nominal echoes on every band"))
    gate.evaluate(_episode(["agent-c"], "shuttle bay doors cycle within tolerance during the drill"))
    assert gate.recent_count == 2
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"


@built
def test_a_contradiction_across_owners_is_still_flagged_and_accepted(caplog: pytest.LogCaptureFixture) -> None:
    """MU1, MU7: the contradiction check still reads every owner's fingerprints; it only logs."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a"], success=True))
    with caplog.at_level(logging.INFO, logger="probos.cognitive.storage_gate"):
        decision = gate.evaluate(_episode(["agent-b"], success=False))
    assert decision.action == "ACCEPT"
    assert "Contradiction detected" in caplog.text


# -- the store seam, the gate at its shipped settings (StorageGateConfig defaults equal config/system.yaml's) ------


@pytest.fixture
async def gated_memory(tmp_path):
    memory = EpisodicMemory(db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3)
    memory.set_storage_gate(StorageGate(config=StorageGateConfig()))
    await memory.start()
    yield memory
    await memory.stop()


_TRIGGER = " ".join(f"t{i}" for i in range(1, 41))
_GROUP = {"test_alpha_slot": "TestAlpha", "test_bravo_slot": "TestBravo", "test_charlie_slot": "TestCharlie"}


def _group_episode(slot: str, callsign: str) -> Episode:
    """The group fan-out's episode, field by field (routers/thread_fanout.py), with group enrichment off."""
    return Episode(
        timestamp=time.time(),
        user_input=f"[group chat] {_TRIGGER}",
        dag_summary={},
        outcomes=[{
            "intent": "direct_message", "success": True, "response": "Acknowledged.",
            "session_type": "group", "callsign": callsign, "source": "group_chat_fanout",
        }],
        agent_ids=[slot],
        reflection=f"{callsign} said in group chat: Acknowledged.",
        source="group_chat_fanout",
        anchors=AnchorFrame(channel="chat", trigger_type="group_fanout", participants=["captain", *_GROUP.values()]),
    )


@built
async def test_three_agents_alike_group_episodes_are_each_stored(gated_memory) -> None:
    """MU1: a 40-word trigger and identical short replies; each agent's episode is stored by the real store."""
    assert len(set(_TRIGGER.split())) == 40 and len(_TRIGGER) <= 200, "premise: 40 distinct words, under the cap"
    outcomes = [await gated_memory.store(_group_episode(slot, callsign)) for slot, callsign in _GROUP.items()]
    assert outcomes == [EpisodeStoreOutcome.STORED] * 3
    stored = [ep for ep in await gated_memory.recent(k=50) if str(ep.source) == "group_chat_fanout"]
    assert sorted(ep.agent_ids[0] for ep in stored) == sorted(_GROUP)


_ALIKE_REPLY = " ".join(f"n{i}" for i in range(1, 96))


@built
async def test_mention_fanout_alike_long_replies_are_each_stored_as_their_owners(tmp_path, gated_memory) -> None:
    """MU1: the @-mention route, the real store and gate; three agents give one 95-word reply. Two agents' episodes
    differ only by the callsign, twice each, so the base stored one of the three."""
    assert len(set(_ALIKE_REPLY.split())) == 95 and len(_ALIKE_REPLY) <= 500, "premise: 95 distinct words, uncut"
    bus = _Bus(replies={_slot(callsign): _ALIKE_REPLY for callsign in _CREW})
    response = await _fan_out(_runtime(tmp_path, gated_memory, bus))
    assert [r["status"] for r in response["per_agent_replies"]] == ["", "", ""], "premise: three genuine replies"
    by_owner = await _fanout_episodes_by_owner(gated_memory)
    assert sorted(by_owner) == sorted(_owner(callsign) for callsign in _CREW)
```

### 6.2 M2: `src/probos/cognitive/storage_gate.py` and the marker

**P2-1** (`src/probos/cognitive/storage_gate.py`: `evaluate` passes the owner key)
SEARCH:
```
        dup_id = self._check_near_duplicate(content)
        if dup_id is not None:
            self._record_fingerprint(episode, content)
```
REPLACE:
```
        dup_id = self._check_near_duplicate(content, self._owners(episode))
        if dup_id is not None:
            self._record_fingerprint(episode, content)
```

**P2-2** (`src/probos/cognitive/storage_gate.py`: the owner key and the near-duplicate check's filter)
SEARCH:
```
    def _check_near_duplicate(self, content: str) -> str | None:
        """Return the duplicate episode ID when content matches recent memory."""
        if not content:
            return None

        content_words = text_to_words(content)
        for recent in self._recent:
            sim = jaccard_similarity(content_words, recent["content_words"])
```
REPLACE:
```
    @staticmethod
    def _owners(episode: Episode) -> frozenset[str]:
        """The episode's owner key: the set of its agent ids; an ownerless episode's key is empty."""
        return frozenset(episode.agent_ids)

    def _check_near_duplicate(self, content: str, owners: frozenset[str]) -> str | None:
        """Return the duplicate episode ID when content matches a recent episode of the same owners.

        BF-967 (#1798): only fingerprints whose owner key equals ``owners`` are compared, so one agent's episode
        never rejects another's, and an ownerless episode compares only with ownerless ones. The window stays one
        deque shared by every writer, so a same-owner comparison reaches exactly what it reached before.
        """
        if not content:
            return None

        content_words = text_to_words(content)
        for recent in self._recent:
            if recent["owners"] != owners:
                continue
            sim = jaccard_similarity(content_words, recent["content_words"])
```

**P2-3** (`src/probos/cognitive/storage_gate.py`: why the contradiction check is not scoped)
SEARCH:
```
        """Check for potential contradictions with recent episodes."""
        if not content:
            return None
```
REPLACE:
```
        """Check for potential contradictions with recent episodes.

        BF-967 (#1798): reads every owner's fingerprints, unlike the near-duplicate check. It only logs and never
        changes the decision, so it cannot cost an agent an episode.
        """
        if not content:
            return None
```

**P2-4** (`src/probos/cognitive/storage_gate.py`: the fingerprint carries the owner key)
SEARCH:
```
        self._recent.append({
            "id": episode.id,
            "content": content,
```
REPLACE:
```
        self._recent.append({
            "id": episode.id,
            "owners": self._owners(episode),
            "content": content,
```

**P2-5** (`src/probos/cognitive/storage_gate.py`: `recent_count` says what it counts)
SEARCH:
```
    def recent_count(self) -> int:
        """Number of episodes in the recent dedup window."""
        return len(self._recent)
```
REPLACE:
```
    def recent_count(self) -> int:
        """Number of fingerprints in the recent window, across all owners; each owner's check reads only its own."""
        return len(self._recent)
```

**P2-6** (`tests/test_storage_gate_owner_scope.py`: the marker becomes a no-op)
SEARCH:
```
# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1798: the gate compares across owners until M2")
```
REPLACE:
```
def built(func):
    """The built cases failed on the base at their own assert and pass now; the marker is a no-op."""
    return func
```

### 6.3 M3: trackers

**P3-1** (`PROGRESS.md`: entry under the title)

This anchor does not move. The wave and batch 4 also insert directly under the title, so the title line stays unique. Whichever entry is applied last sits on top.

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**The storage gate compares an episode only with recent episodes of the same owners, so an agent keeps its own episode when another agent's is alike (2026-11-15), #1798.**
- **Base.** `EpisodicMemory.store` consults a write-time storage gate. Its near-duplicate check rejected an episode alike (word Jaccard 0.95 or more) to any of the last 50 fingerprints, whoever owned them, and the store then skipped it. Agents who replied alike in one fan-out lost all but the first episode. The orchestrator measured this on the @-mention route: three identical 95-word replies stored one episode.
- **Change.** Each fingerprint carries its owner key, the set of the episode's `agent_ids`, and the check reads only fingerprints with an equal key. An agent's own repeat is still rejected. Another agent's alike episode no longer rejects it. An episode with several owners compares only with the same set, and an ownerless one only with ownerless ones. The window stays one deque of 50 shared by every writer, so a same-owner comparison reaches what it reached before and the gate never rejects an episode the base accepted. The contradiction check still reads every owner's fingerprints; it only logs. No config field, event payload or persisted state changes. `tests/test_storage_gate_owner_scope.py` adds ten cases, two of them through the real store with the shipped settings: the group fan-out's episode shape, and the @-mention route.
- **Limits.** Where agents write alike, each now keeps its own copy, so the store holds more rows. The store's per-agent hourly cap and 30-minute duplicate check, which run after the gate, still apply. The group fan-out keys its episodes by slot id and the @-mention fan-out by sovereign id, so one agent's episodes from the two routes are compared as two owners. The decisions are in DECISIONS.md; the contract is `prompts/storage-gate-owner-scope.md`.
```

**P3-2** (`DECISIONS.md`: entry directly after the storage gate's own entry)

This anchor does not move: no prompt outside `prompts/archive/` searches these lines (Absence Verified 6).

SEARCH:
```markdown
**Status:** Implemented

### BF-245: NATS Test Isolation Strategy (2026-04-27)
```
REPLACE:
```markdown
**Status:** Implemented

### The storage gate compares an episode only with recent episodes of the same owners (2026-11-15, #1798)

- *Scope.* `cognitive/storage_gate.py`: the fingerprint's owner key, the near-duplicate check's owner filter and two docstrings. One new test file, `tests/test_storage_gate_owner_scope.py`. No config, event or schema change. Contract `prompts/storage-gate-owner-scope.md`. The entry above, the gate's own, stays as written: its window of 50 for dedup is unchanged.
- *Cause.* The near-duplicate check compared an episode with the last 50 fingerprints of every writer, and a fingerprint held no owner. So an agent's episode was rejected, and not stored, when another agent's recent episode was alike. The store's own per-agent checks are scoped to one owner.
- *G1 (the owner key).* `frozenset(agent_ids)`, compared by equality. One owner compares with that owner's fingerprints; several owners with the same set, in any order; an ownerless episode with ownerless ones. Rejected: the first id only, as the store's per-agent checks use it (a shared episode would reject one of its owners' own); a subset rule (it saves only rows an owner already holds, and needs a special case for the empty key).
- *G2 (the window).* One deque of `recent_window`, shared by every writer and filtered by owner. For the same sequence of evaluations it holds the same episodes as before, and each comparison the new check makes, the old one made too, so the gate never rejects an episode the base accepted. Rejected: a deque per owner (it reaches fingerprints older than the last 50 writes, so it rejects episodes the base accepted, and its memory grows with the number of owner sets).
- *G3 (the contradiction check).* Not scoped. It only logs and never changes the decision, so it cannot cost an episode. Alike episodes of different owners now reach it instead of being rejected first, so it can log more often.
- *G4 (no flag).* The change only keeps episodes the base rejected as another owner's near-duplicate, and nothing is persisted: fingerprints live in memory and a restart clears them.
- *Residual.* Owner ids are not one scheme across writers (slot id for the group fan-out, sovereign id for the @-mention fan-out), so one agent's episodes from the two routes do not compare. Stored volume rises where agents write alike. *Reversal.* Revert M3, M2 and M1; episodes stored meanwhile stay valid.

### BF-245: NATS Test Isolation Strategy (2026-04-27)
```

The orchestrator appends a `*Mutation campaign of record.*` bullet to this entry after section 8.3.

## 7. Builder: may and may not

- **May:** apply the pairs in order; run the focused commands named in section 4; run `gen_ad_ledger.py` in M3; run `git diff --check` and `git diff --stat`; commit as section 4 says.
- **May not:**
  - edit any file not named here;
  - touch `similarity.py` or `episodic.py`;
  - change `_check_contradiction`'s logic;
  - add a config field;
  - add `skip`, `xfail` (other than M1's marker) or a retry;
  - reword a SEARCH anchor.

## 8. Gates (the orchestrator runs them)

### 8.1 Base counts, on the wave's merged head before M1

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad610_storage_gating.py tests/test_mention_fanout_episode_owner.py tests/test_ad1270e2b_cognition_models.py tests/test_ad541b_reconsolidation.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1340_s1_erasure.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```

Record each file's count. I did not run these.

### 8.2 Focused check on the built tree

Run the 8.1 command with `tests/test_storage_gate_owner_scope.py` added. Expected results:
- `tests/test_storage_gate_owner_scope.py`: 10 passed.
- Every other file: its base count, all passed.
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`: passes. `StorageGate` has 12 direct methods.

Then copy the M1 test file onto the base tree, apply P2-6 alone, and run it. Expected: the six `built` cases fail at their own assert and the four controls pass. The R0 row below covers the same check.

What each focused file covers:

| File | Why it is in the set | Expected edit |
|---|---|---|
| `tests/test_ad610_storage_gating.py` | Drives a real `StorageGate`. Every episode has `agent_ids=["agent-1"]` (`:89`), so all are one owner. Pins `recent_count == 2` (`:216`) and the event payload (`:236-244`). | none |
| `tests/test_mention_fanout_episode_owner.py` | Its helpers are imported by S2. | none |
| `tests/test_ad1270e2b_cognition_models.py` | Pins the `StorageGateConfig` fields (`:252-256`). | none (no config change) |
| `tests/test_ad541b_reconsolidation.py` | Sets `_storage_gate` to a `MagicMock` (`:699-702`, `:931`, `:965-979`). | none |
| `tests/test_ad1195_event_persistence_contract.py` | Census of event names (`:162`). | none |
| `tests/test_ad1340_s1_erasure.py` | Calls the real `init_cognitive_services` (`:1059`), which wires a real gate, then stores one episode (`:1082`). | none |
| `tests/test_ad1184_ad_ledger.py` | M3 regenerates the ledger. | none |

### 8.3 Mutation campaign (one row at a time, restored before the next; win32)

- **Selector:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_storage_gate_owner_scope.py tests/test_ad610_storage_gating.py -n 0 -p no:randomly -q`.
- **Campaign of record:** record the tree id and the sha256 of `src/probos/cognitive/storage_gate.py`, `tests/test_storage_gate_owner_scope.py` and `tests/test_ad610_storage_gating.py`. Rerun only the rows whose file differs.
- Each "original" below is a whole stripped line, exactly once in the M2 file.

| Row | Original | Mutant | Expected killers |
|---|---|---|---|
| MU1 (compare across owners) | `if recent["owners"] != owners:` | `if False:` | `two_owners_word_identical`, `ownerless_episode_is_not_compared`, `shared_episode_does_not_reject`, `contradiction_across_owners`, `three_agents_alike_group`, `mention_fanout_alike_long_replies` |
| MU2 (never reject) | `return recent["id"]` | `continue` | `same_owners_identical_second`, `ownerless_repeat_is_still_rejected`, `owner_key_ignores_the_order`; also ad610 `test_reject_near_duplicate` and `test_duplicate_threshold_configurable` |
| MU3 (ownerless compares with owned) | `if recent["owners"] != owners:` | `if owners and recent["owners"] != owners:` | `ownerless_episode_is_not_compared` |
| MU4 (order-sensitive key) | `return frozenset(episode.agent_ids)` | `return tuple(episode.agent_ids)` | `owner_key_ignores_the_order` |
| MU5 (first id only) | `return frozenset(episode.agent_ids)` | `return frozenset(episode.agent_ids[:1])` | `shared_episode_does_not_reject`, `owner_key_ignores_the_order` |
| MU6 (unbounded window) | `self._recent: deque[dict[str, Any]] = deque(maxlen=self._recent_window)` | `self._recent: deque[dict[str, Any]] = deque()` | `window_is_one_window_shared`; also ad610 `test_recent_window_boundary` |
| MU7 (contradiction scoped) | `if word_overlap < 0.3:` | `if word_overlap < 0.3 or recent["owners"] != self._owners(episode):` | `contradiction_across_owners` |
| MU8 (fingerprint ownerless) | `"owners": self._owners(episode),` | `"owners": frozenset(),` | `same_owners_identical_second`, `ownerless_episode_is_not_compared`, `owner_key_ignores_the_order`; also ad610 `test_reject_near_duplicate` and `test_duplicate_threshold_configurable` |
| R0 (base product file) | `storage_gate.py` restored from the base | -- | 6 fail (the `built` cases); the 4 controls and every ad610 case pass |

MU8 records every fingerprint under the empty key. An owned repeat no longer meets its own fingerprint, so no owned repeat is rejected, and ad610's episodes all have the one owner `agent-1` (`:89`). An ownerless episode now meets an owned episode's fingerprint.

Record each row as KILLED (by the named case, or name the case that fired), SURVIVED or INVALID. Any survivor stops the slice for Architect triage.

### 8.4 Broad gate

Once, on the committed M3 head: `scripts/run_test_gate.py --label storage-gate-owner-scope --receipt logs/gates/storage-gate-owner-scope.receipt.json`. Search cannot reach full-runtime tests that boot `init_cognitive_services`; the shipped gate is wired there (`cognitive_services.py:314-322`). By D2 such a test can only see more episodes stored, never fewer. Only a test that counted a cross-owner rejection would fail.

## 9. Diff Reviewer: properties to verify

1. The diff touches only `src/probos/cognitive/storage_gate.py`, `tests/test_storage_gate_owner_scope.py`, `PROGRESS.md`, `DECISIONS.md` and the two regenerated ledger files.
2. Every fingerprint carries `owners == frozenset(episode.agent_ids)`. `_check_near_duplicate` compares only fingerprints with an equal key. No code outside `storage_gate.py` reads `owners` or any fingerprint field.
3. Consumer `EpisodicMemory.store` (`episodic.py:2092-2116`) must accept the change unchanged: for the same sequence of `evaluate` calls the deque holds the same episodes as on the base, and the near-duplicate rejections are a subset of the base's. `StorageDecision`'s fields and the actions it reads are unchanged.
4. `_check_contradiction`'s logic is unchanged; only its docstring grew. The decision for every path other than a cross-owner near-duplicate is unchanged.
5. The `EPISODE_REJECTED` payload keys are unchanged. `StorageGateConfig`, `config/system.yaml`, the config reference and `snapshot()`'s keys are unchanged.
6. The seam cases go through the real `EpisodicMemory` and a real gate with `StorageGateConfig()` defaults. After M2, `built` is a no-op and no `skip`, `xfail` or retry remains.
7. Files are ASCII with LF line endings. Comments cite no line numbers. The tracker entries describe the diff and carry no `AD-` or `BF-` token.

## 10. Verified Against Codebase (2026-11-15, `76ce0974`, tree `94a967f3` = `a02d218e`'s tree; the `config/system.yaml`, `config-reference.md` and `DECISIONS.md` lines re-read 2026-11-16 on `2b7cb330`, tree `d837f4cf`)

```
src/probos/cognitive/storage_gate.py
  50:  self._recent: deque[dict[str, Any]] = deque(maxlen=self._recent_window)
  71-73: dup_id = self._check_near_duplicate(content) / if dup_id is not None: / self._record_fingerprint(episode, content)
  84, 101: self._record_fingerprint(episode, content)
  92-107: contradiction logged at INFO; ACCEPT returned either way
  123-130: def _check_near_duplicate(self, content: str) -> str | None: ... for recent in self._recent:
  174-176: """Check for potential contradictions with recent episodes.""" / if not content: / return None
  183: if word_overlap < 0.3:
  213-215: self._recent.append({ / "id": episode.id, / "content": content,
  228-233: EPISODE_REJECTED payload: episode_id, agent_ids, reason, importance
  242-244: def recent_count ... """Number of episodes in the recent dedup window."""
src/probos/cognitive/similarity.py:17-19  text_to_words = set(text.lower().split())
src/probos/cognitive/episodic.py
  1374-1375: MAX_EPISODES_PER_HOUR = 20; SIMILARITY_WINDOW_MINUTES = 30
  2092-2116: the gate's REJECT/MERGE -> SKIPPED; an exception admits the episode
  2145, 2150: the store's per-agent checks, after the gate
  3302, 3328: agent_id = episode.agent_ids[0]
src/probos/config_models/cognition.py:356-363  StorageGateConfig: True, 0.95, 0.2, 50, True
config/system.yaml:2035-2040  storage_gate: and the same five values
docs/development/config-reference.md:2591-2601  "## `storage_gate`" and the five fields
src/probos/startup/cognitive_services.py:314-322  the only StorageGate construction
src/probos/types.py:676, 686  agent_ids: list[str]; importance: int = 5
src/probos/perception/consumer.py:1108  agent_ids=list(agent_ids) if agent_ids else []
src/probos/routers/thread_fanout.py:1065-1067, 1103-1145  the group episode's shape; agent_ids=[reply["agent_id"]]
tests/test_mention_fanout_episode_owner.py:42-55, 58-69, 99-114, 135-188  _CREW, _slot, _owner, _Bus(replies=), _runtime, _fan_out, _fanout_episodes_by_owner
scripts/check_architecture_principles.py:187-188  SRP_MAX_BODY_LINES = 500; SRP_MAX_DIRECT_METHODS = 15
PROGRESS.md: "# ProbOS Progress" (1 line); DECISIONS.md:6591-6598  the storage gate's entry, then "### BF-245: NATS Test Isolation Strategy (2026-04-27)" (1 line)
```

## Absence Verified (2026-11-15)

Each claim below was checked by a Grep-tool search on this tree.

1. **Claim:** no test reads a fingerprint field.
   **Search:** `content_words|outcome_words|outcomes_summary|\._recent\b|recent_count` in `tests/`.
   **Found:** for this class, only `test_ad610_storage_gating.py:216`. The other `_recent` hits are other classes (ad583g, ad583f, ad580, ad980c, social_verification).
2. **Claim:** no UI code reads the gate, its fingerprints or the rejection event.
   **Search:** `StorageGate|storage_gate|_record_fingerprint|_check_near_duplicate|_check_contradiction|recent_count|EPISODE_REJECTED|episode_rejected|near_duplicate` in `ui/`.
   **Found:** nothing.
3. **Claim:** fingerprints are never persisted or rebuilt.
   **Search:** `\._recent\b` in `src/`.
   **Found:** in `storage_gate.py` only `:50`, `:129`, `:181`, `:213`, `:244`. The other hits are other classes (`bridge_alerts`, `evidence_collector`, `threshold_alerts`).
4. **Claim:** the rejection event has no consumer that reads the fingerprint.
   **Search:** `EPISODE_REJECTED|episode_rejected` in `src/`.
   **Found:** `events.py:394`, `event_persistence.py:237`, `storage_gate.py:223,228,236`, plus the separate `FEDERATION_` event.
5. **Claim:** only one test file builds a real gate directly, and no script or test scans the gate's source.
   **Searches:**
   - `StorageGate\(|set_storage_gate|StorageGateConfig\(` in `tests/` found only `test_ad610_storage_gating.py`.
   - `storage_gate` in `scripts/` found nothing.
   - `storage_gate\.py` in `tests/` found nothing.
   - `storage_gate|StorageGate|agent_ids_json` in `tests/fixtures/` found nothing.
   - `EpisodeStoreOutcome\.SKIPPED` in `tests/` found `test_ad541b` (mocked gates, or no collection), `test_ad599` (a parametrized outcome) and `test_ad610`.
6. **Claim:** no prompt outside the archive anchors on P3-2's lines.
   **Search:** `BF-245: NATS Test Isolation|AD-610: Utility-Based Storage Gating` in `prompts/`.
   **Found:** only `prompts/archive/`.

**Not reachable by search:** full-runtime tests whose boot wires the shipped gate (8.4).

**Re-checked on batch 4's head `2b7cb330` (2026-11-16).** Batch 4 changes 17 files (`git diff --stat a02d218e 2b7cb330`), none of them in `ui/` or `scripts/`. Claims 3 and 4, re-run on its `src/`, hold: the `._recent` hits are the same four files, and the other `EPISODE_REJECTED` hits are still the separate `FEDERATION_` event (`memory_security.py`, `commands_status.py`). The patterns of claims 1 and 5 find nothing in its three changed test files, and claim 6's pattern finds nothing in its new prompt.

## 11. What this does NOT change, and recorded limits

- **Not changed:** `similarity.py`, `episodic.py`, the threshold, the utility floor and score, the config fields, the event payload, the store's per-agent checks, the store's security gate, and the recall anomaly gate (#1680).
- **L1.** Owner ids are not one scheme across writers. The group fan-out stores the slot id (`thread_fanout.py:1115`). The @-mention fan-out stores the sovereign id (DECISIONS.md, #1794 entry, G2). So one agent's episodes from the two routes are two owners and do not compare. This keeps more episodes, never fewer.
- **L2.** Stored volume rises where agents write alike. Each agent's growth is still bounded by the store's hourly cap and 30-minute duplicate check, which run after the gate. An agent can now reach the hourly cap sooner, because its own alike episodes now count.
- **L3.** Alike episodes of different owners now reach the contradiction check, which can log more INFO lines. The decision is unchanged.
- **L4.** A fingerprint is still recorded for an episode the gate rejects (`:73`, `:84`) or the store later skips (`episodic.py:2145-2152`). This is unchanged.
- **L5.** An `agent_ids` element that cannot be hashed would make `frozenset` raise. The store's handler then admits the episode (`episodic.py:2111-2116`), as it does for any gate error. `agent_ids` is typed `list[str]`. No test covers this.
- **L6.** S1 stores the group fan-out's episode shape directly and does not drive the group route. That route's construction is not changed here; S2 drives the @-mention route end to end.
- **L7.** An episode the base rejected only as a cross-owner near-duplicate now reaches the utility check (`storage_gate.py:82-90`). If its utility is under the floor and its importance under 8, it is still rejected, as `below_utility_floor`. The decision's `reason`, `utility_score` and `duplicate_of`, and the event's `reason` value, differ from the base's; the payload keys do not, and the store skips the episode either way (`episodic.py:2092-2116`).

## 12. Prior art and blind spots

- **Internal: the original design scoped the check.** The design text scoped it by anchor ("same anchor_department AND same anchor_channel", `docs/development/roadmap-era-5-completed.md:5059`; "with the same anchor context", `docs/research/agent-memory-survey-absorption.md:124`), but the built gate dropped the scope. Adapted: we scope by owner, not by anchor, because fan-out episodes share a channel.
- **Internal: the store's per-agent checks** (`episodic.py:3298`, `:3324`). Their scoping is adopted. Their first-id key is rejected (D1).
- **Internal: limit L12 of #1794** (`prompts/mention-fanout-episode-owner.md:908`). Its measured configuration is adopted for S2.
- **External: Mem0** scopes memories by `user_id`/`agent_id`/`run_id`, passed at write time, and reconciles new facts only against memories in that scope. This is from a search summary, not read in source ([commonplace review](https://zby.github.io/commonplace/agent-memory-systems/reviews/mem0/), [dev.to](https://dev.to/crabtalk/mem0-what-three-memory-scopes-actually-cost-1kpc)). Adopted as the same principle: dedup inside the owner's scope.
- **`reference-projects.md`** (date used: 2026-11-15). RAGFlow and LoCoMo (2026-05-08, 180-day interval) are overdue. Considered and deferred: neither addresses write-time dedup scope.
- **Blind spots:**
  - owner-id schemes that differ across writers (L1);
  - more contradiction logs (L3);
  - episodes with several owners (D1);
  - the empty key (D1);
  - the volume of stored episodes (L2).

## 13. Acceptance criteria

- Two agents' word-identical episodes are both stored (MU1). An agent's own identical repeat is still rejected as `near_duplicate`, and `EPISODE_REJECTED` still carries `agent_ids` (MU2, MU8). Ownerless episodes compare only with ownerless ones (MU3).
- Through the real store with the shipped settings:
  - the group fan-out's shape with a 40-word trigger and identical short replies stores 3 episodes (S1);
  - the @-mention route with three identical 95-word replies stores 3 owner-keyed episodes (S2).
- `recent_count` says it counts every owner's fingerprints. `snapshot` is unchanged.
- Every mutation row is KILLED and R0 fails exactly the six `built` cases.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
