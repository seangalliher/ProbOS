# Gibson's Affordances: Absorption

*Sean Galliher, 2026-11-02*
*Source: James J. Gibson, *The Ecological Approach to Visual Perception* (1979), chiefly the chapter on affordances; and Don Norman's later distinction between an affordance and a signifier (*The Design of Everyday Things*, revised edition, 2013). Drafted from general knowledge of both, without a copy at hand, so nothing is quoted. The ProbOS side was checked against `main` at `b773c662` on 2026-11-02 and re-checked at `f31afa56` on 2026-11-03. A companion to `primacy-of-perception-absorption.md` (PR #1738, not yet merged).*

## Purpose

The Captain asked for authors related to Merleau-Ponty that ProbOS could absorb, and chose Gibson first. Gibson coined "affordance": what the environment offers an animal, for good or ill. An affordance is a fact about the pair, not about either side alone. A step affords climbing to an adult and not to an infant. Gibson held that affordances are perceived directly, from the structure of the environment, not inferred from a description of it.

ProbOS already uses the word (`docs/development/capability-affordance-layer.md`, AD-983). This note records where Gibson's meaning agrees with that design, where it corrects it, and the concrete gap the correction exposes. These are design references only. Nothing here changes behaviour or authorizes a build.

## Already in ProbOS

- **The tool carries its manual.** The principle is `capability-affordance-layer.md` §2: a tool's description reaches whoever holds it, instead of living in one agent's standing orders. AD-983a's mechanism renders each tool's `usage_hint` into the conversational capability block (`cognitive/cognitive_agent.py:3101-3135`).
- **Exploring for affordances.** Gibson's perceiver moves to find out what the environment offers. AD-1072's `search_capabilities` lets an agent look for a tool it does not yet know; it is registered only while `agentic_tools.tool_search_enabled` is set (`cognitive/agentic_dispatch.py:3339-3354`; default off, on in `config/system.yaml`). AD-1189's `load_tools` fetches a withheld definition on request, when `deferred_tool_schema_threshold_bytes` is above 0 (default off), using AD-983d's `CapabilityRetriever` (`cognitive/tool_manifest.py:249`).
- **Signals that already name what is available.**
  - Plan mode tells the agent its list holds read-only tools only (`cognitive/agent_mode.py:90-91`) and filters the offer to match (`agentic_dispatch.py:3603-3605`).
  - The browser's read-only description names its actions (`agentic_dispatch.py:636-642`), and its refusal names the actions that are available (`:198-202`).
  - Under agent-work confinement, a call to an unregistered tool is refused with "Use search_capabilities to find a registered tool for this step" (`UNREGISTERED_TOOL_REFUSAL`, `agentic_dispatch.py:320-323`).
- **Other crew as affordances.** Gibson counted other animals among the richest affordances. AD-600's expertise directory (`cognitive/expertise_directory.py`) routes a question to the agent who knows the answer, the mechanism psychology calls transactive memory.

## Where Gibson corrects the design

`capability-affordance-layer.md` §2 states, as a load-bearing property, that affordances "travel with the capability, not with the agent." For the *manual* that is right: how to call `read_file` is the same for everyone. For the *affordance* it is the opposite of Gibson. What a tool offers depends on who holds it and where:

- **Rank and grants.** The same tool is granted to one rank and not another.
- **The run's context.** Under agent work, a tool is either *routine*, so the call runs, or not, so the call is filed for approval or refused (`agent_work_runner.py:611-616`).
- **The ship's settings.** `read_file` and `codebase_read_source` are routine only while `security_infra.read_roots` is set, and critical otherwise (`tools/effect_tiers.py:29-32`, `:41-49`).

Norman's later vocabulary makes the split usable. The *affordance* is the action really available to this agent here. The *signifier* is what tells the agent so. Plan mode and the browser signal well. Agent work does not.

## Absorbed

### 1. Tell the agent which actions it can take directly

**The gap.** An agent-work run is offered the agent's usual tools, whole (`agentic_dispatch.py:3606-3608`). Each call's tier is decided only at the call, by membership in the run's routine set (`agentic_dispatch.py:848`). `tools/effect_tiers.py` is read in one place, `agent_work_runner.py:612`. Nothing the agent sees names that set:
- The task text says "Routine reads run directly. A call to another tool may be filed for approval instead of running" (`agent_work_runner.py:228-229`). The word "reads" misleads. `list_files` and `find_mcp_tool` are reads, yet they are elevated (`effect_tiers.py:33-38`), so an agent that trusts the sentence expects them to run.
- The refusal after a filed call says "Finish what the read-only tools allow" (`CONFINED_CALL_FILED`, `agentic_dispatch.py:305-309`), again without naming them.

AD-1356's slices tier the decision. None of them, as filed on #1722, tells the agent its tiers before it acts.

**What it cost.** On 2026-10-31, agents in agent work called tools that were not routine and had no way to see that beforehand. The calls went to the Captain as approval requests: `list_files("**/*.py")` four times from one item, `find_mcp_tool` repeatedly, and five one-line `run_python` clock reads from five agents among the 16 requests pending at 19:21 (BF-947, #1724). Under today's table those are still elevated, elevated and critical. Gibson's point, in ProbOS terms: an action the agent cannot perceive as unavailable will be attempted, and a refusal after the fact is the costliest place to learn it.

**What to absorb.** Make the run's affordances perceivable before the first call:
- name, in the task text, the routine tools that are offered to this run: the confinement's frozenset intersected with the run's offered tool ids (`agentic_dispatch.py:3583-3591`);
- replace "Routine reads run directly" with that list;
- in each tool definition offered to an agent-work run, or in one line beside it, mark a non-routine tool as "files for approval";
- in `CONFINED_CALL_FILED`, list the routine tools instead of "the read-only tools".

The gate stays authoritative. This changes what the agent is told, never what it may do.

**Why the signal must intersect with the offer.** The confinement holds the whole routine table (13 tools; `agent_work_runner.py:611-615`). That is deliberate: S2's contract (decision D2 on #1722) keeps the set table-wide and decides at each call whether the agent holds the tool. A signal taken from the set alone would therefore name tools the agent does not hold. Likewise, `list_files` is elevated by S2's decision D4, because it resolves its path without the read policy (`DECISIONS.md:1274`), although the issue's first table listed it as routine.

*Owner: AD-1356 (#1722). Posted there as input for S3 on 2026-11-03.*

### 2. Measure each agent's niche, not only its grants

**The idea.** Gibson defined an animal's niche as the set of affordances it actually uses, as distinct from the habitat, which is everything around it.

**In ProbOS.** Grants describe the habitat. The niche can be measured from two records:
- **Calls that ran.** Each call that reaches the registry emits a durable `TOOL_INVOKED` event when an event log is wired (`tools/executor.py:1182-1240`). The record's fields are described in `primacy-of-perception-absorption.md` §3.
- **Calls that did not.** A call that confinement files or refuses returns before the registry (`agentic_dispatch.py:847`, `:852`) and writes no `TOOL_INVOKED` record. Filed calls are in the capability-request store. Refused calls reach the loop as error results, so they appear in the per-run durable tool trace (AD-1151, `_persist_tool_trace`, `agentic_dispatch.py:4426`), though not in `TOOL_INVOKED`. Counting them per agent needs an aggregate over that trace (read from the code, not run).

Compared per agent, grants against these give two lists:
- **granted and never used**: candidates for removal under least privilege;
- **attempted and filed or refused**: candidates for a grant, a routine entry, or a better signal (item 1).

*Owner: input for AD-1356 S4's per-tier settings and its earned-agency bar (paused), and for AD-983b's per-agent enablement. Tracked as a proposal on #1743.*

### 3. Every refusal names what is available instead

**The idea.** For Gibson, a perceiver learns the layout from what it can and cannot do. A wall is perceived as a barrier and, at the same time, as a guide to the way around it.

**In ProbOS.** The browser refusal and `UNREGISTERED_TOOL_REFUSAL` already do this. Make it the rule for every refusal an agent receives: say what was refused, why, and the nearest action that is available, and name only actions this agent actually has. `UNREGISTERED_TOOL_REFUSAL` shows why the last clause matters: it names `search_capabilities` unconditionally, so with `tool_search_enabled` off it points to a tool that is not registered. Refusals of calls that never ran are already kept out of the defect record (`_NEVER_RAN_REFUSALS`, `agentic_dispatch.py:331-334`). This item is about the agent's next step, not the record.

*Owner: a convention for refusal text. The agent-work refusals in `agentic_dispatch.py:301-325` are in the #1722 S3 input; the rest is a proposal on #1743.*

## A lens, not a build

- **The environment designed for the perceiver.** Gibson and Norman both treat the environment as something designed for its users. ProbOS designs its environment for crew: tool names, schemas, refusal text, Ship's Records. A useful review question for any new tool is "what will an agent believe this offers, from its name and first line alone?"
- **Direct perception against inference.** Gibson argued that perceivers pick up what the environment offers without building an internal model first. Language models have no direct perception, but the design lesson carries over: put what an action offers where the agent meets it, not in a manual it must read and reason from.

## Rejected

- **Hiding non-routine tools from agent-work runs.** Rejected as the first step, although plan mode does exactly this. It would give the strongest signal, but some filed calls are legitimate and approved, and BF-947 just made approved calls work. Marking the tools keeps them reachable through the gate.

## Consistent with existing ProbOS principles

- The gate stays the only authority. The signal is computed at run start from the gate's set and the offer. It can still go stale: the offer can change mid-run (BF-755), and the gate runs a routine tool the agent was not offered.
- Nothing widens what an agent may do.
- Fewer blind attempts means fewer approval requests, which is AD-1356's goal: the Captain decides by exception.
