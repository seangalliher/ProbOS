# The Primacy of Perception: Absorption

*Sean Galliher, 2026-11-02*
*Source: Maurice Merleau-Ponty, *The Primacy of Perception*, a collection of essays edited by James M. Edie (Northwestern University Press, 1964). Drafted from general knowledge of the essays, without a copy at hand, so nothing is quoted. The ProbOS side was checked against `main` at `b773c662` on 2026-11-02.*

## Purpose

The Captain asked which ideas from the book ProbOS could absorb. Its central claim is that knowledge rests on perception, a direct and embodied contact with the world, and that reflection, models and science are built on that contact rather than replacing it. This note records which of the book's ideas ProbOS already holds, which give a concrete next step, and which are only a lens. These are design references only. Nothing here changes behaviour or authorizes a build.

## Already in ProbOS

Much of the book's central idea, that how something is known matters as much as what is known, is already built under other names:

- **How a memory was acquired.** `MemorySource` (`types.py:492`, AD-541) marks an episode `direct`, `secondhand`, `ship_records`, `briefing` or `reflection`. The recall prompt shows `[direct]` / `[secondhand]` and `[verified]` / `[unverified]` markers (legend at `cognitive_agent.py:10238`, header rendered at `:10267`).
- **Grounding.** `AnchorFrame` (`types.py:502`, AD-567a) ties each episode to when, where, who and why, following Johnson's source-monitoring framework.
- **Hearsay that loops back.** AD-567f's social verification (`cognitive/social_verification.py`) detects cascade confabulation, which intelligence analysts call circular reporting.
- **Provenance on retrieved context.** AD-677's `ProvenanceTag` (`cognitive/provenance.py`) marks Oracle results with source tier, relevance and age. It is constructed only for Oracle results (`provenance.py:87`); the docstrings at `provenance.py:71` and `memory_transparency.py:5` describe uses that do not exist.
- **Coherence over volume.** The ambient-awareness design (`docs/research/ambient-awareness-optimal-working-memory.md` §5.3) already takes the book's figure-and-ground point: context is a structured field, not a pile.
- **The live system over the document.** "Live-system claims must come from the live system" (CLAUDE.md), and the 7-day live shadow period in AD-1346 M3's exit evidence (#1604, under the epic #1601).

## Absorbed

### 1. A partial view says what lies beyond it

**The idea.** A thing is only ever seen from one side. Perception carries an implicit sense of the sides it cannot see, which is why a partial view is not mistaken for the whole thing.

**Prior art in ProbOS.** Page reads already do this. `PageReaderAgent` prints "characters {start} to {end} of {total}" and the next `offset=` (`agents/utility/web_agents.py:139-149`; the agent is defined at `:641`, and its `read_page` descriptor is at `:654`). The browser tool's page output ends with `[truncated: N characters elided ...]` (`agentic_dispatch.py:204`, applied by `_bound_browser_output` at `:404-435`). The builder marks `[lines X-Y omitted]` (`cognitive/builder.py:2296`, `:2301`), and AD-1240's pointer frame names the saved result.

**Where ProbOS falls short.** The file and result tools have no such convention. A `read_file` call with `offset` and `limit` returns only the slice, with nothing saying how much of the file lies outside it (`cognitive/swe_harness/tools.py:483-488`). The same holds for the verified-read path and the workspace-slice path (`_workspace_slice_result`, `tools.py:379-393`). The total is already known and then dropped: `SourceRef.total_lines` (`execution/workspace_results.py:183`), and `len(lines)` on the sliced path. BF-946 (#1723) shows the cost: Forge's read-back of a saved result asked for a slice over the 6,000-character recovery bound named in #1723, which ended the turn. The Captain decided R-a on #1723 (2026-11-02): a promised read over the bound will return an error naming the bound. That fix is not on `main` yet.

**What to absorb.** Extend the page-read convention to every partial result: state the part shown and the whole it comes from ("lines 1–200 of 1,450", "40 of 190 rows", "the first 6,000 of 48,213 characters") and how to get the rest. The agent then plans its next read from facts, not from a guess. For `read_file` this is a rendering change, since the total is already computed.

*Owner: a follow-up to BF-946 (#1723), starting with `read_file` and the read-only tools.*

### 2. What the agent observed this turn outranks what it remembers

**The idea.** For Merleau-Ponty, perceiving comes first. Memory, testimony and inference build on it and are weaker in proportion to their distance from it.

**Where ProbOS falls short.** `MemorySource` grades memories, and AD-677 grades Oracle results, but the strongest source an agent has is not marked: what its own tool calls returned *in this turn*. A tool result and a recalled episode about the same fact reach the model with no stated order between them (no precedence rule found by search; a rendered prompt was not inspected). AD-677's own decision text names this distinction ("sensor-derived facts ... LLM-inferred conclusions ... hearsay via Ward Room"); the built tag covers Oracle tiers only.

**What to absorb.**
- Mark this turn's tool observations as the top source, above `direct` memory, and tell the agent that a fresh observation overrides a conflicting recollection.
- A question to check, not a finding: whether an agent's own conclusion from a turn can be stored as a `direct` episode. If it can, an inference later comes back as an experience. That is how a confabulation starts before it spreads, which AD-567f and AD-583 (wrong convergence) catch only later, once it has.

*Owner: AD-1302 (#1355). Its S1 build prompt (PR #1735, open, not built) plans to record which Ship's Records entries an agent was shown, by revision. Observation in the current turn is the same kind of record, one step closer to the source.*

### 3. A tool becomes part of the body through use

**The idea.** The book's example is a blind man's cane. With practice he stops attending to the cane and feels the pavement through its tip. A skill is a habit of the body, not a rule consulted each time.

**Where ProbOS stands.** Every run presents each tool's full definition (AD-983a: the tool carries its manual). AD-1189 can withhold large definitions behind `load_tools` (`agentic_tools.deferred_tool_schema_threshold_bytes`, off by default), but it decides by size, and its decision record rejects per-tool keep lists "for lack of evidence" (`DECISIONS.md:11236`). The raw evidence exists. When an event log is wired, each tool call emits a durable `TOOL_INVOKED` event (`tools/executor.py:1182-1240`; durable at `event_persistence.py:86`, `:103`; capped at 500 per run, `executor.py:77`, AD-1224). The fallback record carries the raw agent id, tool id, `is_error` and `error_category` (`executor.py:981-1020`). Effect-governed calls carry digests of the agent and tool and a reason code instead (`_strict_tool_record`, `executor.py:1040-1098`). Skills have a per-agent count (`AgentSkillRecord.exercise_count`, `skill_framework.py:617-630`). What does not exist is an aggregate record of how well each agent uses each tool, and the Hebbian graph has no agent-to-tool edges (`tools/skill_tool_resolver.py:53-58`).

**What to absorb.** A tool counts as *incorporated* for an agent when that agent has used it correctly many times without an error caused by misuse. Misuse needs a mapping, since no single category names it; `invalid_params` and `ambiguous_tool` (`ERROR_CATEGORIES`, `executor.py:328-332`) are the obvious members. Aggregated from `TOOL_INVOKED` (digests are stable, so both record shapes aggregate), that is the evidence AD-1189 lacked. An incorporated tool's definition could then shrink to its one-line manifest entry for that agent, while an unfamiliar tool keeps its full manual. This is also earned agency at the level of tools, and it fits AD-1342 ("the harness is the body; ProbOS is the self"): what a crew member has learned to use belongs to the crew member, whatever body it uses.

*Owner: AD-1189, as evidence for a later per-agent policy. It needs an aggregate over the existing events, not a new store; today an offer is run-local and nothing persists. `TOOL_INVOKED` retention was not checked.*

### 4. Not knowing is a legitimate state

**The idea.** Perception tolerates ambiguity, and forcing a definite answer distorts what was seen.

**What to absorb.** Treat *indeterminate* as an answer agents are expected to give, not a failure to avoid. AD-592's confabulation guard points this way, and AD-1302 S1's build prompt plans an `unknown` outcome (not built). An agent that says "I can't tell from what I have" should never score worse than one that fills the gap.

*Owner: AD-1302, and the epistemic-degradation work generally.*

## A lens, not a build

- **Self and others are told apart gradually.** On the book's account, a child begins in an undifferentiated sociability and only gradually separates its own view from others'. Cold-start crew may show a similar phase, echoing one another before they speak in their own voice (an observation from the Captain's sessions, not measured). AD-638's boot camp (#271, closed) is where this would apply if a later revision shapes its stages.
- **Thinking that works only on models loses contact with the world.** "Eye and Mind" makes this criticism of science that operates on models. ProbOS already guards against it by requiring live evidence. This note does not use it to argue for any change to the review loop.

## Rejected

- **A full phenomenological account of agent experience.** Rejected. It adds vocabulary without a testable change, and it would risk claims about agent experience that ProbOS's trial-disclosure and Westworld principles keep honest.

## Consistent with existing ProbOS principles

Each item strengthens grounding without weakening a control:
- Partial results that state their size bring nothing over the bound into context.
- Ranking observation above memory is a label, not a new permission.
- Incorporation changes only how much of a tool's manual is presented, never whether the tool may be used.
