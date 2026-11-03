# Clark and Chalmers' Extended Mind: Absorption

*Sean Galliher, 2026-11-02*
*Source: Andy Clark and David Chalmers, "The Extended Mind" (*Analysis*, 1998), and Clark's *Supersizing the Mind* (2008). Drafted from general knowledge of both, without a copy at hand, so nothing is quoted. The ProbOS side was checked against `main` at `b773c662` on 2026-11-02. A companion to `primacy-of-perception-absorption.md` (PR #1738) and `gibson-affordances-absorption.md`.*

## Purpose

The Captain asked for authors related to Merleau-Ponty whose ideas would most improve ProbOS. Clark and Chalmers argue that a mind can extend into the world. Their example is Otto, who has memory loss and keeps what he needs in a notebook. When Otto checks his notebook for an address, the notebook does the work memory does for anyone else, so it counts as part of his memory. They call this the parity principle: if an outside resource does the job an inner process would do, treat it the same way.

They also say when an outside resource qualifies. In paraphrase, and without their numbering:
- **Reliably there:** it is present and routinely consulted.
- **Easy to get at:** what it holds is available when needed.
- **Trusted on retrieval:** what it says is believed without fresh checking.
- **Endorsed by its owner:** it holds what it does because its owner put it there.

ProbOS crew keep notebooks in Ship's Records, and the ship keeps a shared record. This note asks how well each meets those conditions, and where trust without checking becomes a hazard. These are design references only. Nothing here changes behaviour or authorizes a build.

## Already in ProbOS

- **Otto's notebook, for every crew member.** Ship's Records (AD-434, `knowledge/records_store.py`) holds each agent's notebook at `notebooks/{callsign}/{topic}.md`. Any crew agent can save to it, from a Captain DM (AD-911, AD-912; `cognitive_agent.py:3226`) or on the proactive path.
- **Reliably there.** For agents at AUTONOMOUS or UNRESTRICTED agency, each proactive cycle shows the notebook index, with each topic's last update (`cognitive_agent.py:9404-9414`, `:11311-11317`; built at `proactive.py:2765-2807`, gated at `:2611-2614`).
- **Endorsed by its owner.** Notebook entries are private by default (AD-1157, `records_store.py:72`), written under the agent's callsign, and dated in frontmatter: `created`, `updated` and `revision` (`records_store.py:38-40`, `:312-325`). AD-552 suppresses a notebook write at revision 5 or more when it adds little new (`proactive.py:3186`, `:3228-3235`). Its agent-facing repetition warning is built (`proactive.py:2816-2829`) but nothing renders it.
- **The record over the recollection.** AD-986b (#928, closed) has an agent consult the chat transcript, the objective record, when its own episodic memory is lossy.
- **Never delete, in progress.** AD-1340 (#1568, open) makes dream pruning archive episodes instead of deleting them; archive is already the default eviction (`config.py:861`). Parity says the same rule should hold for an agent's notebooks.

## Absorbed

### 1. Trust on retrieval needs the date and the author

**The idea.** Trust on retrieval is what makes the notebook part of Otto's memory, and it is also the danger: Otto believes whatever the notebook says. That trust is reasonable only because Otto knows the notebook is his and roughly how old an entry is.

**Where ProbOS falls short.** Two read-back paths drop exactly that information:
- **A notebook read back into context** shows only the topic and a snippet, `<notebook topic="...">` (`cognitive_agent.py:9416-9419`, `:11324-11327`). It omits the `updated` date that the index line just above it shows, and no read-back shows the `revision`.
- **A Records result through `oracle_query`** is marked `[source:records relevance:0.82 age:0s]`. The `age` is the time since *retrieval*, not since the entry was written. `ProvenanceEnvelope.from_oracle_result` sets `retrieval_timestamp` to the current time (`cognitive/provenance.py:79-92`), and the tool renders the marker in the same call (`tools/oracle_query_tool.py:148`), so the age is always about zero. The entry's real dates are in its frontmatter, carried in the result's `metadata` (`oracle_service.py:1076-1083`) and not rendered by this tool. A six-month-old entry reads as brand new. The tool's own preamble tells agents to weigh a STALE entry lightly, and the marker can never say STALE. (The passive path, `query_formatted`, does show `by {author}` for Records, but no date.)

The second is a mislabel of the same kind AD-1294 fixed, when a match score was shown to agents as `confidence`.

**What to absorb.**
- Every read-back of external memory states who wrote it and when: "your note, updated 2026-10-12, revision 4", or "Ship's Records, written by Forge on 2026-05-03".
- Fix the `age` marker: show the entry's `updated` date from frontmatter, or rename the field so it cannot be read as the content's age.

*Owner: a BF for the `age` marker, in the AD-677 and AD-1294 lineage; the notebook read-back belongs with it.*

### 2. Easy to get at, when it is needed

**The idea.** Otto consults the notebook at the moment he needs the address, not later.

**In ProbOS.** On the proactive path, an agent that asks for a notebook with `[READ_NOTEBOOK topic]` gets it in the *next* cycle (AD-504, `proactive.py:3443-3444`, consumed at `:2847-2858`), so a note it chose can inform only the thought after the one that needed it. In agentic runs the agent can query Records through `oracle_query` within the run, and sees its own private notes because the tool passes its identity (`oracle_query_tool.py:322`).

The proactive path also has a same-cycle pull: it searches for the agent's department name and injects the top hit as `notebook_content` (`proactive.py:2831-2842`). **That pull is a privacy defect, found while checking this note.** It calls `records_store.search(dept, scope=f"notebooks/{callsign}")` with no reader identity. `scope` there is a classification level, not a path, so the unknown value is treated as `ship`. A `private` entry (level 0) passes, the identity check is skipped when no reader is given (`records_store.py:139-145`), and `search` scans every entry (`:1107` onward). An agent can therefore be shown another crew member's private note. A reviewer reproduced it against a real `RecordsStore`; `tests/test_self_monitoring.py` mocks `search`, which is why tests miss it. It is to be filed as a BF, not fixed in this note.

*Owner: the BF for the leak. Same-cycle access to the agent's own chosen note is then a design question for the proactive path.*

### 3. Parity as a design test for every new memory store

**The idea.** If an outside store does the work of memory, give it memory's rules.

**What to absorb.** A short test for any store an agent is meant to rely on, such as AD-1240's workspace results, the results BF-947 carries across resumes, or a future store:
- Is it there when the agent needs it, without a special request?
- Can the agent tell who wrote each item and when?
- Is it governed like memory: kept, not deleted (AD-1340); private by default where it is personal (AD-1157); checked for currency (AD-1302)?

A store that fails the first two should be presented as a source to check, not as something the agent knows.

*Owner: a review question for prompts that add a store the crew will rely on.*

## A lens, not a build

- **Minds that build their own tools.** Clark's later work describes people shaping their surroundings so that thinking gets easier. Crew writing notebooks for themselves, and Chapel writing for her successor, are examples. Notebook quality (`knowledge/notebook_quality.py`) measures this from the outside. Clark suggests also asking whether an agent's notes make its later work better.
- **Predictive processing.** Clark's *Surfing Uncertainty* (2016) belongs with Friston, whom ProbOS already cites in its attention research. It adds nothing new here.

## Rejected

- **Treating every store as memory.** Rejected. Parity applies only when the conditions hold. Treating a web page or a colleague's post as memory would extend trust without the conditions that warrant it.

## Consistent with existing ProbOS principles

- Dating and attributing read-backs adds information and removes none.
- The `age` fix corrects a label. It changes no retrieval or ranking.
- Parity strengthens existing rules (never delete, private by default, currency) by applying them to stores they do not yet name.
