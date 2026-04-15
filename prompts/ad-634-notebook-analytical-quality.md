# AD-634: Notebook Analytical Quality Skill

**Issue:** #229
**Depends on:** AD-631, AD-625, AD-626, AD-596a-e
**Absorbs:** None (clean new capability)
**Principles:** Single Responsibility, DRY, Open/Closed

## Problem

ProbOS notebook infrastructure measures **structural** quality — topic
diversity, freshness, novelty rate, convergence, self-repetition (AD-550,
AD-552, AD-553, AD-554, AD-555). These filters catch exact duplicates,
stale entries, and repetitive writing. But nothing evaluates **semantic
content quality**.

Observable failures in live notebook entries:
1. **Ward Room summary repackaging** — agent rewrites what was said in a
   thread, adding nothing beyond what the thread already contains
2. **Process narration without findings** — "I looked at X and noticed Y"
   without stating what Y means or what to do about it
3. **Data recording presented as analysis** — logging a metric value without
   comparing to baseline, explaining significance, or tracking trend
4. **Topic reset** — writing about the same topic without building on the
   prior entry (new entry ignores revision history)
5. **Conclusion-free entries** — observations without interpretation

These pass all structural quality gates (AD-555 scores them as diverse,
fresh, novel) because the *shape* of the entry is fine — it's the *depth*
that's missing.

## Scope Boundary — What This AD Does NOT Cover

- **Structural quality measurement** → AD-555 (quality engine)
- **Dedup / self-repetition detection** → AD-550, AD-552
- **Cross-agent convergence** → AD-554
- **Notebook syntax and mechanics** → federation.md (lines 292-303),
  ship.md (notebook guidance sections)
- **Ward Room post quality** → AD-625/631 (communication-discipline skill)
- **Leadership feedback on communication** → AD-630
- **Notebook infrastructure (parsing, storage)** → AD-434, proactive.py

This AD teaches: what constitutes analytically useful notebook content, and
how to self-evaluate before writing.

## Design

### Config-Only AD

This AD creates exactly **one new file**:
`config/skills/notebook-quality/SKILL.md`

No code changes. No schema changes. No new methods. The skill catalog
auto-discovers skills via `rglob("SKILL.md")` in `config/skills/`
(skill_catalog.py line 272). The new directory and SKILL.md file are all
that's needed.

### Co-Activation with Communication Discipline

Both `communication-discipline` and `notebook-quality` will fire on the
`proactive_think` intent via `_load_augmentation_skills()`. This is by
design — `_load_augmentation_skills()` (cognitive_agent.py line 1873)
concatenates ALL matching augmentation skills. Communication discipline
guides Ward Room posting; notebook quality guides notebook writing. Both
are relevant during proactive think cycles.

**Ordering note:** Skill concatenation follows `_cache` iteration order
(insertion = scan order = filesystem). No explicit priority. This is
acceptable — the two skills address different output actions
(`[POST]`/`[REPLY]`/`[ENDORSE]` vs `[NOTEBOOK]`) with no conflict.

### Rank Gate: All Crew

Unlike `leadership-feedback` (lieutenant_commander+), notebook quality
applies to **all crew agents**. Every agent writes notebooks. Set
`probos-min-rank: ensign`.

### Relationship to Existing Notebook Context

Agents already see their notebook index in `<recent_activity>`:
```
Your notebooks: [topic-a (updated 2h ago), topic-b (updated 1d ago)]
```
And notebook content via `<notebook topic="...">` XML tags when a semantic
pull or explicit `[READ_NOTEBOOK]` is active.

The skill teaches agents to USE this existing context — specifically the
temporal threading aspect (building on prior entries) and the
`[READ_NOTEBOOK]` action for reviewing before writing.

### Relationship to Communication Discipline

`communication-discipline` teaches:
- Finding-first structure (Minto Pyramid) for Ward Room posts
- Pre-Submit Check (3 mandatory checks)
- Endorsement vs reply decision

`notebook-quality` teaches:
- Analytical Purpose Gate for notebook entries
- Finding-first structure applied to notebook context (longer form)
- Temporal Threading (building on prior entries)
- Data vs Analysis distinction
- Ward Room Differentiation (notebook must exceed thread content)

The Minto Pyramid principle (conclusion first) is shared, but applied
differently: 2-4 sentence Ward Room posts vs multi-paragraph notebook
entries. This is not DRY violation — it's the same principle at different
scales with different guidance.

## SKILL.md Content Specification

### YAML Frontmatter

```yaml
---
name: notebook-quality
description: >
  Analytical quality standards for notebook entries in Ship's Records.
  Teaches finding-first structure, temporal threading, data-vs-analysis
  distinction, and self-evaluation before writing.
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: notebook-quality
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "proactive_think"
  probos-activation: augmentation
---
```

### Skill Body Structure

Follow the pattern established by `communication-discipline/SKILL.md` and
`leadership-feedback/SKILL.md`:

1. **Title and role statement** — one paragraph establishing the skill's
   purpose
2. **Analytical Purpose Gate** — every `[NOTEBOOK topic-slug]` entry must
   answer a question or advance a hypothesis. If the entry is purely
   recording what happened without interpretation, it doesn't clear the
   gate. Agents should ask themselves: "What does this mean?" and "So
   what?" — if they can't answer, the entry isn't ready.
3. **Finding-First Structure** — adapted Minto Pyramid for notebook entries:
   - First paragraph: conclusion, finding, or hypothesis
   - Second paragraph: evidence and reasoning
   - Third paragraph: implications, next steps, or open questions
   - Contrast with anti-pattern: "I looked at X. Here are the numbers.
     They seem interesting." (no conclusion)
4. **Temporal Threading** — when writing about a topic that already exists
   in your notebook index (visible in `<recent_activity>`):
   - Read the prior entry first using `[READ_NOTEBOOK topic-slug]`
   - State what changed since the last entry
   - State what was confirmed or revised
   - Do NOT restart from zero — the notebook is a running analysis, not
     a series of disconnected snapshots
   - If the prior entry's conclusion still holds and nothing changed,
     don't write a new entry
5. **Data vs Analysis** — recording a metric value is data. Analysis
   requires:
   - Comparison to a baseline or prior value (what changed?)
   - Significance assessment (is this normal variance or anomalous?)
   - Causal hypothesis (what might explain this?)
   - Recording "trust score is 0.62" is data. Recording "trust score
     dropped from 0.71 to 0.62 over 3 cycles, coinciding with repeated
     cap hits — may indicate communication frustration" is analysis.
6. **Ward Room Differentiation** — your notebook must go beyond what was
   said in the Ward Room thread. If your notebook entry is a summary of
   thread content, it adds no value — the thread already exists. Value
   comes from:
   - Analysis that was too detailed for a 2-4 sentence Ward Room post
   - Cross-thread synthesis (connecting observations from multiple threads)
   - Longitudinal tracking (how has this topic evolved over multiple cycles?)
   - Data that wasn't in the original thread (your own measurements,
     comparisons to baselines you maintain)
7. **Anti-Patterns** — with explanations (not just "don't do this"):
   - **Process narration** — "I examined the trust scores and found them
     interesting." This describes YOUR process, not your findings. Nobody
     needs to know you examined something. State what you found.
   - **Ward Room repackaging** — copying or paraphrasing thread content
     into a notebook entry. The thread is already archived. Your notebook
     should add depth, not redundancy.
   - **Baseline recording without interpretation** — logging numbers
     without stating what they mean. A notebook of raw values is a
     database, not analysis.
   - **Topic reset** — writing about a topic as if for the first time
     when you have prior entries. Check your notebook index. Build on
     what you wrote before.
   - **Conclusion-free entries** — observations without a "so what?"
     statement. Every entry needs a takeaway, even if tentative: "This
     suggests..." or "I'll monitor for..." or "This confirms my earlier
     hypothesis that..."
8. **Pre-Write Verification Gate** — before composing `[NOTEBOOK]`:
   1. Does your entry contain a conclusion or finding? If not, it's raw
      data — consider whether it needs to be in a notebook at all.
   2. If you have a prior entry on this topic, does this entry build on
      it? If not, read the prior entry first with `[READ_NOTEBOOK]`.
   3. Does your entry contain analysis beyond what was said in the Ward
      Room thread? If not, the thread is sufficient — skip the notebook
      entry.
   If any check fails, do not write the entry.
9. **Proficiency Progression** — 7 levels (FOLLOW→SHAPE), adapted for
   analytical depth:

| Level | Behavior |
|-------|----------|
| FOLLOW (1) | Apply the Pre-Write Verification Gate. Ensure entries have conclusions. |
| ASSIST (2) | Distinguish data recording from analysis without checking. |
| APPLY (3) | Independently thread entries across cycles. Reference prior entries. |
| ENABLE (4) | Synthesize cross-thread observations into notebook analysis. |
| ADVISE (5) | Recognize when NOT to write — the prior entry still stands. |
| LEAD (6) | Produce hypothesis-driven entries that guide future observation. |
| SHAPE (7) | Evolve analytical standards through exemplary notebook practice. |

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | One file, one concern: teaching analytical quality for notebook entries. No code changes — separation between structural measurement (AD-555) and content quality instruction (AD-634). |
| **DRY** | Finding-first structure principle is shared with communication-discipline but applied at different scale (notebook vs Ward Room post). Notebook syntax mechanics are NOT repeated — the skill references existing standing orders. |
| **Open/Closed** | Skill activates through existing augmentation infrastructure. Adding notebook-quality requires no changes to cognitive_agent.py, proactive.py, skill_catalog.py, or any other code. |
| **Defense in Depth** | Content quality instruction (this skill) complements structural measurement (AD-555). Agents self-evaluate AND the system measures. Neither alone is sufficient. |
| **Interface Segregation** | New skill uses the narrow `augmentation` activation interface — no new event types, no new API endpoints, no new configuration fields. |

## Files to Create

| File | Content |
|------|---------|
| `config/skills/notebook-quality/SKILL.md` | New augmentation skill per specification above |

## Files to Verify (NOT Modify)

| File | Why Verify |
|------|------------|
| `config/skills/communication-discipline/SKILL.md` | Confirm no conflicting guidance, confirm both can co-activate |
| `config/skills/leadership-feedback/SKILL.md` | Confirm pattern consistency |
| `config/standing_orders/federation.md` | Confirm notebook section (lines 292-303) is not duplicated by skill |
| `config/standing_orders/ship.md` | Confirm notebook guidance is complementary, not duplicated |
| `src/probos/cognitive/skill_catalog.py` | Confirm `rglob("SKILL.md")` at line 272 will discover the new directory |

## Do NOT Change

- Any Python source files — this is config-only
- `federation.md` — notebook mechanics are already documented there
- `ship.md` — notebook usage guidance is already documented there
- `communication-discipline/SKILL.md` — complementary, not overlapping
- `notebook_quality.py` — structural measurement is separate from content
  instruction

## Test Requirements

### Unit Tests (`tests/test_ad634_notebook_quality.py`)

Since this is config-only, tests focus on skill validation and catalog
integration rather than behavioral code.

1. **TestSkillDiscovery**
   - `test_skill_file_exists` — `config/skills/notebook-quality/SKILL.md`
     exists and is readable
   - `test_skill_parses` — `parse_skill_file()` succeeds on the SKILL.md
   - `test_skill_validates` — `validate_skill()` returns `valid=True`
     with no errors (may have warnings)
   - `test_skill_name_matches_directory` — `name` field equals directory
     name `notebook-quality`

2. **TestSkillMetadata**
   - `test_department_is_wildcard` — `probos-department` is `"*"`
   - `test_min_rank_is_ensign` — `probos-min-rank` is `"ensign"`
   - `test_activation_is_augmentation` — `probos-activation` is
     `"augmentation"`
   - `test_intent_is_proactive_think` — `probos-intents` contains
     `"proactive_think"`
   - `test_skill_id` — `probos-skill-id` is `"notebook-quality"`

3. **TestCoActivation**
   - `test_both_skills_load_for_proactive_think` — when an ensign-rank
     agent queries augmentation skills for `proactive_think`, both
     `communication-discipline` AND `notebook-quality` are returned
   - `test_leadership_feedback_adds_third` — when a lieutenant_commander+
     agent queries, all three skills fire

4. **TestSkillContent**
   - `test_has_proficiency_progression` — skill body contains all 7 levels
     (FOLLOW through SHAPE)
   - `test_has_pre_write_gate` — skill body contains "Pre-Write" or
     verification gate language
   - `test_has_anti_patterns` — skill body contains anti-pattern section
   - `test_no_hardcoded_callsigns` — skill body does not contain any known
     crew callsign (validation layer 3 from `validate_skill()`)

### Existing test verification

```
pytest tests/test_ad634_notebook_quality.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad631_skill_effectiveness.py -v
pytest tests/ -k "skill" --tb=short
```

## Verification Checklist

- [ ] `config/skills/notebook-quality/SKILL.md` exists with valid YAML
      frontmatter
- [ ] Skill passes `validate_skill()` (AD-596e) with no errors
- [ ] Skill name `notebook-quality` matches directory name
- [ ] `probos-min-rank: ensign` — all crew agents get this skill
- [ ] `probos-activation: augmentation` — fires as context augmentation
- [ ] `probos-intents: "proactive_think"` — only on think cycles
- [ ] Skill co-activates with `communication-discipline` without conflict
- [ ] Skill body contains: Analytical Purpose Gate, Finding-First Structure,
      Temporal Threading, Data vs Analysis, Ward Room Differentiation,
      Anti-Patterns, Pre-Write Verification Gate, Proficiency Progression
- [ ] No duplication of notebook syntax or mechanics from federation.md
      or ship.md
- [ ] No hardcoded crew callsigns in skill body
- [ ] No Python code changes
- [ ] Existing skill tests still pass
