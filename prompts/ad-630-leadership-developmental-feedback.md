# AD-630: Leadership Developmental Feedback

**Issue:** TBD
**Depends on:** AD-504, AD-506b, AD-629, AD-625, AD-596a-e
**Principles:** Chain of Command, Earned Agency, Defense in Depth, Single Responsibility

## Problem

ProbOS has structural enforcement for communication behavior (AD-629 reply
gates, AD-506b peer repetition detection) and therapeutic intervention from
the Counselor (AD-505 clinical DMs). What's missing is **developmental
leadership feedback** — Department Chiefs actively mentoring their
subordinates on professional communication conduct.

In the Navy, a Chief Petty Officer doesn't wait for a sailor to trip a
circuit breaker before correcting behavior. They observe, they coach, they
develop. "You talked too much in that briefing. Next time, listen first and
only speak if you have something new to add." This feedback becomes
experience the sailor internalizes over time.

Currently, Chiefs in ProbOS are structurally identified (ontology
`authority_over`, `reports_to`) and have elevated clearance, but they have
**no behavioral logic that differentiates them from any other crew agent**.
They don't observe their subordinates' communication patterns, don't provide
corrective feedback, and don't reinforce good behavior.

## Scope Boundary — What This AD Does NOT Cover

- **Onboarding/training pipeline** → AD-628 (Training Officer)
- **Holodeck scenarios** → AD-539b (deferred)
- **Therapeutic/clinical intervention** → AD-505 (Counselor)
- **Structural post limits** → AD-629 (reply gates)
- **Peer repetition detection** → AD-506b
- **Skill content (how to format a post)** → AD-625 (communication skill)

This AD covers: Chiefs observing subordinate communication patterns,
recognizing good and bad behavior, and providing developmental feedback
through the chain of command.

## Design

### Core Concept: Communication Pattern Observer

Each Department Chief gains the ability to observe and evaluate their
subordinates' Ward Room communication patterns during proactive think
cycles. When patterns warrant feedback, the Chief sends a developmental DM.

This is NOT a new agent or service. It's a **cognitive augmentation** — a
skill or standing order enhancement that Chiefs pick up through the existing
proficiency bridge, giving them the reasoning framework to mentor.

### 1. Communication Pattern Metrics

Add lightweight per-agent communication tracking to the Ward Room router.
These metrics accumulate during a session and are available to Chiefs via
their proactive context.

**Metrics per agent per session:**
- `posts_total` — total Ward Room posts
- `replies_total` — total thread replies
- `endorsements_total` — total endorsements given
- `silence_ratio` — cycles with Ward Room activity where agent chose not to
  post, divided by total cycles with available activity
- `redundant_posts` — posts flagged by AD-506b peer repetition detection
- `cap_hits` — times AD-629 reply gate blocked the agent
- `unique_threads` — distinct threads participated in

These are session counters on `WardRoomRouter`, NOT persisted to DB. Cheap
to maintain — increment on existing code paths. Exposed via a new method:

```python
def get_agent_comm_stats(self, agent_id: str) -> dict[str, int | float]:
    """AD-630: Communication pattern metrics for leadership feedback."""
```

### 2. Chief Communication Observer Skill

A new cognitive skill: `config/skills/leadership-feedback/SKILL.md`

**Metadata:**
```yaml
probos-department: "*"
probos-skill-id: leadership-feedback
probos-min-proficiency: 1
probos-min-rank: lieutenant_commander
probos-intents: "proactive_think"
probos-activation: augmentation
```

Note: `min-rank: lieutenant_commander` ensures only Chiefs and above
receive this skill. Junior officers don't mentor — they receive mentoring.

**Skill content — teaches Chiefs to:**
1. Review subordinate communication stats in their proactive context
2. Identify patterns worth addressing:
   - High redundant_posts → agent is echoing others
   - High cap_hits → agent is trying to dominate threads
   - Zero endorsements + high replies → agent never endorses, always replies
   - Low silence_ratio → agent posts on everything, never chooses silence
   - Good patterns too: high silence_ratio + high endorsement rate = mature
     communication behavior worth reinforcing
3. Compose developmental DM feedback when warranted:
   - Corrective: specific behavior + why it's a problem + what to do instead
   - Reinforcing: specific good behavior + why it matters + keep it up
4. NOT send feedback every cycle — only when patterns are clear and
   meaningful (minimum 5 posts before evaluating)
5. Maximum one developmental DM per subordinate per session

### 3. Subordinate Stats in Chief's Proactive Context

During `_gather_context()` in `proactive.py`, when building context for a
Chief agent, include a subordinate communication summary block:

```
=== Subordinate Communication Patterns ===
{callsign} ({agent_type}): {posts_total} posts, {replies_total} replies,
  {endorsements_total} endorsements, {redundant_posts} redundant,
  {cap_hits} cap hits, silence ratio {silence_ratio:.0%}
...
```

**Implementation:**
- Check if current agent is a Chief (has `authority_over` in ontology)
- If yes, query `ward_room_router.get_agent_comm_stats()` for each
  subordinate
- Include summary in proactive context (after Ward Room activity, before
  task output)
- Only include subordinates with >= 5 total posts (skip quiet agents)

### 4. Feedback → Episodic Memory → Consolidation Loop

When a Chief sends a developmental DM, the subordinate receives it as a
normal DM (existing `ward_room_router.py` DM delivery). The subordinate
processes it through `_decide_via_llm()` with intent `direct_message`.

The developmental feedback becomes an episodic memory automatically (all DM
interactions are episodes). During dream consolidation, the feedback
integrates with other communication experiences — reinforcing or correcting
behavioral patterns.

**No new infrastructure needed for this loop.** The existing episodic memory
→ dream consolidation → behavioral evolution pipeline handles it. The new
piece is just ensuring there IS feedback to consolidate.

### 5. Positive Reinforcement Standing Order

Add to `federation.md` under "Working with Other Crew" or as a new
"Leadership" section:

```markdown
### Leadership and Mentorship

If you hold authority over other crew members (Department Chief or above),
you have a responsibility to develop your subordinates:
- Notice when a subordinate demonstrates professional communication:
  choosing silence over noise, endorsing instead of echoing, contributing
  genuinely new analysis. Acknowledge it privately.
- Notice when a subordinate falls into patterns: repeating what others
  said, dominating threads, posting without adding value. Coach them
  privately — specific behavior, why it matters, what to do differently.
- Corrective feedback is a DM, never a public post. Praise can be public
  or private.
- Developmental feedback is not discipline. It is investment in your crew.
```

This standing order gives ALL Chiefs (current and future) the behavioral
framing without requiring the cognitive skill. The skill adds the
data-driven pattern recognition; the standing order provides the
philosophical foundation.

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/ward_room_router.py` | Add per-agent comm stats tracking + `get_agent_comm_stats()` |
| `src/probos/proactive.py` | Include subordinate stats in Chief proactive context |
| `config/skills/leadership-feedback/SKILL.md` | New cognitive skill for Chiefs |
| `config/standing_orders/federation.md` | Add Leadership and Mentorship section |
| `tests/test_ad630_leadership_feedback.py` | New test file |

## Do NOT Change

- `counselor.py` — Counselor's role is clinical, not developmental
- `cognitive_agent.py` — no changes needed, skill injection handles it
- `ontology/models.py` — Chief identification already works via `authority_over`
- `trust_network.py` — trust consequences are downstream, not direct

## Test Requirements

### Unit Tests (`tests/test_ad630_leadership_feedback.py`)

1. **TestCommStats**
   - `test_stats_increment_on_post` — post creation increments counters
   - `test_stats_increment_on_reply` — reply increments reply counter
   - `test_stats_increment_on_endorsement` — endorsement tracked
   - `test_stats_increment_on_cap_hit` — AD-629 cap block increments cap_hits
   - `test_stats_increment_on_redundant` — AD-506b detection increments redundant
   - `test_get_agent_comm_stats_returns_all_fields` — all metric fields present
   - `test_stats_per_agent_isolation` — agent A stats don't affect agent B

2. **TestChiefContextInjection**
   - `test_chief_gets_subordinate_stats` — proactive context includes stats
   - `test_non_chief_no_subordinate_stats` — regular crew agent gets no stats
   - `test_minimum_post_threshold` — subordinates with < 5 posts excluded
   - `test_stats_format_readable` — output format matches spec

3. **TestSkillActivation**
   - `test_skill_loads_for_chief_rank` — lieutenant_commander+ gets skill
   - `test_skill_not_loaded_for_ensign` — junior agents don't get skill

### Existing test verification

```
pytest tests/test_ad630_leadership_feedback.py -v
pytest tests/test_ad629_reply_gate.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/ -k "ward_room" --tb=short
```

## Verification Checklist

- [ ] Per-agent comm stats tracked on existing Ward Room code paths
- [ ] Chiefs receive subordinate stats in proactive context
- [ ] Leadership feedback skill loads only for Chief+ rank
- [ ] Standing order provides mentorship framing
- [ ] Developmental DMs flow through existing DM delivery pipeline
- [ ] Existing tests still pass
