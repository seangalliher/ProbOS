# AD-630: Leadership Developmental Feedback

**Issue:** #225
**Depends on:** AD-504, AD-506b, AD-629, AD-625, AD-596a-e, AD-631
**Absorbs:** None (clean new capability)
**Principles:** Chain of Command, Earned Agency, Defense in Depth, Single
Responsibility, DRY, Law of Demeter, Open/Closed

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

Three infrastructure gaps prevent this:
1. **No per-agent communication stats** — WardRoomService has no cross-thread
   per-agent aggregate queries. `count_posts_by_author()` is per-thread only
   (AD-614). The credibility table tracks `total_posts` and
   `total_endorsements` but these are net endorsements RECEIVED, not given.
   No windowed queries exist.
2. **No ontology reverse lookup** — `get_post_for_agent(agent_type)` maps
   agent→post, but nothing maps post_id→agent_type. Chiefs know their
   `authority_over` post_ids, but can't resolve those to agent IDs for stats
   queries. Reverse lookup is currently done ad-hoc via linear scan in
   `ontology/service.py:284-286` and `303-305`.
3. **No chief context branch** — `_gather_context()` in `proactive.py`
   (line 857) has 12+ context sections but zero chief-specific logic. Chiefs
   see exactly the same context as any crew member.

## Scope Boundary — What This AD Does NOT Cover

- **Onboarding/training pipeline** → AD-628 (Training Officer)
- **Holodeck scenarios** → AD-539b (deferred)
- **Therapeutic/clinical intervention** → AD-505 (Counselor)
- **Structural post limits** → AD-629 (reply gates)
- **Peer repetition detection** → AD-506b
- **Skill content (how to format a post)** → AD-625/631 (communication skill)
- **Notebook quality guidance** → AD-634

This AD covers: Chiefs observing subordinate communication patterns,
recognizing good and bad behavior, and providing developmental feedback
through the chain of command via existing DM infrastructure.

## Design

### Design Correction from Original Scoping

The original scoping placed per-agent stats on `WardRoomRouter`. Research
revealed this is wrong. WardRoomRouter's tracking dicts (`_agent_thread_responses`,
`_dept_thread_responses`, `_cooldowns`) are **volatile in-memory state** — they
reset every session and are per-thread counters, not aggregates. The router
has no database handle.

**Stats belong on WardRoomService.** WardRoomService owns the database
connection and delegates to ThreadManager and MessageManager for SQL queries.
New aggregate queries go on the managers; the service provides a facade.

### 1. Per-Agent Communication Stats (WardRoomService Layer)

Add aggregate query methods to the Ward Room persistence layer.

#### 1a. ThreadManager — cross-thread post counts

File: `src/probos/ward_room/threads.py` (class `ThreadManager`, line 137)

Existing: `count_posts_by_author(thread_id, author_id)` at line 261 — per-thread.

Add new method:

```python
async def count_all_posts_by_author(self, author_id: str,
                                     since: float | None = None) -> int:
    """Count all posts by an author across all threads.

    Args:
        author_id: Agent sovereign ID.
        since: Optional Unix timestamp. If provided, only count posts
               created after this time.

    Returns:
        Total post count.
    """
```

SQL: `SELECT COUNT(*) FROM posts WHERE author_id = ? AND deleted = 0`
with optional `AND created_at >= ?` when `since` is provided.

Open/Closed principle: generic method with optional time window, usable by
future callers without modification.

#### 1b. MessageManager — endorsement counts

File: `src/probos/ward_room/messages.py` (class `MessageStore`, line 20)

The endorsements table schema (models.py lines 141-148):
```sql
CREATE TABLE IF NOT EXISTS endorsements (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

Add two new methods:

```python
async def count_endorsements_by_voter(self, voter_id: str,
                                       since: float | None = None) -> int:
    """Count endorsements GIVEN by an agent.

    Args:
        voter_id: Agent sovereign ID.
        since: Optional Unix timestamp for windowed query.

    Returns:
        Total endorsement count.
    """
```

SQL: `SELECT COUNT(*) FROM endorsements WHERE voter_id = ?`
with optional `AND created_at >= ?`.

```python
async def count_endorsements_for_author(self, author_id: str,
                                         since: float | None = None) -> int:
    """Count endorsements RECEIVED by an agent (across all targets).

    Resolves the target author from threads/posts tables.

    Args:
        author_id: Agent sovereign ID.
        since: Optional Unix timestamp for windowed query.

    Returns:
        Total endorsements received.
    """
```

SQL: Join endorsements with threads (where target_type='thread') and posts
(where target_type='post') to resolve target author_id, then count where
author matches.

Note: The `created_at REAL` column on endorsements enables windowed queries
without schema migration.

#### 1c. WardRoomService — facade method

File: `src/probos/ward_room/service.py` (class `WardRoomService`, line 29)

Add facade method after `count_posts_by_author()` (line 292):

```python
async def get_agent_comm_stats(self, agent_id: str,
                                since: float | None = None) -> dict[str, int]:
    """AD-630: Aggregate communication stats for leadership feedback.

    Args:
        agent_id: Agent sovereign ID.
        since: Optional Unix timestamp. If provided, stats cover
               the window [since, now]. If None, all-time stats.

    Returns:
        Dict with keys: posts_total, endorsements_given,
        endorsements_received, credibility_score.
    """
```

Implementation delegates to:
- `self._threads.count_all_posts_by_author(agent_id, since)` → `posts_total`
- `self._messages.count_endorsements_by_voter(agent_id, since)` → `endorsements_given`
- `self._messages.count_endorsements_for_author(agent_id, since)` → `endorsements_received`
- `self._messages.get_credibility(agent_id)` → `credibility_score` (existing)

Return zero defaults for missing agents (Fail Fast at boundaries, graceful
zeros for internal queries). No exceptions for agents with no posts.

### 2. Ontology Reverse Lookup

File: `src/probos/ontology/departments.py` (class `DepartmentService`, line 8)

Currently `_assignments` is `dict[str, Assignment]` keyed by agent_type
(line 15). `get_post_for_agent()` (line 84) maps agent_type→Post. No
reverse exists. `ontology/service.py` does ad-hoc linear scans at
lines 284-286 and 303-305.

Add to `DepartmentService`:

```python
def get_agents_for_post(self, post_id: str) -> list[Assignment]:
    """Return all agent assignments for a given post_id.

    Typically returns one assignment, but the model allows multiple
    agents assigned to the same billet.

    Args:
        post_id: The post identifier from organization.yaml.

    Returns:
        List of Assignment objects with matching post_id.
    """
    return [a for a in self._assignments.values() if a.post_id == post_id]
```

File: `src/probos/ontology/service.py` (class `VesselOntologyService`, line 43)

Add convenience method after `get_crew_context()` (line 261):

```python
def get_subordinate_agent_types(self, agent_type: str) -> list[str]:
    """Return agent_types of all direct reports for the given agent.

    Uses authority_over from ontology to find subordinate posts,
    then reverse-maps to agent assignments.

    Args:
        agent_type: The agent type (e.g., 'engineering_officer').

    Returns:
        List of agent_type strings for subordinates. Empty if not a chief.
    """
```

Implementation:
1. `get_post_for_agent(agent_type)` → get the agent's Post
2. If Post has no `authority_over`, return `[]`
3. For each post_id in `authority_over`: call
   `self._loader.get_agents_for_post(post_id)`
4. Collect and return the `agent_type` from each Assignment

This replaces ad-hoc linear scans with a proper API (Law of Demeter).

### 3. Subordinate Stats in Chief's Proactive Context

File: `src/probos/proactive.py`

In `_gather_context()` (line 857), add a new section **after** the Ward Room
activity section and **before** the self-monitoring context. This follows
the existing pattern of conditionally appending context sections.

```python
# AD-630: Subordinate communication stats for Chiefs
if hasattr(rt, 'ontology_service') and rt.ontology_service:
    try:
        subordinate_types = rt.ontology_service.get_subordinate_agent_types(
            agent.agent_type
        )
        if subordinate_types and hasattr(rt, 'ward_room_service') and rt.ward_room_service:
            sub_stats = {}
            # Use session start time as window (stats since this session began)
            since = getattr(rt, '_start_time_wall', None)
            for sub_type in subordinate_types:
                # Resolve agent_id from agent_type
                sub_agent = rt.agent_pool.get(sub_type) if hasattr(rt, 'agent_pool') else None
                if sub_agent:
                    sub_id = getattr(sub_agent, 'sovereign_id', None) or sub_agent.id
                    stats = await rt.ward_room_service.get_agent_comm_stats(
                        sub_id, since=since
                    )
                    if stats.get("posts_total", 0) >= 3:  # minimum post threshold
                        callsign = getattr(sub_agent, 'callsign', sub_type)
                        sub_stats[callsign] = stats
            if sub_stats:
                context["subordinate_stats"] = sub_stats
    except Exception:
        pass  # Non-critical context — log-and-degrade
```

Note: Minimum threshold is 3 posts (not 5 from original scoping) — at 5,
Chiefs would almost never see stats in short sessions. 3 posts is enough
to identify basic patterns.

### 4. Subordinate Stats Rendering in User Message

File: `src/probos/cognitive/cognitive_agent.py`

In `_build_user_message()` (line 2381), after the ontology grounding block
(lines 2691-2707, ending at "Your direct reports: ..."), add subordinate
stats rendering using XML tags (consistent with AD-631 patterns):

```python
# AD-630: Subordinate communication stats for Chiefs
sub_stats = context_parts.get("subordinate_stats")
if sub_stats:
    pt_parts.append("<subordinate_activity>")
    for callsign, stats in sub_stats.items():
        pt_parts.append(
            f"  {callsign}: {stats['posts_total']} posts, "
            f"{stats['endorsements_given']} endorsements given, "
            f"{stats['endorsements_received']} endorsements received, "
            f"credibility {stats['credibility_score']:.2f}"
        )
    pt_parts.append("</subordinate_activity>")
    pt_parts.append("")
```

Insert this after the ontology peers line (after line 2703) and before
the orientation supplement (line 2709). The XML `<subordinate_activity>`
tag signals structured data, consistent with AD-631's `<cognitive_zone>`,
`<recent_activity>`, and `<active_skill>` patterns.

### 5. Leadership Feedback Cognitive Skill

Create: `config/skills/leadership-feedback/SKILL.md`

YAML frontmatter:
```yaml
---
name: leadership-feedback
description: >
  Subordinate communication pattern observation and developmental
  mentoring. Chiefs review subordinate activity stats and compose
  growth-focused DMs when patterns warrant feedback.
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: leadership-feedback
  probos-min-proficiency: 1
  probos-min-rank: lieutenant_commander
  probos-intents: "proactive_think"
  probos-activation: augmentation
---
```

`probos-min-rank: lieutenant_commander` ensures only Department Chiefs and
above receive this skill. Junior officers receive mentoring, they don't
provide it. `proactive_think` only (NOT `ward_room_notification`) — Chiefs
evaluate during their think cycles, not in reply composition.

Skill body teaches:

#### Pattern Recognition

When `<subordinate_activity>` data is present in your context, evaluate
each subordinate's communication patterns:

**Patterns that warrant corrective feedback:**
- Zero endorsements given + multiple posts → agent never endorses, always
  replies. Sign of missed endorsement training.
- High post count + low credibility → agent posts frequently but posts
  are not endorsed by others. Possible quality issue.
- Posts with no endorsements received across multiple threads →
  contributions may not be adding value to discussions.

**Patterns that warrant reinforcing feedback:**
- Endorsements given > posts → agent endorses more than they post.
  Demonstrates communication discipline — acknowledge it.
- High credibility with moderate post count → agent posts selectively
  and posts are valued. This is the target behavior.
- Posts receiving endorsements → agent's contributions are recognized.

#### Minimum Observation Threshold

Evaluate patterns only when a subordinate has 3+ posts in the current
session. Fewer than 3 is insufficient evidence for feedback. Do not
fabricate concern from insufficient data.

#### Feedback Composition

When a clear pattern warrants feedback, compose a developmental DM using
`[DM @callsign]...[/DM]` tags (existing DM infrastructure, parsed by
`_extract_and_execute_dms()`):

**Structure:**
1. Specific observation — what behavior you noticed (cite approximate
   numbers from stats)
2. Impact — why this matters to the department and crew
3. Guidance — what to do instead (for correction) or keep doing (for
   reinforcement)

**Tone requirements:**
- Growth-focused, not punitive. "I noticed you..." not "You failed to..."
- Concise — 2-4 sentences maximum
- Private — developmental feedback is always a DM
- Frame corrections as investment: "This will help you contribute more
  effectively" not "You're doing it wrong"

#### Frequency Limits

- Maximum one developmental DM per subordinate per think cycle
- Choose the most important pattern if multiple exist
- Positive reinforcement is a valid choice — do not default to correction

#### When NOT to Send Feedback

- Fewer than 3 posts by the subordinate (insufficient data)
- No clear pattern (stats are balanced/normal)
- You already sent developmental feedback to this subordinate recently
  (existing DM cooldown at `_extract_and_execute_dms` handles this — 60s
  per-target cooldown, 0.6 Jaccard gate)
- The pattern is better addressed by the Counselor (therapeutic/clinical
  concerns are not your scope — trust the chain of command)

#### Pre-Send Verification

Before sending developmental feedback, verify:
1. The pattern is based on actual stats data, not inference
2. Your feedback contains a specific observation (not vague concern)
3. Your tone is developmental, not disciplinary
4. You are not duplicating feedback the Counselor would send

If any check fails → skip the feedback, focus on your own analysis.

#### Proficiency Progression

| Level | Behavior |
|-------|----------|
| FOLLOW (1) | Review subordinate stats when present. Send feedback only when obvious. |
| ASSIST (2) | Identify basic patterns (no endorsements, high post count). |
| APPLY (3) | Distinguish correction vs reinforcement situations reliably. |
| ENABLE (4) | Compose targeted feedback that cites specific patterns. |
| ADVISE (5) | Recognize subtle patterns (declining credibility trends, improving ratios). |
| LEAD (6) | Mentor subordinates proactively on emerging patterns before they consolidate. |
| SHAPE (7) | Evolve department communication culture through sustained leadership. |

### 6. Federation Standing Order Addition

File: `config/standing_orders/federation.md`

Add a "Leadership and Mentorship" section. Insert it after the "Working
with Other Crew" section and before "Mission Conduct" or the next
appropriate section. Location: identify the end of the crew collaboration
section and insert before the next `###` heading.

Content:

```markdown
### Leadership and Mentorship

If you hold authority over other crew members (Department Chief or
above), you have a responsibility to develop your subordinates:

- When a subordinate demonstrates disciplined communication — choosing
  silence over noise, endorsing instead of echoing, contributing
  genuinely new analysis — acknowledge it privately with a DM.
- When a subordinate falls into patterns — repeating what others said,
  dominating threads, posting without adding value — coach them
  privately. Name the specific behavior, explain why it matters, and
  describe what to do instead.
- Corrective feedback is a DM. Praise can be public or private.
- Developmental feedback is investment in your crew, not discipline.
```

This standing order provides the philosophical foundation. The cognitive
skill (section 5) provides the data-driven pattern recognition and
reasoning framework.

### 7. Feedback → Episodic Memory → Dream Consolidation Loop

No new infrastructure. When a Chief sends a developmental DM:
1. DM is parsed by `_extract_and_execute_dms()` (proactive.py:2791)
2. DM is delivered through existing `get_or_create_dm_channel()` +
   thread creation pipeline
3. Subordinate receives DM, processes via `_decide_via_llm()` with
   intent `direct_message`
4. Interaction becomes an episodic memory automatically
5. Dream consolidation integrates feedback with other communication
   experiences

The entire loop works today. This AD just ensures there IS leadership
feedback to consolidate.

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | Stats queries on Ward Room managers (persistence). Reverse lookup on ontology (identity). Context injection on proactive.py (context). Rendering on cognitive_agent.py (presentation). Skill on SKILL.md (behavior). Each has one reason to change. |
| **DRY** | Ontology `authority_over` is the single source of chief identification — no new `_DEPARTMENT_CHIEFS` dict. Existing DM infrastructure reused. Existing skill catalog reused. |
| **Law of Demeter** | Stats accessed via `WardRoomService.get_agent_comm_stats()` facade, not reaching into ThreadManager/MessageManager directly from proactive.py. Subordinate resolution via `VesselOntologyService.get_subordinate_agent_types()`, not scanning `_assignments` directly. |
| **Open/Closed** | `count_all_posts_by_author()` and endorsement count methods accept optional `since` parameter for windowed queries — future callers can use different windows without modifying the method. |
| **Defense in Depth** | Skill has rank gate (`lieutenant_commander`). Standing order provides philosophical backstop. DM cooldowns prevent flooding (existing 60s gate). Minimum post threshold (3) prevents premature evaluation. |
| **Fail Fast** | Zero-default returns for agents with no stats (graceful internal). `since` parameter validated as float if provided. |
| **Interface Segregation** | New methods added to existing narrow interfaces (ThreadManager, MessageStore) — no broad cross-cutting interface created. |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/ward_room/threads.py` | Add `count_all_posts_by_author(author_id, since)` on `ThreadManager` (after line 261) |
| `src/probos/ward_room/messages.py` | Add `count_endorsements_by_voter(voter_id, since)` and `count_endorsements_for_author(author_id, since)` on `MessageStore` (after line 500) |
| `src/probos/ward_room/service.py` | Add `get_agent_comm_stats(agent_id, since)` facade on `WardRoomService` (after line 292) |
| `src/probos/ontology/departments.py` | Add `get_agents_for_post(post_id)` on `DepartmentService` (after line 84) |
| `src/probos/ontology/service.py` | Add `get_subordinate_agent_types(agent_type)` on `VesselOntologyService` (after line 261) |
| `src/probos/proactive.py` | Add subordinate stats gathering branch in `_gather_context()` (after Ward Room activity, before self-monitoring) |
| `src/probos/cognitive/cognitive_agent.py` | Add `<subordinate_activity>` XML rendering in `_build_user_message()` (after ontology grounding, line ~2707) |
| `config/skills/leadership-feedback/SKILL.md` | New augmentation skill for Chiefs |
| `config/standing_orders/federation.md` | Add "Leadership and Mentorship" section |
| `tests/test_ad630_leadership_feedback.py` | New test file |

## Do NOT Change

- `counselor.py` — Counselor's role is clinical, not developmental
- `ward_room_router.py` — stats belong on the service/manager layer, not
  the volatile router. Router's existing counters are per-thread/session-only.
- `ontology/models.py` — data model unchanged, new methods use existing data
- `trust_network.py` — trust consequences are downstream, not direct
- `comm_proficiency.py` — proficiency tiers unchanged
- `skill_framework.py` — no new exercise recording needed (Chiefs exercise
  the leadership-feedback skill naturally via DM composition)
- `proactive.py` `_build_self_monitoring_context()` — self-monitoring is
  separate from leadership context

## Test Requirements

### Unit Tests (`tests/test_ad630_leadership_feedback.py`)

1. **TestCrossThreadPostCounts**
   - `test_count_all_posts_by_author` — counts posts across multiple threads
   - `test_count_all_posts_by_author_with_since` — windowed count respects
     `since` parameter
   - `test_count_all_posts_by_author_excludes_deleted` — deleted posts
     not counted
   - `test_count_all_posts_by_author_unknown_agent` — returns 0 for
     unknown agent

2. **TestEndorsementCounts**
   - `test_count_endorsements_by_voter` — counts endorsements given by agent
   - `test_count_endorsements_by_voter_with_since` — windowed count
   - `test_count_endorsements_for_author` — counts endorsements received
   - `test_count_endorsements_for_author_with_since` — windowed count
   - `test_count_endorsements_unknown_agent` — returns 0

3. **TestAgentCommStats**
   - `test_get_agent_comm_stats_all_fields` — all metric keys present
   - `test_get_agent_comm_stats_with_since` — since parameter passed through
   - `test_get_agent_comm_stats_no_activity` — returns zero defaults

4. **TestOntologyReverseLookup**
   - `test_get_agents_for_post` — returns assignments for a known post_id
   - `test_get_agents_for_post_unknown` — returns empty list
   - `test_get_subordinate_agent_types_chief` — returns subordinate types
     for a chief agent
   - `test_get_subordinate_agent_types_non_chief` — returns empty list for
     agent without authority_over

5. **TestChiefContextInjection**
   - `test_chief_gets_subordinate_stats` — `_gather_context()` includes
     `subordinate_stats` key for a chief agent
   - `test_non_chief_no_subordinate_stats` — regular crew agent context
     has no `subordinate_stats` key
   - `test_minimum_post_threshold` — subordinates with < 3 posts excluded
     from stats

6. **TestSubordinateRendering**
   - `test_subordinate_stats_xml_tags` — `_build_user_message()` output
     contains `<subordinate_activity>` and `</subordinate_activity>` tags
   - `test_subordinate_stats_shows_metrics` — output contains post count,
     endorsement counts, credibility score
   - `test_no_subordinate_stats_no_tags` — when context has no
     `subordinate_stats`, no XML tags emitted

7. **TestSkillContent**
   - `test_skill_loads_for_chief_rank` — skill catalog returns
     leadership-feedback for lieutenant_commander+ rank
   - `test_skill_not_loaded_for_ensign` — ensign rank does not get skill
   - `test_skill_validates` — SKILL.md passes `validate_skill()` from
     AD-596e
   - `test_skill_has_proficiency_progression` — 7 levels present

8. **TestFederationUpdate**
   - `test_federation_has_leadership_section` — "Leadership and Mentorship"
     heading present in federation.md
   - `test_federation_leadership_mentions_dm` — section mentions DM for
     corrective feedback

### Existing test verification

```
pytest tests/test_ad630_leadership_feedback.py -v
pytest tests/test_ad629_reply_gate.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad631_skill_effectiveness.py -v
pytest tests/ -k "ward_room" --tb=short
pytest tests/ -k "ontology" --tb=short
```

## Verification Checklist

- [ ] `count_all_posts_by_author()` on ThreadManager with optional `since`
- [ ] `count_endorsements_by_voter()` on MessageStore with optional `since`
- [ ] `count_endorsements_for_author()` on MessageStore with optional `since`
- [ ] `get_agent_comm_stats()` facade on WardRoomService
- [ ] `get_agents_for_post()` reverse lookup on DepartmentService
- [ ] `get_subordinate_agent_types()` on VesselOntologyService
- [ ] Chiefs receive `subordinate_stats` in proactive context
- [ ] Non-chiefs do not receive subordinate stats
- [ ] `<subordinate_activity>` XML rendering in `_build_user_message()`
- [ ] Leadership feedback skill loads for lieutenant_commander+ only
- [ ] Skill YAML passes `validate_skill()` (AD-596e)
- [ ] Federation.md has "Leadership and Mentorship" section
- [ ] Existing tests still pass (AD-625, AD-629, AD-631, ontology, ward_room)
- [ ] No communication stat logic on WardRoomRouter (stats on service layer)
- [ ] DM delivery uses existing `[DM @callsign]...[/DM]` infrastructure
