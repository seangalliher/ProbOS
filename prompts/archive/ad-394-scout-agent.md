# AD-394: ScoutAgent — Daily Intelligence Gathering

## Overview

A ScoutAgent in the Science department that searches GitHub daily for AI agent
projects relevant to ProbOS. Classifies each find as either an **absorption
candidate** (patterns/techniques to learn from) or a **visiting officer
candidate** (tool that could integrate under ProbOS command). Delivers a
formatted daily digest to Discord and posts findings as Bridge notification
cards.

This is ProbOS's first "useful for the Captain every day" feature — proving the
system isn't just architecture but a working crew that delivers intelligence.

## Architecture

### 1. ScoutAgent (CognitiveAgent)

Create `probos/cognitive/scout.py` extending `CognitiveAgent`.

**Agent identity:**
- `agent_type = "scout"`
- Department: `science`
- Pool: `"scout"` (target_size=1), added to the Science pool group
- LLM tier: `"standard"` (classification doesn't need deep/Opus)
- Callsign: "Wesley" (eager, goes exploring, reports back to the Bridge)

**Handled intents:**
- `scout_search` — Run a scout scan now (triggered by `/scout` command or
  scheduled task)
- `scout_report` — Retrieve the latest scout report (triggered by
  `/scout report`)

**Intent descriptors:**
```python
intent_descriptors = [
    IntentDescriptor(
        name="scout_search",
        description="Search GitHub for AI agent projects relevant to ProbOS — "
                    "absorption candidates and visiting officer candidates",
        example_triggers=["scout for new projects", "find AI agent repos",
                          "what's new in the agent space"],
    ),
    IntentDescriptor(
        name="scout_report",
        description="Show the latest scout intelligence report",
        example_triggers=["scout report", "show latest findings",
                          "what did the scout find"],
    ),
]
```

**perceive() override:**
1. Call GitHub REST API via `httpx` to search for repositories:
   - Query: `topic:ai-agents OR topic:llm-agents OR topic:multi-agent OR
     topic:agent-framework created:>{7_days_ago} stars:>50`
   - Also query: `topic:ai-coding OR topic:code-generation
     created:>{7_days_ago} stars:>100`
   - Sort by stars descending, limit to 20 results per query
   - Use GitHub REST API v3: `GET https://api.github.com/search/repositories`
   - No auth token required for public search (rate limit: 10 req/min
     unauthenticated, 30 req/min with token)
   - If `GH_TOKEN` env var or `gh auth token` is available, use it for higher
     rate limits
2. For each repo, fetch: `full_name`, `description`, `stargazers_count`,
   `created_at`, `updated_at`, `language`, `license.spdx_id`, `topics`,
   `html_url`
3. Filter out repos already seen (store seen repo IDs in a simple JSON file at
   `data/scout_seen.json` — append-only, prune to last 90 days on each run)
4. Build an observation dict with the list of new repos

**decide() — LLM classification:**

The system prompt instructs the LLM to classify each repo into one of:
- **absorb** — Contains a pattern, technique, or architectural idea ProbOS
  should learn from. Examples: novel agent communication patterns, interesting
  prompt engineering, benchmark methodologies, efficient context management
- **visiting_officer** — A tool/framework that could serve as an external
  agent under ProbOS command. Must pass the Visiting Officer Subordination
  Principle: can ProbOS control its context, commits, model selection, and
  trust tracking? Litmus test: can you disable its orchestration loop and use
  it purely as a capability engine?
- **skip** — Not relevant to ProbOS

For each absorb/visiting_officer classification, the LLM provides:
- `relevance` (1-5 score)
- `summary` (1-2 sentences: what it does)
- `insight` (1-2 sentences: why it matters to ProbOS, what pattern to absorb
  or how it would integrate)

**Output format** (LLM responds with structured text):
```
===SCOUT_REPORT===
REPO: owner/name
STARS: 1234
URL: https://github.com/owner/name
CLASS: absorb | visiting_officer | skip
RELEVANCE: 3
SUMMARY: One-line description of what this project does.
INSIGHT: Why this matters to ProbOS — pattern to absorb or integration path.
===END===

===SCOUT_REPORT===
...
===END===
```

**act() override:**
1. Parse the `===SCOUT_REPORT===` blocks from LLM output
2. Filter to only `absorb` and `visiting_officer` classifications with
   relevance >= 3
3. Sort by relevance descending
4. Build the report data structure:
```python
@dataclass
class ScoutFinding:
    repo_full_name: str
    stars: int
    url: str
    classification: str  # "absorb" | "visiting_officer"
    relevance: int       # 1-5
    summary: str
    insight: str
    language: str
    license: str
    topics: list[str]
```
5. Store the report in `data/scout_reports/YYYY-MM-DD.json`
6. Post Bridge notifications for top findings (relevance >= 4)
7. Format and deliver Discord digest

**report() override:**
Return the formatted report as the intent result text.

### 2. Discord Digest Delivery

After `act()` completes, deliver the digest to Discord:

**Delivery mechanism:** Use the runtime's Discord adapter directly:
```python
adapter = self._runtime.channel_adapters.get("discord")
if adapter and adapter.running:
    await adapter.send_response(channel_id, digest_text)
```

**Channel configuration:** Add `scout_channel_id` to the Discord config in
`system.yaml`:
```yaml
channels:
  discord:
    scout_channel_id: 0  # Discord channel ID for scout reports
```

Add the field to `DiscordConfig` in `config.py`:
```python
scout_channel_id: int = 0
```

If `scout_channel_id` is 0 (unconfigured), skip Discord delivery silently.

**Digest format:**
```
**ProbOS Scout Report — {date}**

**ABSORB CANDIDATES:**
{for each absorb finding, sorted by relevance:}
- **{repo_full_name}** ({stars} stars, {language}, {license})
  {summary}
  *Insight:* {insight}
  {url}

**VISITING OFFICER CANDIDATES:**
{for each visiting_officer finding, sorted by relevance:}
- **{repo_full_name}** ({stars} stars, {language}, {license})
  {summary}
  *Integration:* {insight}
  {url}

{total_count} findings | Full report on Bridge
```

### 3. Bridge Notification Cards

For findings with relevance >= 4, post a notification via the notification
queue:

```python
self._runtime.notification_queue.notify(
    agent_id=self.agent_id,
    agent_type="scout",
    department="science",
    title=f"Scout: {finding.repo_full_name}",
    detail=f"[{finding.classification}] {finding.summary}",
    notification_type="info",
    action_url=finding.url,
)
```

### 4. Scheduling

Register a daily scout scan using the `TaskScheduler`:

In `runtime.start()`, after the scout pool is created:
```python
if self.config.channels.discord.scout_channel_id:
    self.task_scheduler.schedule(
        text="/scout",
        delay_seconds=60,            # first run 60s after startup
        interval_seconds=86400,      # then every 24 hours
        channel_id=str(self.config.channels.discord.scout_channel_id),
    )
```

The `/scout` command (slash command) triggers the `scout_search` intent.

### 5. Slash Command

Register `/scout` in `shell.py`:

**COMMANDS dict entry:**
```python
"scout": "Run scout intelligence scan (/scout) or view report (/scout report)",
```

**_dispatch_slash() handler:**
```python
"scout": lambda args: self._dispatch_intent("scout_report" if args.strip() == "report" else "scout_search", args),
```

### 6. Crew Profile

Create `config/standing_orders/crew_profiles/scout.yaml`:
```yaml
agent_type: scout
callsign: Wesley
department: science
role: officer
personality:
  traits:
    - curious
    - thorough
    - concise
  communication_style: briefing
  formality: professional
standing_orders: |
  You are the Scout, a Science department officer responsible for daily
  intelligence gathering. Your mission is to find GitHub projects in the
  AI agent space that are relevant to ProbOS.

  CLASSIFICATION CRITERIA:
  - ABSORB: Contains a pattern, technique, or architectural concept ProbOS
    should learn from. Focus on: agent communication, context management,
    trust/safety patterns, multi-agent orchestration, developer experience.
  - VISITING OFFICER: A tool that could integrate under ProbOS command.
    Must pass the Subordination Principle — ProbOS must be able to control
    context, commits, model selection, and trust tracking. If the tool
    manages its own orchestration loop, it is a competing captain, not crew.
  - SKIP: Not relevant. Most repos will be skips.

  QUALITY STANDARDS:
  - Only surface findings with relevance >= 3
  - Be concise — the Captain reads these over coffee
  - Include the "so what" — why should the Captain care?
  - Don't repeat projects already reported (check seen list)
```

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `src/probos/cognitive/scout.py` | ScoutAgent — CognitiveAgent for GitHub intelligence gathering |
| MODIFY | `src/probos/runtime.py` | Register scout template, create pool, add to Science group, schedule daily scan |
| MODIFY | `src/probos/shell.py` | Add `/scout` slash command (COMMANDS dict + _dispatch_slash handler) |
| MODIFY | `src/probos/config.py` | Add `scout_channel_id` to `DiscordConfig` |
| MODIFY | `config/system.yaml` | Add `scout_channel_id: 0` default |
| CREATE | `config/standing_orders/crew_profiles/scout.yaml` | Crew profile with classification standing orders |
| CREATE | `tests/test_scout.py` | Unit tests for ScoutAgent |

## Acceptance Criteria

1. `ScoutAgent` extends `CognitiveAgent` with `agent_type = "scout"`
2. `perceive()` calls GitHub REST API to search for recent AI agent repos
3. `decide()` classifies repos as absorb/visiting_officer/skip with relevance scores
4. `act()` parses LLM output, filters to relevance >= 3, stores report JSON
5. Discord digest is delivered to configured `scout_channel_id` (if set)
6. Bridge notifications posted for findings with relevance >= 4
7. `/scout` command triggers immediate scan; `/scout report` shows latest
8. Daily schedule registered via TaskScheduler (24-hour interval)
9. Seen repos tracked in `data/scout_seen.json` to avoid duplicates
10. Scout pool registered in Science pool group
11. Crew profile created with classification standing orders
12. No errors when Discord is not configured (graceful skip)

## Test Requirements

Create `tests/test_scout.py`:

1. **parse_scout_report** — verify `===SCOUT_REPORT===` block parsing extracts
   all fields correctly
2. **classify_absorb** — mock LLM output with absorb classification, verify
   ScoutFinding has correct classification
3. **classify_visiting_officer** — same for visiting_officer
4. **filter_by_relevance** — verify findings below relevance 3 are filtered out
5. **seen_tracking** — verify seen repos are persisted and duplicates are
   skipped on subsequent runs
6. **discord_format** — verify digest text formatting (markdown, sections,
   counts)
7. **notification_threshold** — verify only relevance >= 4 findings generate
   Bridge notifications
8. **graceful_no_discord** — verify no error when Discord adapter is absent
   or scout_channel_id is 0

## Do NOT Build

- **Do NOT** add Slack/Teams/other channel delivery — Discord only for now
- **Do NOT** add web scraping or HN/blog sources — GitHub only for v1
- **Do NOT** modify any CognitiveAgent base class logic
- **Do NOT** add persistent task scheduling — TaskScheduler is in-memory only
  (persistence is Phase 25)
- **Do NOT** add automatic absorption or integration — the Scout reports, the
  Captain decides
- **Do NOT** use emoji in any output
- **Do NOT** add new store fields or HXI components — use existing notification
  system
