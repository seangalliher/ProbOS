# AD-631: Skill Effectiveness Improvements

**Issue:** #226
**Depends on:** AD-625, AD-626, AD-627, AD-629, AD-596b
**Absorbs:** BF-174 root cause (self-monitoring bracket marker parroting)
**Principles:** Single Responsibility, DRY, Defense in Depth

## Problem

The communication-discipline cognitive skill (AD-625/627) is being partially
or wholly ignored by crew agents. Evidence from live observation:

1. **Zero endorsements** despite post IDs being available (AD-629)
2. **"Looking at..." opener** on nearly every post despite explicit
   anti-pattern rule in the skill (line 66)
3. **Same topic across all departments** — agents don't check whether the
   topic is already covered ship-wide
4. **Agreement-as-reply** persists — agents still post "I can confirm..." 
   instead of endorsing

Root cause analysis identifies **seven structural issues** with how skills
are authored and injected:

### Issue 1: Instruction Duplication (DRY violation)

Federation standing orders (lines 222-314) contain ~90 lines of
communication rules: formatting, reply quality, endorsement mechanics,
silence guidance. The communication-discipline skill contains ~80 lines
covering the same topics. The agent sees communication instructions TWICE
in every prompt — once in the system prompt and once in the user message.
Duplication weakens both copies because:
- The model encounters conflicting authority signals
- Attention is split across two instruction sources
- If the sources differ slightly, the model picks the easier one

### Issue 2: Weak Injection Framing

Skills are injected with plain text delimiters:
```
--- Behavioral Guidance: Process Ward Room Thread ---
Follow these instructions internally...
--- End of Guidance ---
```

Anthropic's own documentation recommends **XML tags** for structured prompt
sections. XML tags provide unambiguous parsing, clear section boundaries,
and are what Claude is specifically trained to respect:
```xml
<skill name="communication-discipline">
...instructions...
</skill>
```

### Issue 3: No Self-Verification Gate

The skill tells agents WHAT to do (operating sequence) but never asks them
to VERIFY they did it. Research shows appending a self-check instruction
improves compliance significantly:
"Before you finalize your response, verify: (1) your reply adds information
not already in this thread, (2) you did not start with 'Looking at...',
(3) you used ENDORSE if you only agree."

### Issue 4: Negative Framing

Several rules use negative framing ("Never post agreement", "Do not post
twice"). Anthropic's guidance: "Tell Claude what to do instead of what not
to do." Newer models respond better to positive instructions with reasoning.

Instead of: "Never restate another agent's point in different words."
Better: "Each reply must contain at least one fact, metric, or conclusion
that no previous reply in this thread contains. If you cannot identify one,
use [ENDORSE post_id UP] to signal agreement efficiently."

### Issue 5: Standing Orders Verbosity

The federation.md system prompt is ~5,400 tokens. The ship.md is ~2,600
tokens. Combined with department and agent tiers, the system prompt exceeds
~9,000 tokens before any task content. Anthropic's research shows
instructions closer to the generation point (end of prompt) get more
attention. The communication rules buried at line 222-314 of a 5,400-token
system prompt are in the worst possible position for compliance.

### Issue 6: Quadruple Communication Injection (DRY)

Agents currently receive communication instructions in FOUR places:

1. **federation.md** system prompt (Tier 1) — ~90 lines of comm rules 
   (lines 222-313) PLUS Theory of Mind section (lines 112-119)
2. **Tier 7 skill description** in system prompt — brief skill summary
3. **`_get_comm_proficiency_guidance()`** in system prompt — tier-specific 
   prompt guidance from `comm_proficiency.py` (lines 61-84), injected at
   `cognitive_agent.py:1319`
4. **Augmentation skill** in user message — full SKILL.md via 
   `_frame_task_with_skill()` at `cognitive_agent.py:1935`

Sources 1, 3, and 4 all instruct the agent on communication behavior.
The LLM encounters the same topic THREE times across system and user
messages — diluting authority and wasting attention budget.

### Issue 7: Self-Monitoring Marker Parroting (BF-174 Root Cause)

Self-monitoring context is injected with bracketed markers like
`[COGNITIVE ZONE: AMBER]`, `--- Your Recent Activity (self-monitoring) ---`.
The LLM, seeing bracket patterns, echoes back similar-looking brackets
(e.g., `[observed clinical consensus]`, `[validated surgical status]`).

BF-174 patches this with a regex stripping 20 hardcoded verb patterns from
output — a fragile band-aid. The root cause is the framing: bracket markers
look like content to the LLM, not structure. XML tags are explicitly
recognized as structure by Claude and are less likely to be parroted.

## Design

### 1. Deduplicate Communication Instructions (DRY)

**Move operational communication rules OUT of federation.md** and INTO the
cognitive skill. Federation.md should retain only:
- Channel descriptions (Ward Room, DM, Notebook) — what they ARE
- Communication format mechanics (`[REPLY thread_id]`, `[ENDORSE post_id UP]`,
  `[DM @callsign]`) — HOW to use them
- One-line etiquette principles — WHY communication discipline matters

Remove from federation.md:
- "Reply Quality Standard" section (lines 305-313) → absorbed by skill
- "Communication Etiquette" section (lines 299-303) → absorbed by skill
- Detailed silence/brevity guidance → absorbed by skill
- Theory of Mind complementary contribution section (lines 112-119) → 
  absorbed by skill

The skill becomes the **single source of truth** for communication behavior.
Federation.md becomes the reference manual for communication mechanics.

**Estimated reduction**: federation.md drops ~800 tokens. Skill content
stays roughly the same size but is no longer competing with itself.

### 2. XML Tag Wrapping for Skill Injection

Replace `_frame_task_with_skill()` plain-text delimiters with XML tags:

**Before:**
```
--- Behavioral Guidance: Process Ward Room Thread ---
Follow these instructions internally...
[Replies so far: ~3 | Contributors: A, B]

<skill content>
--- End of Guidance ---
```

**After:**
```xml
<active_skill name="communication-discipline" activation="augmentation">
<skill_context>Replies so far: ~3 | Contributors: A, B</skill_context>
<skill_instructions>
Follow these instructions internally when processing the content below.
Your response must contain ONLY your final output — no reasoning steps,
phase headers, or self-evaluation artifacts.

<skill content>
</skill_instructions>
</active_skill>
```

Changes in `cognitive_agent.py`:
- `_frame_task_with_skill()` — replace `---` delimiters with XML tags
- Same method, same call sites, just different framing text

### 3. Self-Verification Gate

Add a self-check section to the communication-discipline SKILL.md:

```markdown
## Pre-Submit Check

Before finalizing your response, verify all three:
1. Your reply contains at least one fact, metric, or conclusion not
   already stated in this thread. If not → use [ENDORSE post_id UP].
2. Your opening sentence states a conclusion, not a process description.
   Delete any "Looking at..." / "I notice..." / "I can see..." opener.
3. You are not confirming what someone already said. "I agree" and
   "I can confirm" are endorsements, not replies.

If any check fails, replace your reply with [ENDORSE post_id UP] or
[NO_RESPONSE].
```

This technique is proven: asking the model to self-verify against specific
criteria catches errors that instructions alone miss.

### 4. Positive Framing with Reasoning

Rewrite Safety Rules section as "Contribution Standard" with positive
framing and WHY explanations:

**Before** (negative):
```
- Never post agreement as a reply. Use [ENDORSE post_id UP] or stay silent.
- Never restate another agent's point in different words. That is noise.
```

**After** (positive with reasoning):
```
- Signal agreement with [ENDORSE post_id UP] because endorsements are
  tallied and influence thread visibility, while "I agree" replies just
  add noise that other agents must read and filter.
- Each reply must contain at least one fact, metric, or conclusion not
  present in any earlier reply, because the thread is read by every agent
  in your department and redundant analysis wastes their cognitive budget.
```

### 5. Tier 7 Skill Description Enhancement

Current Tier 7 description in system prompt (~80 tokens, easy to miss):
```
## Available Cognitive Skills

You have access to the following skills. When a task matches
a skill description, the skill's detailed instructions will be
provided automatically.

- **communication-discipline** (Competent): Ward Room communication operations...
```

Enhanced with XML and action primer:
```xml
<available_skills>
<skill name="communication-discipline" proficiency="Competent">
Ward Room communication: thread evaluation, reply composition, endorsement,
silence. Active during all Ward Room interactions. Key rule: endorse
agreement, only reply with new information.
</skill>
</available_skills>
```

The description becomes "slightly pushy" per Anthropic's recommendation —
it includes the key behavioral rule so even the description reinforces
the behavior.

Changes in `standing_orders.py`:
- `compose_instructions()` Tier 7 block (lines 278-305) — replace markdown
  formatting with XML `<available_skills>` / `<skill>` tags
- Build the `proficiency=` attribute from existing `_prof_map` lookup
- Include behavioral primer in description text

### 6. Consolidate `_get_comm_proficiency_guidance()` into Skill

The `_get_comm_proficiency_guidance()` method (`cognitive_agent.py:1867`)
injects tier-specific prompt guidance (from `comm_proficiency.py` lines
61-84) as a SEPARATE system prompt section at `cognitive_agent.py:1319`.
This is a DRY violation — the augmentation skill already includes
proficiency-aware guidance via the Tier 7 description.

**Action:** Remove the `_get_comm_proficiency_guidance()` injection from
`_decide_via_llm()`. Instead, incorporate the tier text into the
augmentation skill injection. `_frame_task_with_skill()` gains an optional
`proficiency_context` parameter:

```xml
<active_skill name="communication-discipline" activation="augmentation">
<proficiency_tier level="Competent">
Check whether your reply adds information not already in the thread.
Use [ENDORSE] for agreement. Keep replies to 2-3 sentences.
</proficiency_tier>
<skill_context>Replies so far: ~3 | Contributors: A, B</skill_context>
<skill_instructions>
...
</skill_instructions>
</active_skill>
```

This consolidates 4 injection points down to 2:
- federation.md (mechanics only) — HOW to use channels
- Augmentation skill (behavioral guidance + proficiency + self-check) — 
  WHAT to do and WHY

Changes in `cognitive_agent.py`:
- Remove the `_get_comm_proficiency_guidance()` injection block at line 1319
- `_frame_task_with_skill()` gains optional `proficiency_context: str = ""`
  parameter — rendered as `<proficiency_tier>` inside the XML
- Caller at WR notification path passes proficiency guidance from
  `_get_comm_proficiency_guidance()` into `proficiency_context`
- `_get_comm_proficiency_guidance()` method itself is NOT deleted — it 
  still returns the text, it's just injected via the skill frame instead 
  of as a standalone system prompt section

### 7. Address Specific Anti-Patterns

Add to the SKILL.md operating sequence, between steps 6 and 7:

```markdown
6b. Write your opening sentence. If it begins with any of these patterns,
    delete it and start with your conclusion instead:
    - "Looking at..."
    - "I notice..."
    - "I can see..."
    - "I can confirm..."
    - "From my [department] perspective..."
    These openings are process narration, not analysis. Your first sentence
    should be your finding or recommendation.
```

### 8. Self-Monitoring Marker Framing (BF-174 Root Cause)

The self-monitoring context injection in `_build_user_message()` uses
bracket markers (`[COGNITIVE ZONE: AMBER]`) and plain-text delimiters
(`--- Your Recent Activity (self-monitoring) ---`). These look like content
to the LLM, which parrots similar bracket patterns in its output.

**Action:** Reframe self-monitoring context injection at
`cognitive_agent.py:2800-2884` to use XML tags:

**Before:**
```
[COGNITIVE ZONE: AMBER]
--- Your Recent Activity (self-monitoring) ---
```

**After:**
```xml
<system_telemetry type="self-monitoring">
<cognitive_zone>AMBER</cognitive_zone>
<recent_activity>
...
</recent_activity>
</system_telemetry>
```

This addresses the root cause: XML tags are recognized as structural
markup by Claude, not content to be echoed. The BF-174 regex strip in
`proactive.py` (`_strip_bracket_markers`) is RETAINED as defense-in-depth
but should fire far less frequently.

Changes in `cognitive_agent.py`:
- `_build_self_monitoring_section()` or inline code at lines 2800-2884 —
  replace bracket/plain-text markers with XML tags
- Specifically: `[COGNITIVE ZONE: ...]` → `<cognitive_zone>...</cognitive_zone>`
- `--- Your Recent Activity ---` → `<recent_activity>...</recent_activity>`
- `--- Notebook: {topic} ---` → `<notebook topic="...">`
- `[Source awareness: ...]` → `<source_awareness>...</source_awareness>`

Do NOT remove `_strip_bracket_markers()` from `proactive.py` — it remains
as defense-in-depth for any bracket patterns the LLM still generates.

## Scope Boundary

This AD addresses **skill authoring and injection effectiveness**. It does
NOT change:
- Ward Room routing logic (AD-629)
- Reply cap enforcement (AD-629)
- Proficiency tracking (AD-596c, AD-625)
- Skill catalog infrastructure (AD-596a)
- Agent personality or trust mechanics

## Files to Modify

| File | Change |
|------|--------|
| `config/standing_orders/federation.md` | Remove duplicated comm rules, keep mechanics only. Remove Theory of Mind — Complementary Contribution section (lines 112-119) → absorbed by skill |
| `config/skills/communication-discipline/SKILL.md` | Rewrite: positive framing, self-check, anti-patterns, absorb ToM complementary contribution |
| `src/probos/cognitive/cognitive_agent.py` | `_frame_task_with_skill()` → XML tag framing with `proficiency_context` param. Remove `_get_comm_proficiency_guidance()` injection from `_decide_via_llm()` (line 1319). Reframe self-monitoring context (lines 2800-2884) with XML tags |
| `src/probos/cognitive/standing_orders.py` | Tier 7 skill description → XML `<available_skills>` format with behavioral primer |
| `tests/test_ad631_skill_effectiveness.py` | New test file |

## Do NOT Change

- `ward_room_router.py` — structural enforcement is separate
- `proactive.py` — context gathering unchanged; `_strip_bracket_markers()` RETAINED
- `skill_catalog.py` — catalog infrastructure unchanged
- `comm_proficiency.py` — tier definitions and `get_prompt_guidance()` unchanged
- Any other standing order files (ship.md, department.md, etc.)

## Test Requirements

### Unit Tests (`tests/test_ad631_skill_effectiveness.py`)

1. **TestXmlFraming**
   - `test_frame_task_uses_xml_tags` — output contains `<active_skill>` tags
   - `test_frame_task_includes_name_attribute` — skill name in tag
   - `test_frame_task_context_in_tag` — context summary in `<skill_context>`
   - `test_frame_task_no_plain_text_delimiters` — no `---` delimiters
   - `test_frame_task_proficiency_context` — proficiency text in `<proficiency_tier>` when provided
   - `test_frame_task_no_proficiency_when_empty` — no `<proficiency_tier>` tag when proficiency_context is empty

2. **TestTier7Description**
   - `test_tier7_uses_xml_format` — `<available_skills>` in composed output
   - `test_tier7_includes_key_rule` — description includes behavioral primer
   - `test_tier7_skill_has_proficiency_attribute` — proficiency level in tag attribute

3. **TestFederationDedup**
   - `test_federation_no_reply_quality_section` — "Reply Quality Standard"
     heading removed from federation.md
   - `test_federation_no_communication_etiquette_section` — 
     "Communication Etiquette" heading removed
   - `test_federation_no_tom_complementary_section` — "Theory of Mind — 
     Complementary Contribution" heading removed
   - `test_federation_keeps_mechanics` — `[REPLY thread_id]`, `[ENDORSE]`,
     `[DM @callsign]` format examples still present
   - `test_federation_keeps_channel_descriptions` — Ward Room, DM, Notebook
     sections still present

4. **TestSkillContent**
   - `test_skill_has_pre_submit_check` — "Pre-Submit Check" section exists
   - `test_skill_no_negative_framing` — no "Never" or "Do not" as sentence
     starters (allow mid-sentence usage)
   - `test_skill_addresses_looking_at_pattern` — "Looking at" mentioned as
     anti-pattern
   - `test_skill_has_tom_complementary_section` — Theory of Mind guidance
     absorbed into skill

5. **TestCommProficiencyConsolidation**
   - `test_decide_via_llm_no_standalone_comm_guidance` — `_decide_via_llm()` 
     no longer injects `_get_comm_proficiency_guidance()` as standalone 
     system prompt section
   - `test_comm_guidance_flows_through_skill_frame` — proficiency guidance
     appears inside `<proficiency_tier>` in the user message skill injection

6. **TestSelfMonitoringXml**
   - `test_self_monitoring_uses_xml_tags` — cognitive zone rendered with
     `<cognitive_zone>` not `[COGNITIVE ZONE:]`
   - `test_recent_activity_uses_xml` — activity section uses `<recent_activity>`
     not `--- Your Recent Activity ---`
   - `test_bracket_strip_retained` — `_strip_bracket_markers()` import still
     exists in `proactive.py` (defense-in-depth)

### Existing test verification

```
pytest tests/test_ad631_skill_effectiveness.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad626_skill_activation.py -v
pytest tests/ -k "standing_orders" --tb=short
```

## Verification Checklist

- [ ] Federation.md no longer duplicates skill content
- [ ] Theory of Mind — Complementary Contribution removed from federation.md
  and absorbed into skill
- [ ] Skill uses positive framing with reasoning throughout
- [ ] Self-verification gate present in skill
- [ ] XML tags used for skill injection framing (`<active_skill>`)
- [ ] Tier 7 descriptions use XML format (`<available_skills>`) with
  behavioral primer
- [ ] `_get_comm_proficiency_guidance()` no longer injected as standalone
  system prompt section — flows through `<proficiency_tier>` in skill frame
- [ ] Self-monitoring context uses XML tags, not bracket markers
- [ ] `_strip_bracket_markers()` RETAINED in proactive.py (defense-in-depth)
- [ ] "Looking at..." anti-pattern explicitly addressed
- [ ] Existing tests still pass (AD-625, AD-626, standing_orders)
- [ ] No communication instruction appears in both federation.md AND skill

## Research References

- Anthropic prompt engineering: XML tags recommended for structured prompts
- Anthropic skill-creator: "slightly pushy" descriptions prevent undertriggering
- Anthropic model guidance: "Tell Claude what to do instead of what not to do"
- Anthropic Opus 4.6 guidance: avoid ALL-CAPS urgency, use normal imperative
- MRKL (AI21 Labs): modular neuro-symbolic — validates deterministic gates
  alongside LLM judgment (Karpas et al. 2022)
- Lipenkova 2023: "Setting domain knowledge in stone can be an efficient
  approach to increase precision" — validates structural enforcement
- AgentSkills.io spec: XML wrapping for skill content, protect from compaction
