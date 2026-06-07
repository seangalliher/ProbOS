# AD-915 — Turn-Taking Facilitator (group chat → meeting epic)

**Relevance-ranked speaking order + convergence-gated termination for ad-hoc group chats.**

| | |
|---|---|
| **Target repo** | OSS (`d:\ProbOS`) |
| **Status** | Ready to build |
| **Current highest committed AD** | **AD-914** (`4ab00335`, HEAD → main). AD-913 = `d67b3f54`. |
| **Depends on** | AD-914 (`src/probos/routers/thread_fanout.py`), AD-641c (pattern only), AD-583/AD-614 (Jaccard primitive only) |
| **Layer** | Cognitive (pure scorer) + Routers (assembly + wiring) |
| **Estimated tests** | **+18 pytest** (`tests/test_ad915_turn_taking_facilitator.py`) |

---

## Problem

AD-914's [`group_chat_fanout`](../src/probos/routers/thread_fanout.py) fans the Captain's turn to **all** crew-agent participants **in parallel, once, and stops** (thread_fanout.py:155 `replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])`). With many participants this floods: every agent replies to every Captain turn regardless of relevance, and there is no termination signal when the exchange has converged. AD-915 turns AD-914's blind all-at-once into **"the most relevant participants reply, in a sensible order, and the exchange stops when it converges."** This same sequencer is the shared ordering primitive AD-921 (meeting voice) will reuse so avatars do not talk over each other.

## Solution (verified-feasible design)

A **pure, deterministic, LLM-free** `ChatFacilitator` value-class (mirrors the AD-641c `ThreadPriorityScorer` pure/impure split) that, given per-speaker signal snapshots and the recent agent exchange, returns an **ordered, possibly-truncated, possibly-suppressed** speaker list. A thin **assembly helper** in `thread_fanout.py` builds the signal snapshots from the runtime (the I/O side, mirroring `ThreadPriorityService`). The facilitator is wired **inside** `group_chat_fanout`, between participant resolution and the `asyncio.gather`, so AD-914's persist/dispatch primitive (`_send_one`) is untouched — the facilitator decides **WHO / ORDER**, AD-914 still does the dispatch+persist (DRY).

### What is REUSED vs genuinely NEW (honest accounting)

| Capability | Reuse or New | Why |
|---|---|---|
| Per-speaker relevance ranking | **NEW** pure scorer | AD-641c `ThreadPriorityScorer` scores **threads** (`ThreadPriorityInput` = thread snapshot: `captain_involved`, `recent_post_bodies`, `participant_departments`, `last_post_at`, `endorsement_count`; scorer.py:24-95), **not which agent should speak**. Forcing it to rank speakers would be wrong-shape. AD-915 adds a NEW pure value-class that *mirrors its pattern* (frozen `Input`/`Score` dataclasses, weighted factors, no I/O). |
| Convergence detection | **Reuse PRIMITIVE only** | The AD-583 detectors are substrate-coupled: `check_cross_agent_convergence()` lives on `RecordsStore` (notebook markdown entries), and `ThreadEchoAnalyzer` (`ward_room/thread_echo.py`) reads **Ward Room** posts via `ThreadManagerProtocol.get_thread_posts_temporal` (async) and detects *pathological echo*, not healthy agreement-termination. **Neither can be pointed at `chat_thread_messages` rows as-is.** Their atomic, pure primitive — `probos.cognitive.similarity.jaccard_similarity(set, set)` + `text_to_words(str)` (similarity.py:4,17) — **is** directly reusable. The facilitator reuses exactly that (the same call `ThreadEchoAnalyzer` makes). Threshold default `0.6` follows the **AD-614** precedent (`WardRoomConfig.dm_similarity_threshold = 0.6`, config.py:3760). |
| @-mention "always included" | **Reuse** | `extract_all_leading_callsign_mentions` (crew_profile.py:868) + the module's `@(\w+)` token primitive (crew_profile.py:843); callsign→agent resolution by inverting the forward `callsign_registry.get_callsign` map over the participant set. |
| Department signal | **Reuse** | `ontology.get_agent_department(agent_type)` (ontology/service.py:159), Tier-2 fallback to `agent_type`; relevance via the same pure `jaccard_similarity`. |
| Trust signal (optional) | **Reuse** | `TrustNetwork.get_score(agent_id) -> float` (trust.py:406), injected as a `Callable | None`, neutral `0.5` default when absent. |
| Reply cap / turn-taking | **NEW config field** | `WardRoomRouter.check_and_increment_reply_cap` **does not exist** (phantom). The real cap is `WardRoomConfig.max_thread_posts` (BF-201) on the **Ward Room** substrate — wrong substrate (Captain ruling: substrate = `ChatThreadStore`). The chat-substrate truncation cap is a NEW `GroupChatConfig` field, default **off** (`0`) to preserve AD-914. `collective_tests.py::_gini` (collective_tests.py:37) is a *post-hoc fairness metric*, not a speaker-ordering primitive — it inspires the recency/anti-domination factor but is not reused. |

---

## Verified context (grep/read evidence — see footer for full grep hits)

- AD-914 fan-out loop to retarget: thread_fanout.py:103 `agent_ids = crew_agent_participants(...)`, thread_fanout.py:104 `session_history = _build_session_history(...)`, thread_fanout.py:155 `replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])`.
- AD-914 history reader (the OLDEST-N tail-slice trap is documented): thread_fanout.py:52 `prior = store.list_messages(thread_id, limit=1000, before=before)`; thread_fanout.py:53 `recent = prior[-_FANOUT_HISTORY_LIMIT:]`.
- `ChatThreadMessage` shape: `id, thread_id, author_id, role, body, created_at, metadata` (threads/__init__.py:131-147). `role ∈ {"captain","agent","system",...}`.
- `ChatThreadStore.list_messages(thread_id, *, limit, before)` returns ASC (oldest first) — **tail-slice for recency**.
- Pure Jaccard: similarity.py:4 `def jaccard_similarity(a: set[str], b: set[str]) -> float`; similarity.py:17 `def text_to_words(text: str) -> set[str]`.
- Mention parser: crew_profile.py:868 `def extract_all_leading_callsign_mentions(text) -> (list[str], str)` (lower-cased); crew_profile.py:843 `re.search(r'@(\w+)', text)`.
- Department: ontology/service.py:159 `def get_agent_department(self, agent_type: str) -> str | None`.
- Trust read: trust.py:406 `def get_score(self, agent_id: AgentID) -> float`.
- AD-641c pure scorer pattern to mirror: scorer.py:43 `class ThreadPriorityScorer` (frozen `ThreadPriorityInput`/`ThreadPriorityScore`, weighted factors, `score()` pure).
- Config anchors: config.py:3747 `class WardRoomConfig(BaseModel):`; config.py:3760 `dm_similarity_threshold: float = 0.6  # AD-614`; config.py:5147 `ward_room: WardRoomConfig = WardRoomConfig()`.
- Wiring gate (UNCHANGED): routers/threads.py:253 `if body.role == "captain":` → :260 `if thread is not None and len(crew_agent_participants(...)) >= 2:` → :261 `await group_chat_fanout(...)`.

---

## Implementation

### Section 1 — Config (`src/probos/config.py`)

Add `GroupChatConfig` immediately before `WardRoomConfig`. All defaults make AD-914 inert (cap off; convergence cannot fire below `min_messages` / `min_agents`).

**SEARCH** (config.py:3747):
```python
class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""
```
**REPLACE**:
```python
class GroupChatConfig(BaseModel):
    """AD-915: ad-hoc group-chat turn-taking facilitator.

    Defaults preserve AD-914 (all crew reply, once): the truncation cap is
    OFF (0) and the convergence gate cannot fire until a real exchange has
    accumulated (>= convergence_min_messages from >= convergence_min_agents).
    """

    max_speakers_per_turn: int = 0          # 0 = off (AD-914 all-at-once). >0 caps NON-mentioned speakers.
    convergence_enabled: bool = True
    convergence_similarity_threshold: float = 0.6   # AD-614 Jaccard precedent
    convergence_min_messages: int = 4       # min recent agent msgs before the gate can fire
    convergence_min_agents: int = 2         # min distinct agents in the recent window
    weight_mention: float = 0.40            # also a hard-include (see facilitator)
    weight_recency: float = 0.25            # anti-domination / fairness
    weight_department: float = 0.25
    weight_trust: float = 0.10


class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""
```

**SEARCH** (config.py:5147):
```python
    ward_room: WardRoomConfig = WardRoomConfig()
    visiting_officers: VisitingOfficersConfig = VisitingOfficersConfig()  # AD-701
```
**REPLACE**:
```python
    ward_room: WardRoomConfig = WardRoomConfig()
    group_chat: GroupChatConfig = GroupChatConfig()  # AD-915
    visiting_officers: VisitingOfficersConfig = VisitingOfficersConfig()  # AD-701
```

### Section 2 — New pure facilitator (`src/probos/cognitive/chat_facilitator.py`)

PURE: no runtime import, no I/O, no LLM, no event emission. Mirrors `thread_priority/scorer.py`. Full new file:

```python
"""AD-915: pure turn-taking facilitator for ad-hoc group chats.

Deterministic, side-effect-free, LLM-free. Given per-speaker signal
snapshots and the recent agent exchange, produce an ordered, possibly
truncated, possibly suppressed speaker list:

  * relevance ranking   — weighted factors (mention, recency, department, trust)
  * @-mention hard-include — an explicitly addressed agent ALWAYS speaks,
    at the front, overriding both truncation and convergence
  * truncation cap      — bounds NON-mentioned fan-out (0 = off, AD-914)
  * convergence gate     — when the recent exchange has converged (mean
    pairwise Jaccard >= threshold across >= min_agents distinct agents over
    >= min_messages recent agent turns), suppress non-mentioned speakers

This is the shared sequencer AD-921 (meeting voice) reuses to order who
speaks aloud. It reuses the AD-583/AD-614 pure primitive
``probos.cognitive.similarity.jaccard_similarity`` rather than the
substrate-coupled convergence DETECTORS (RecordsStore / Ward Room posts),
which cannot be pointed at chat_thread_messages rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from probos.cognitive.similarity import jaccard_similarity, text_to_words


@dataclass(frozen=True)
class SpeakerSignals:
    """Per-speaker snapshot. Assembled by the impure layer; scored pure."""

    agent_id: str
    mentioned: bool = False            # @-addressed in the Captain turn -> hard include
    turns_since_last_spoke: int = 9_999  # large => quiet => fairness boost
    department_relevance: float = 0.0  # jaccard(captain words, dept+type words) in [0,1]
    trust: float = 0.5                 # neutral default
    order_index: int = 0               # stable tiebreak (input participant order)


@dataclass(frozen=True)
class SpeakerScore:
    agent_id: str
    score: float
    mentioned: bool
    factors: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FacilitationResult:
    speaking_order: list[str]          # ordered agent_ids (possibly empty/truncated)
    converged: bool                    # recent exchange converged -> non-mentioned suppressed
    scores: list[SpeakerScore] = field(default_factory=list)  # full ranking (diagnostics)


class ChatFacilitator:
    """Pure facilitator. No I/O, no LLM, no runtime."""

    def __init__(
        self,
        *,
        max_speakers_per_turn: int = 0,
        convergence_enabled: bool = True,
        convergence_similarity_threshold: float = 0.6,
        convergence_min_messages: int = 4,
        convergence_min_agents: int = 2,
        weight_mention: float = 0.40,
        weight_recency: float = 0.25,
        weight_department: float = 0.25,
        weight_trust: float = 0.10,
    ) -> None:
        self._max_speakers = max(0, int(max_speakers_per_turn))
        self._conv_enabled = bool(convergence_enabled)
        self._conv_threshold = float(convergence_similarity_threshold)
        self._conv_min_messages = max(1, int(convergence_min_messages))
        self._conv_min_agents = max(2, int(convergence_min_agents))
        self._w_mention = float(weight_mention)
        self._w_recency = float(weight_recency)
        self._w_department = float(weight_department)
        self._w_trust = float(weight_trust)

    @classmethod
    def from_config(cls, config: object | None) -> "ChatFacilitator":
        """Build from a SystemConfig-like object. None / missing group_chat
        -> all defaults (zero-config boot; AD-914's minimal runtime)."""
        gc = getattr(config, "group_chat", None)
        if gc is None:
            return cls()
        return cls(
            max_speakers_per_turn=getattr(gc, "max_speakers_per_turn", 0),
            convergence_enabled=getattr(gc, "convergence_enabled", True),
            convergence_similarity_threshold=getattr(gc, "convergence_similarity_threshold", 0.6),
            convergence_min_messages=getattr(gc, "convergence_min_messages", 4),
            convergence_min_agents=getattr(gc, "convergence_min_agents", 2),
            weight_mention=getattr(gc, "weight_mention", 0.40),
            weight_recency=getattr(gc, "weight_recency", 0.25),
            weight_department=getattr(gc, "weight_department", 0.25),
            weight_trust=getattr(gc, "weight_trust", 0.10),
        )

    # ---- pure scoring ----

    def _recency_factor(self, turns_since: int) -> float:
        # 0 turns -> 0.0 (just spoke), 1 -> 0.5, 3 -> 0.75, never-spoke -> ~1.0.
        t = max(0, int(turns_since))
        return 1.0 - 1.0 / (1.0 + t)

    def rank(self, signals: list[SpeakerSignals]) -> list[SpeakerScore]:
        """Score + sort speakers descending. Deterministic; stable tiebreak
        on (-score, order_index, agent_id)."""
        scored: list[SpeakerScore] = []
        for s in signals:
            factors: dict[str, float] = {}
            total = 0.0
            if s.mentioned:
                factors["mention"] = self._w_mention
                total += self._w_mention
            rec = self._recency_factor(s.turns_since_last_spoke) * self._w_recency
            if rec > 0.0:
                factors["recency"] = rec
                total += rec
            dep = max(0.0, min(1.0, s.department_relevance)) * self._w_department
            if dep > 0.0:
                factors["department"] = dep
                total += dep
            tr = max(0.0, min(1.0, s.trust)) * self._w_trust
            if tr > 0.0:
                factors["trust"] = tr
                total += tr
            scored.append(SpeakerScore(
                agent_id=s.agent_id, score=total, mentioned=s.mentioned, factors=factors,
            ))
        order = {s.agent_id: s.order_index for s in signals}
        scored.sort(key=lambda sc: (-sc.score, order.get(sc.agent_id, 0), sc.agent_id))
        return scored

    def is_converged(self, recent_agent_messages: list[tuple[str, str]]) -> bool:
        """recent_agent_messages: list of (author_id, body), oldest->newest,
        role=="agent" only. Converged when there are >= min_messages turns
        from >= min_agents distinct agents AND the mean pairwise Jaccard of
        their bodies >= threshold. Reuses the AD-583/AD-614 pure primitive."""
        if not self._conv_enabled:
            return False
        msgs = recent_agent_messages
        if len(msgs) < self._conv_min_messages:
            return False
        if len({a for a, _ in msgs}) < self._conv_min_agents:
            return False
        word_sets = [text_to_words(b) for _, b in msgs]
        sims: list[float] = []
        for i in range(len(word_sets)):
            for j in range(i + 1, len(word_sets)):
                sims.append(jaccard_similarity(word_sets[i], word_sets[j]))
        if not sims:
            return False
        return (sum(sims) / len(sims)) >= self._conv_threshold

    def facilitate(
        self,
        signals: list[SpeakerSignals],
        recent_agent_messages: list[tuple[str, str]],
    ) -> FacilitationResult:
        """Order, truncate, and convergence-gate. Mentioned speakers are
        ALWAYS honored (front, override truncation + convergence). The cap
        bounds NON-mentioned speakers only."""
        scores = self.rank(signals)
        mentioned = [sc.agent_id for sc in scores if sc.mentioned]
        others = [sc.agent_id for sc in scores if not sc.mentioned]
        converged = self.is_converged(recent_agent_messages)
        if converged:
            return FacilitationResult(speaking_order=list(mentioned), converged=True, scores=scores)
        if self._max_speakers > 0:
            remaining = max(0, self._max_speakers - len(mentioned))
            others = others[:remaining]
        return FacilitationResult(speaking_order=mentioned + others, converged=False, scores=scores)
```

### Section 3 — Assembly helper + wiring (`src/probos/routers/thread_fanout.py`)

The impure side (mirrors `ThreadPriorityService`): build `SpeakerSignals` from the runtime, Tier-2-guarding every lookup exactly like the existing module. Single-read DRY: fetch `prior` once and reuse it for history, recency, and the convergence window.

**3a — make `_build_session_history` reuse a pre-fetched list (additive, backward-compatible).**

**SEARCH** (thread_fanout.py:48-53):
```python
def _build_session_history(
    runtime: Any, store: Any, thread_id: str, before: float
) -> list[dict[str, str]]:
```
...
```python
    prior = store.list_messages(thread_id, limit=1000, before=before)
    recent = prior[-_FANOUT_HISTORY_LIMIT:]
```
**REPLACE** (only the `def` line and the `prior =` line change; keep the docstring + everything else byte-identical):
```python
def _build_session_history(
    runtime: Any, store: Any, thread_id: str, before: float, prior: Any = None
) -> list[dict[str, str]]:
```
...
```python
    if prior is None:
        prior = store.list_messages(thread_id, limit=1000, before=before)
    recent = prior[-_FANOUT_HISTORY_LIMIT:]
```
> The 4-arg call (`tests/test_ad914_group_chat_fanout.py` imports and calls `_build_session_history` with 4 positional args) is unchanged: `prior` defaults to `None` → it does its own read exactly as before.

**3b — module imports + constant.** Add at the top of the module:
```python
from probos.cognitive.chat_facilitator import ChatFacilitator, SpeakerSignals
from probos.crew_profile import extract_all_leading_callsign_mentions
```
And a module constant near `_FANOUT_HISTORY_LIMIT`:
```python
# AD-915: recent agent turns inspected by the convergence gate.
_CONVERGENCE_WINDOW = 12
```

**3c — assembly helper.** Add a new function (impure, Tier-2-guarded):
```python
def _assemble_speaker_signals(
    runtime: Any, captain_body: str, agent_ids: list[str], prior: list[Any]
) -> list[SpeakerSignals]:
    """Build per-speaker SpeakerSignals snapshots from the runtime. Every
    lookup is Tier-2 log-and-degrade (mirrors group_chat_fanout): a missing
    registry/callsign/ontology/trust never blocks facilitation."""
    # @-mentions in the Captain turn -> hard-include set (lower-cased callsigns).
    mention_callsigns: set[str] = set()
    try:
        leading, _ = extract_all_leading_callsign_mentions(captain_body or "")
        mention_callsigns.update(leading)
        for m in re.findall(r"@(\w+)", captain_body or ""):
            mention_callsigns.add(m.lower())
    except Exception:
        logger.debug("AD-915: mention parse failed", exc_info=True)
    # turns_since_last_spoke from prior (oldest->newest). Default large = quiet.
    last_idx: dict[str, int] = {}
    for i, m in enumerate(prior):
        if getattr(m, "role", "") == "agent":
            last_idx[m.author_id] = i
    n_prior = len(prior)
    cap_words = text_to_words(captain_body or "")
    trust_lookup = None
    tn = getattr(runtime, "trust_network", None)
    if tn is not None and hasattr(tn, "get_score"):
        trust_lookup = tn.get_score
    ontology = getattr(runtime, "ontology", None)
    signals: list[SpeakerSignals] = []
    for idx, aid in enumerate(agent_ids):
        agent_type = ""
        callsign = ""
        try:
            agent = runtime.registry.get(aid)
            if agent is not None:
                agent_type = getattr(agent, "agent_type", "") or ""
                if hasattr(runtime, "callsign_registry"):
                    callsign = runtime.callsign_registry.get_callsign(agent_type) or ""
        except Exception:
            logger.debug("AD-915: identity resolve failed for %s", aid, exc_info=True)
        mentioned = bool(callsign) and callsign.lower() in mention_callsigns
        turns_since = (n_prior - last_idx[aid]) if aid in last_idx else 9_999
        dept = ""
        try:
            if ontology is not None and agent_type:
                dept = ontology.get_agent_department(agent_type) or ""
        except Exception:
            logger.debug("AD-915: department resolve failed for %s", aid, exc_info=True)
        descriptor = text_to_words(f"{dept} {agent_type}")
        dep_rel = jaccard_similarity(cap_words, descriptor)
        trust = 0.5
        if trust_lookup is not None:
            try:
                trust = float(trust_lookup(aid))
            except Exception:
                logger.debug("AD-915: trust lookup failed for %s", aid, exc_info=True)
        signals.append(SpeakerSignals(
            agent_id=aid, mentioned=mentioned, turns_since_last_spoke=turns_since,
            department_relevance=dep_rel, trust=trust, order_index=idx,
        ))
    return signals
```
> Add the imports this helper needs (`import re` if not already imported; `from probos.cognitive.similarity import jaccard_similarity, text_to_words`).

**3d — wire the facilitator into `group_chat_fanout`.**

**SEARCH** (thread_fanout.py:101-104):
```python
    store = runtime.chat_thread_store
    thread = store.get_thread(thread_id)
    if thread is None:
        return []
    agent_ids = crew_agent_participants(runtime, thread.participants)
    session_history = _build_session_history(runtime, store, thread_id, captain_msg.created_at)
```
**REPLACE**:
```python
    store = runtime.chat_thread_store
    thread = store.get_thread(thread_id)
    if thread is None:
        return []
    agent_ids = crew_agent_participants(runtime, thread.participants)
    # AD-915: single-read DRY — fetch the prior window once and reuse it for
    # history injection, recency, and the convergence gate.
    prior = store.list_messages(thread_id, limit=1000, before=captain_msg.created_at)
    session_history = _build_session_history(
        runtime, store, thread_id, captain_msg.created_at, prior=prior
    )
    # AD-915: facilitator decides WHO/ORDER; AD-914's _send_one still does the
    # dispatch+persist (DRY). Tier-2: any facilitation failure degrades to the
    # AD-914 all-at-once order so a facilitator bug never silences the crew.
    try:
        facilitator = ChatFacilitator.from_config(getattr(runtime, "config", None))
        signals = _assemble_speaker_signals(runtime, captain_body, agent_ids, prior)
        recent_agent_msgs = [
            (m.author_id, m.body) for m in prior[-_CONVERGENCE_WINDOW:] if m.role == "agent"
        ]
        result = facilitator.facilitate(signals, recent_agent_msgs)
        speaking_order = result.speaking_order
    except Exception:
        logger.warning(
            "AD-915: facilitation failed for thread=%s; falling back to AD-914 order",
            thread_id, exc_info=True,
        )
        speaking_order = list(agent_ids)
```

**SEARCH** (thread_fanout.py:155, the dispatch line):
```python
    replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])
    return list(replies)
```
**REPLACE**:
```python
    replies = await asyncio.gather(*[_send_one(a) for a in speaking_order])
    return list(replies)
```
> `_send_one` and the persistence block are **unchanged**. When `speaking_order == []` (converged, no mentions), `asyncio.gather()` returns `[]`, `group_chat_fanout` returns `[]`, the endpoint returns `{**msg.to_dict(), "per_agent_replies": []}` — the Captain message stays persisted, no agent rows are written.

---

## Tests — `tests/test_ad915_turn_taking_facilitator.py` (+18, BF-287)

**Pure facilitator (no runtime; the value-class is pure):**
1. `test_rank_orders_by_relevance` — higher department/trust/recency ⇒ earlier; assert descending order.
2. `test_mentioned_speaker_ranks_first` — `mentioned=True` sorts ahead of higher-scored non-mentioned.
3. `test_truncation_caps_non_mentioned` — `max_speakers_per_turn=2`, 5 candidates ⇒ 2 non-mentioned returned.
4. `test_truncation_off_by_default_returns_all` — cap `0` ⇒ all candidates (AD-914 invariant).
5. `test_mention_always_included_past_cap` — cap `1` + 2 mentions ⇒ both mentions present (cap bounds non-mentioned only).
6. `test_convergence_suppresses_speakers` — ≥4 high-Jaccard msgs from ≥2 agents ⇒ `converged=True`, `speaking_order==[]`.
7. `test_convergence_inert_below_min_messages` — 2 similar msgs ⇒ not converged.
8. `test_convergence_inert_single_agent` — 6 identical msgs all one author ⇒ not converged (echo ≠ cross-agent convergence).
9. `test_convergence_inert_low_similarity` — ≥4 dissimilar msgs from ≥2 agents ⇒ not converged.
10. `test_mention_overrides_convergence` — converged window + one mention ⇒ `speaking_order==[mentioned]`, `converged=True`.
11. `test_recency_fairness_prioritizes_quiet_agent` — quiet agent outranks just-spoke agent, all else equal.
12. `test_rank_deterministic_stable_tiebreak` — identical signals ⇒ stable order by `order_index` then `agent_id`.
13. `test_from_config_none_uses_defaults` — `ChatFacilitator.from_config(None)` ⇒ defaults; cap off, convergence on.

**Assembly helper (BF-287: real `ChatThreadStore` on `tmp_path`, real-but-fake registry/callsign/ontology stubs — NOT MagicMock):**
14. `test_assemble_detects_mention` — captain `"@troi status?"` ⇒ that participant `.mentioned is True`.
15. `test_assemble_recency_from_prior` — seeded prior ⇒ `turns_since_last_spoke` reflects who spoke when; never-spoke ⇒ large.
16. `test_assemble_department_relevance_and_fallback` — overlapping captain words ⇒ `department_relevance>0`; no ontology ⇒ falls back to `agent_type` descriptor, no crash; trust absent ⇒ neutral `0.5`.

**Integration in `group_chat_fanout` (BF-287: real `ChatThreadStore` + real `IntentBus(SignalManager(reap_interval=1.0))` + recording handlers, mirroring the AD-914 test harness):**
17. `test_fanout_two_agent_unchanged_ad914` — 2-agent first turn ⇒ both reply (cap off + convergence inert); guards the AD-914 "do not break" invariant.
18. `test_fanout_converged_thread_suppresses` — seed ≥4 high-Jaccard agent rows from 2 agents, then a Captain turn ⇒ `group_chat_fanout` returns `[]`, Captain msg persisted, **no new** agent rows.
19. `test_fanout_mention_in_converged_thread_only_mentioned` — converged window + `"@scout ..."` ⇒ only `scout1` dispatched + persisted.
20. `test_build_session_history_backcompat_4arg` — `_build_session_history(runtime, store, thread_id, before)` (4 args, no `prior`) returns identical history; AD-914 standalone contract preserved.

> Floor: **+18**. (20 named cases above leave headroom.) Run focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad915_turn_taking_facilitator.py -v -n 0`. Then the AD-914 regression: `... tests/test_ad914_group_chat_fanout.py -q -n 0` (must stay green). Then blast-radius: `... tests/ -k "thread or chat or fanout or intent" -q -n 0`.

---

## What this does NOT change (hard boundaries)

- **No meeting / voice / avatars / VRM / viseme** — that is AD-920/AD-921/AD-922/AD-923. AD-915 is text-only ordering.
- **No UI** — no TypeScript/React/Vitest. The HXI group-chat surface is AD-917.
- **No agent-to-agent auto-reply, no multi-round loop** — AD-915 still fans the Captain's **single** turn (just ordered/truncated/gated). Convergence is single-turn *suppression*, not a self-feeding loop. Agent-initiated chats are AD-918.
- **AD-914 dispatch/persist primitive is untouched** — `_send_one`, the `direct_message` IntentMessage shape, the `role="agent"` persistence, and the `metadata.fanout="ad914"` tag are byte-identical. The facilitator only reorders/filters the `agent_ids` list.
- **The `routers/threads.py` endpoint gate is untouched** — `role=="captain"` AND `>= 2 crew` still triggers `group_chat_fanout`; the facilitator lives **inside** it. The single-agent and non-Captain paths are byte-identical.
- **`_build_session_history` behavior is unchanged for the 4-arg call** — only an additive optional `prior=None` param (defaults to the existing read).
- **Do NOT touch / modify** `WardRoomRouter` (wrong substrate; the reply-cap method is phantom), `ThreadPriorityScorer`/`ThreadPriorityService`, `check_cross_agent_convergence`, `ThreadEchoAnalyzer`, or the `chat.py` AD-719 @-mention branch. Reuse ONLY the pure `jaccard_similarity`/`text_to_words` primitive and the `extract_all_leading_callsign_mentions` parser.
- **No LLM calls** anywhere in the facilitator or assembly helper — pure/deterministic only.
- **No new EventType, no new store, no new API route, no consensus gate** (Captain-authority, fully reversible ordering — Minimal Authority).

---

## Tracking

- `PROGRESS.md` — add an `AD-915 shipped` entry (facilitator design, reuse-vs-new accounting, test count) once gate-green.
- `docs/development/roadmap.md` — flip the Northstar "Ad-hoc crew collaboration" **AD-915** row to `SHIPPED <date> gate-verified` (precedent: AD-914 staged the roadmap edit explicitly).
- `DECISIONS.md` — append the AD-915 decision (NEW pure scorer because AD-641c scores threads not speakers; convergence reuses the pure Jaccard primitive, not the substrate-coupled detectors; phantom `check_and_increment_reply_cap` avoided).

## Acceptance criteria

- `src/probos/cognitive/chat_facilitator.py` is pure (no `probos.runtime`/router import, no I/O, no LLM); `ChatFacilitator` mirrors the AD-641c `ThreadPriorityScorer` pure pattern.
- `GroupChatConfig` added to `config.py` with all defaults; ProbOS boots zero-config; AD-914 paths inert (cap `0`, convergence below floors).
- Facilitator wired inside `group_chat_fanout`; `_send_one`/persistence/dispatch primitive unchanged; converged-no-mentions ⇒ `[]` and Captain msg still persisted.
- `tests/test_ad915_turn_taking_facilitator.py` adds **≥18** tests (BF-287 real fixtures) covering ranking, truncation, convergence suppression, @-mention always-included + override, assembly, and the AD-914 integration invariant.
- AD-914 regression (`tests/test_ad914_group_chat_fanout.py`) stays green; blast-radius `-k "thread or chat or fanout or intent"` green.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```text
git log --oneline -1
  4ab00335 (HEAD -> main) AD-914: group-chat fan-out + cross-agent visibility   # highest committed AD = AD-914

grep -n "agent_ids = crew_agent_participants" src/probos/routers/thread_fanout.py
  103:    agent_ids = crew_agent_participants(runtime, thread.participants)
grep -n "session_history = _build_session_history" src/probos/routers/thread_fanout.py
  104:    session_history = _build_session_history(runtime, store, thread_id, captain_msg.created_at)
grep -n "replies = await asyncio.gather" src/probos/routers/thread_fanout.py
  155:    replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])
grep -n "prior = store.list_messages" src/probos/routers/thread_fanout.py
  52:    prior = store.list_messages(thread_id, limit=1000, before=before)

grep -n "def jaccard_similarity|def text_to_words" src/probos/cognitive/similarity.py
  4:  def jaccard_similarity(a: set[str], b: set[str]) -> float:
  17: def text_to_words(text: str) -> set[str]:

grep -n "class ThreadPriorityScorer|class ThreadPriorityInput" src/probos/cognitive/thread_priority/scorer.py
  24: class ThreadPriorityInput:   # thread snapshot (captain_involved, recent_post_bodies, participant_departments, last_post_at, endorsement_count) — scores THREADS, not speakers
  43: class ThreadPriorityScorer:  # pure, no I/O — pattern to mirror

grep -n "def extract_all_leading_callsign_mentions" src/probos/crew_profile.py
  868: def extract_all_leading_callsign_mentions(text: str) -> tuple[list[str], str]:

grep -n "def get_agent_department" src/probos/ontology/service.py
  159: def get_agent_department(self, agent_type: str) -> str | None:

grep -n "def get_score" src/probos/consensus/trust.py
  406: def get_score(self, agent_id: AgentID) -> float:

grep -n "class ChatThreadMessage" src/probos/threads/__init__.py
  131: class ChatThreadMessage:   # id, thread_id, author_id, role, body, created_at, metadata

grep -n "class WardRoomConfig|dm_similarity_threshold|ward_room: WardRoomConfig" src/probos/config.py
  3747: class WardRoomConfig(BaseModel):
  3760:     dm_similarity_threshold: float = 0.6  # AD-614: Jaccard threshold for DM self-similarity suppression
  5147:     ward_room: WardRoomConfig = WardRoomConfig()

# PHANTOM (confirmed absent): WardRoomRouter.check_and_increment_reply_cap
grep -rn "check_and_increment_reply_cap" src/   ->  (no matches)
# Real Ward Room cap (wrong substrate, NOT reused): config.py:3753 max_thread_posts: int = 50  # BF-201
```
