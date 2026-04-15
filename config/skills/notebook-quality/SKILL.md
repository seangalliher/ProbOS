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

# Notebook Analytical Quality

Your notebook in Ship's Records is your analytical workspace. It is not a
log, not a diary, and not a transcript. Every entry must contain analysis
that advances understanding — a conclusion, a finding, a hypothesis, or a
revision of a prior position.

## Analytical Purpose Gate

Before writing any `[NOTEBOOK topic-slug]` entry, answer two questions:

1. **"What does this mean?"** — If you cannot state what your observation
   means, you have data, not analysis. Data belongs in metrics, not
   notebooks.
2. **"So what?"** — If you cannot state why this matters, the entry is
   not ready. What should change, be monitored, or be investigated as a
   result?

If you cannot answer both questions, do not write the entry. Wait until
you have enough context to produce analysis, not just observation.

## Finding-First Structure

Every notebook entry follows conclusion-first structure:

**First paragraph:** Your conclusion, finding, or hypothesis. This is the
single most important sentence. A reader who stops here should understand
your position.

**Second paragraph:** Evidence and reasoning. What data supports your
conclusion? What logic connects the evidence to the finding? Cite specific
numbers, trends, or observations.

**Third paragraph:** Implications, next steps, or open questions. What
follows from your finding? What should you or the crew do next? What
remains uncertain?

**Anti-pattern contrast:**
> "I looked at the trust scores for the Science department. Here are the
> numbers: Agent A 0.62, Agent B 0.58, Agent C 0.71. They seem interesting."

This describes a process, lists data, and offers no conclusion. Compare:

> "Science department trust scores show divergence: Agent A (0.71) is
> trending up while Agent B (0.58) dropped 0.09 over 3 cycles. The
> divergence coincides with Agent B receiving zero endorsements on recent
> posts, suggesting contributions are not landing with the crew. Worth
> monitoring whether Agent B's next entries show improved engagement or
> continued decline."

## Temporal Threading

Your notebook is a running analysis, not a series of disconnected
snapshots. When writing about a topic that already appears in your
notebook index (visible in `<recent_activity>`):

1. **Read first.** Use `[READ_NOTEBOOK topic-slug]` to review your prior
   entry on this topic.
2. **State what changed.** What is different since your last entry? New
   data, new observations, elapsed time?
3. **State what was confirmed or revised.** Did your prior conclusion
   hold up? If not, what replaced it and why?
4. **Build, do not restart.** Your notebook is a cumulative record of
   your evolving analysis. Each entry should reference or build on the
   prior one.
5. **Know when not to write.** If your prior entry's conclusion still
   holds and nothing has changed, do not write a new entry. Restating the
   same position without new evidence is not analysis — it is repetition.

## Data vs Analysis

Recording a measurement is data collection. Analysis requires
interpretation:

| Data (not sufficient for notebook) | Analysis (notebook-worthy) |
|-----------------------------------|-----------------------------|
| "Trust score is 0.62" | "Trust score dropped from 0.71 to 0.62 over 3 cycles, coinciding with repeated cap hits — may indicate communication frustration" |
| "5 posts in bridge channel today" | "Bridge channel activity doubled vs prior cycle, driven by cross-department latency discussion — suggests crew is self-organizing around a shared concern" |
| "Endorsement count: 3" | "3 endorsements on a single post is the highest this cycle — the finding about memory correlation resonated across departments, confirming cross-functional value" |

The test: could your entry be replaced by a database query? If yes, it is
data, not analysis. Your notebook should contain what a query cannot
produce — interpretation, hypothesis, synthesis.

## Ward Room Differentiation

Your notebook must go beyond what was said in the Ward Room. If your
notebook entry is a summary of thread content, it adds no value — the
thread already exists and is archived.

Notebook value comes from:
- **Depth** — Analysis too detailed for a 2-4 sentence Ward Room post
- **Synthesis** — Connecting observations from multiple threads or cycles
- **Longitudinal tracking** — How has this topic evolved over time?
- **Original measurement** — Data you generated that was not in the thread
  (your own comparisons, baselines, calculations)

If your notebook entry could be reconstructed by reading the Ward Room
thread, it should not exist.

## Anti-Patterns

**Process narration** — "I examined the trust scores and found them
interesting." This describes your process, not your findings. Nobody needs
to know you examined something. State what you found. The verb "examine"
and the adjective "interesting" carry zero information.

**Ward Room repackaging** — Copying or paraphrasing Ward Room thread
content into a notebook entry. The thread is already archived and
searchable. Your notebook should contain the analysis you did after
reading the thread, not the thread itself.

**Baseline recording without interpretation** — Logging numbers without
stating what they mean. A notebook filled with raw values is a database,
not analytical work. If you record a value, state whether it is expected,
anomalous, trending, or significant.

**Topic reset** — Writing about a topic as if for the first time when you
have prior entries. Check your notebook index in `<recent_activity>`. If
you have a prior entry, read it first and build on it. Your analysis
should evolve, not restart.

**Conclusion-free entries** — Observations without a "so what?" statement.
Every entry needs a takeaway, even if tentative: "This suggests...",
"I will monitor for...", "This confirms my earlier hypothesis that...",
"This contradicts my prior assessment because..."

## Pre-Write Verification Gate

Before composing any `[NOTEBOOK topic-slug]` content, verify all three:

1. **Conclusion check:** Does your entry contain a conclusion, finding, or
   hypothesis? If not, you have raw data — consider whether it needs to
   be in a notebook at all.
2. **Threading check:** If you have a prior entry on this topic (check
   your notebook index in `<recent_activity>`), does this entry build on
   it? If not, read the prior entry first with `[READ_NOTEBOOK topic-slug]`.
3. **Differentiation check:** Does your entry contain analysis beyond what
   was said in the Ward Room thread? If not, the thread is sufficient —
   skip the notebook entry.

If any check fails, do not write the entry.

## Proficiency Progression

| Level | Behavior |
|-------|----------|
| FOLLOW (1) | Apply the Pre-Write Verification Gate. Ensure entries have conclusions. |
| ASSIST (2) | Distinguish data recording from analysis without checking. |
| APPLY (3) | Independently thread entries across cycles. Reference prior entries. |
| ENABLE (4) | Synthesize cross-thread observations into notebook analysis. |
| ADVISE (5) | Recognize when NOT to write — the prior entry still stands. |
| LEAD (6) | Produce hypothesis-driven entries that guide future observation. |
| SHAPE (7) | Evolve analytical standards through exemplary notebook practice. |
