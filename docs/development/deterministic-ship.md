# Probabilistic Crew, Deterministic Ship

**Status:** Founding design principle. **Thesis:** the Captain (Sean Galliher), 2026-10-29.
**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-29. Code anchors are on `main` at `d740c692`.
**Placement:** linked from [Design Principles](design-principles.md#probabilistic-crew-deterministic-ship).

> **Thesis (the Captain's).** Autonomous agents need a deterministic core: a system of
> record, like a ledger with fixed business rules, that enforces governance. That core is
> what gives agents the freedom to act, just as it gives humans the freedom to act. Humans
> lived for most of their history in a largely probabilistic world with a few hard laws.
> Writing and record-keeping gave them a more deterministic way to exist, and that is what
> let them progress. In ProbOS the ship is that core for the crew: **probabilistic crew,
> deterministic ship.**

---

## 1. The human analogy

Physicists still disagree about whether the world's underlying laws are deterministic or probabilistic. At human scale it hardly matters: weather and much else is chaotic, so small differences grow until prediction fails (Lorenz, 1963). People do not get by on predicting the world. They rely on a few things that hold no matter what: objects persist, everyone shares one world, causes come before effects, the past cannot be changed, and some rules, such as gravity, cannot be argued with.

Minds are the probabilistic part. Memory is reconstructive rather than a recording (Bartlett, 1932), and most of what we "know" is inference. ProbOS agents are the same: a language model reasons, an agent's recall is ranked and partial, and two agents can read the same facts and conclude different things. That is a strength, and ProbOS keeps it.

What humans added on top of physics was **record-keeping**, and the record came early. The earliest Mesopotamian writing, proto-cuneiform (about 3300 BCE, Uruk), grew out of accounting: most of the archaic tablets are administrative records of goods, labour and rations (Nissen, Damerow and Englund, *Archaic Bookkeeping*, 1993). Written law codes followed, the Code of Ur-Nammu (about 2100 BCE) and the Code of Hammurabi (about 1754 BCE), whose stele stood in public. Double-entry bookkeeping appears in Italian merchant ledgers around 1300 and was first set out in print by Luca Pacioli in 1494. Public land registries, such as South Australia's Torrens title system (1858), made ownership a fact anyone could check, and de Soto (*The Mystery of Capital*, 2000) argues that formal property records are what let an asset be trusted by strangers.

Each of these let trust reach past personal memory and kinship. You could deal with someone you had never met because the record, not either party's recollection, said what was owed, owned and agreed. Each one **widened the freedom to act** by making consequences legible and enforceable at the moment they were recorded.

The same history carries a warning. Records also served taxation, conscription and control; James C. Scott (*Seeing Like a State*, 1998; *Against the Grain*, 2017) shows how making a population "legible" served the state that read it. A system of record can become surveillance and bureaucracy. ProbOS takes both lessons: keep the record, and keep governance **minimal, legible and enforced at the points where something becomes true**, not spread over everything an agent thinks.

## 2. The principle

**Agents are free in what they think and propose. Deterministic logic decides what becomes true.**

When an agent's proposal would change the ship's state (a write, a booking, a trust change, an archive entry, a lifecycle step), it passes through a **commit point**: one owner, in ordinary code, that checks authority and evidence, records who did it, and keeps the history. Before that point an agent may reason, guess, debate and change its mind. After it, the result is a fact the whole crew can rely on, because no one's memory is needed to establish it.

This is why governance buys autonomy rather than taxing it. The more reliably the core holds its invariants, the more an agent can be allowed to do unattended, because every consequence lands in a record the Captain and the crew can read, check and, where allowed, reverse.

The core does not have to be deterministic throughout. Trust scores are Bayesian estimates, consensus weighs confidence-scaled votes, and dreaming consolidates memories by heuristics. What must be deterministic are the **invariants**: the guarantees below, which hold whatever the probabilistic parts produce.

One difference from physics matters most. **Physics' invariants cannot be broken; a ship's can, by code.** A feature that is wired but never runs, a receipt that claims more than it saw, an identifier counted under the wrong key: each makes the ship lie to the agents who live in it. A ship that reports something false is worse than one that says "unknown", because agents build on what the ship tells them. So honest self-report is itself an invariant.

## 3. The invariants

Each row says what the invariant means in ProbOS, which existing components provide it today, and the known gaps. Gaps are cited from open issues or recorded registers; this document creates no new work.

*Glossary:* **ACM** (Agent Capital Management) is the crew's personnel-records service. A **slot id** names an agent's post on the ship; a **sovereign id** names the agent itself (its birth certificate). The **Ward Room** is the crew's message board.

| Invariant | What it means in ProbOS | Provided today by | Known gaps |
|---|---|---|---|
| **1. Persistence** | What was committed is still there after a restart, on any storage backend. | Every durable store opens through the `ConnectionFactory` protocol (`src/probos/protocols.py:362`), e.g. `EventLog` (`substrate/event_log.py:486-503`) and `ArchiveStore` (`knowledge/archive_store.py:481`). Ship's Records makes every write a git commit (`knowledge/records_store.py:207-212`). | No verified snapshot or point-in-time restore yet (AD-1265, AD-1266, Wave 4 of #1324). Ship's Records cuts a document short when a frontmatter value contains `---` (BF-940, #1686). |
| **2. One shared state** | Each fact has one owner, and each agent one key, so every reader sees the same answer. | ACM as the single personnel authority (`acm.py:1-10`, legal transitions `acm.py:42-50`). One identity resolver, `AgentIdentityRegistry.resolve_slot_id` (`identity.py:804`, BF-907). Hybrid Coordination's rule that one deterministic service owns each durable transition ([design-principles.md](design-principles.md#hybrid-coordination-ad-1231)). | About 18 other local identity resolvers remain (AD-1346 epic, #1601). The AD-638 boot camp counts episodes under the slot id while episodes carry the sovereign id, so no enrolled agent graduates on its criteria (#1324 register addition, 2026-10-29; `boot_camp.py:211`). Trust inputs read through APIs that do not exist (BF-924, #1654). |
| **3. Causal order** | Every change has one place in one sequence, and its cause is recorded with it. | `EventLog` rows are ordered by id and chained by `prev_hash`, with `correlation_id` and `parent_event_id` columns (`event_log.py:80-110`). ACM reads, checks and writes a transition and its audit row as one locked section (`acm.py:250-264`). | Durable event meaning and correlated run evidence do not yet cover every critical path (AD-1195 and AD-1152, Wave 5 of #1324); one graph from model request to tool call to child run is unbuilt (AD-1329, #1531). |
| **4. A fixed past** | History is appended, never rewritten; a removal leaves a trace. | `EventLog` is append-only and hash-chained, with `verify_chain` (`event_log.py:476-482`, `:1211-1248`). The Identity Ledger hash chain (`identity.py:351-372`). The security `AuditLog`'s anchored truncation, so a full log is reported as truncated, never as tampered (`security/audit.py:89`, AD-1278). `ArchiveStore` never updates an entry; the Captain's erase leaves a content-free marker (`archive_store.py:1-17`, `:593`). Trust changes keep raw `(alpha, beta)` and a receipt with its evidence hash (`consensus/trust.py:32-50`). | `EventLog.prune` severs the hash chain, so `verify_chain` reports the kept rows as corrupt (documented and deliberately left unfixed by BF-873 at `event_log.py:1250-1262`; now tracked as BF-942, #1706). Dream pruning deletes episodes rather than archiving them (AD-1340, #1568). |
| **5. Rules no one can bypass** | A change commits only through its owner's checks; there is no side door. | ACM refuses an illegal lifecycle transition (`acm.py:260-264`). Consensus evaluates destructive intents on the live path (`QuorumEngine`, `consensus/quorum.py:36`; `runtime.py:4681`). `CodeValidator` checks agent code (`cognitive/code_validator.py:18`). The Archive has one write path, `promote_entry` (`archive_store.py:534`). | Controls are enforced where work starts, and work starts in many places: one admission decision per unit of work is in shadow mode (AD-1346, #1601, #1604), and 18 direct `.handle_intent(` calls skip the pre-intent policy (BF-789, per #1601). The AD-753 permission gate has no caller (`consensus/quorum.py:196-201`; AD-1353, #1659). Work permits are built but not consumed (`tools/work_permits.py:9-13`; owner AD-1348, #1630). |
| **6. Honest self-report** | The ship states only what it observed. Unknown is reported as unknown, never as a default or a success. | Activation receipts record what startup actually wired and claim no health or exercise (`maturity/receipts.py:1-11`, `:56-68`). The maturity report answers `UNKNOWN`, never `FALSE`, for an input it cannot resolve (`maturity/report.py:13-16`). The report-only dormant-class check lists classes nothing uses (`scripts/check_dormant_classes.py:1-6`, baseline `docs/development/dormant-class-baseline.yaml`). A trust miss is reported as "no record", not as the 0.5 prior (BF-907, `DECISIONS.md:245-246`). Inert config fields say so (`config.py:2976`). | The AD-486 Birth Chamber admits almost no one and graduates no one, silently (AD-1355, #1700, Problem items 1-10). The boot-camp slot-id count above. A recall gate never bound (BF-938, #1680); verification and alert producers nothing calls (AD-1352, #1658); a merge the UI offers that always refuses (BF-937, #1678). Orientation would tell an agent with a history it "was commissioned moments ago" (`cognitive/orientation.py:352`; #1700 track E). |
| **7. Attributed authority, the Captain at the top** | Every committed change records who made it and under what authority, and the Captain's authority is the top of the chain. | ACM records `initiated_by` on every transition (`acm.py:96`, `:113`, `:241-244`). Ship's Records frontmatter names the author (`records_store.py:210-211`). Archive erase and veto are Captain-only (`archive_store.py:468-470`). A work permit's issuer must differ from its holder (`tools/work_permits.py:1-8`). | The Captain's stop for one agent or the vessel is not enforced by every service (AD-1343, #1595). Making the Federation Constitution unamendable by agents, while the Captain keeps amending it through ordinary development, is open (AD-1344 slice 1, #1596). Nothing calls `ConnManager.is_authorized` (#1324 register R8, `DECISIONS.md:898`). |

Whether these records add up to a ledger, the chain-head log that would make the whole past checkable, and why that is not a blockchain: [How Literally Should ProbOS Take "Ledger"?](ship-ledger.md).

The gaps are not a reason to doubt the principle; they are what the principle is for. Most rows in the last column were found by asking exactly these questions of existing code: the activation receipts, the dormant-class check, the boot camp's slot-id count and the Birth Chamber findings all came out of the AD-1270 platform-maturity work (#1324) and AD-1355 (#1700).

## 4. Where governance sits

**Commit points** (deterministic, attributed, recorded):

- a write to a durable store: an event, a Ship's Records document, an archive entry, an episode;
- a lifecycle step in ACM, and the issue or revocation of an identity;
- a trust change, applied once per outcome with its evidence;
- a destructive or external action, after consensus or an explicit grant;
- a change to standing orders, configuration or code, with the Captain's approval where the rules require it.

At each one the owner checks authority and evidence, records the actor, appends to history, and reports exactly what it did.

**Deliberately left probabilistic:**

- what an agent thinks, says, proposes, remembers and decides to work on;
- routing and attention (Hebbian weights, intent matching, proactive cycles);
- the *values* of trust scores and consensus outcomes, which are estimates, even though applying them is recorded deterministically;
- dreaming, consolidation and recall ranking;
- character and its growth.

Governance does not watch thinking. It meets an agent at the moment its idea would become a fact, and nowhere else.

## 5. The check every AD and BF answers

Answer each with yes or no in the prompt; a "no" needs a reason.

1. **Owner.** If this change makes something true, is there exactly one owner and one commit point for it, named in the prompt?
2. **No side door.** Is every path that produces the same effect routed through that commit point?
3. **Authority and attribution.** Does the commit point check authority and evidence in ordinary code, and record who acted?
4. **History.** Is the result appended rather than rewritten, and does it survive a restart?
5. **Honest report.** Does everything the ship says about it (receipts, status, logs, prompts, docs) state only what was observed, with "unknown" where it does not know, and is there a test that crosses from producer to consumer through production wiring?
6. **Free thinking, minimal banks.** Does the change leave how agents think untouched, and does each new constraint state what it defends and what it costs?
7. **The Captain.** Can the Captain see the result and, where the rules allow, override or reverse it?

## 6. How it relates to the other principles

This principle names the ground the others stand on. It does not replace any of them.

| Principle | Relation |
|---|---|
| [Probabilistic Agents, Consensus Governance](design-principles.md#probabilistic-agents-consensus-governance) | The other half. That one keeps agent behaviour probabilistic and avoids hardcoded "always do X" in how agents act; this one makes the record of what they did deterministic. Invariants constrain outcomes, not reasoning. |
| [Hybrid Coordination](design-principles.md#hybrid-coordination-ad-1231) | Supplies the boundary test: a service owns durable state transitions, an agent owns what the work is. Commit points are where that boundary sits. |
| Secure but Not Limited ([design principles](design-principles.md)) | States that governance buys autonomy; this principle says why it can: consequences are legible and enforced at commit points, so freedom elsewhere is safe. Check 6 is its "a ceiling must be a decision" rule. |
| Authentic AI Identity, the Westworld Principle ([design principles](design-principles.md)) | Westworld forbids deceiving agents about what they are. Invariant 6 extends the same honesty from the agent's identity to the ship's own state. Nothing here limits what agents know about themselves. |
| [Foundational Governance Axioms](design-principles.md#foundational-governance-axioms) | Safety budget, reversibility and minimal authority apply *at* the commit points this principle locates. |
| [Markdown is Code](design-principles.md#markdown-is-code) | Its three substrates map onto this split: Python is the deterministic ship, markdown runs on the probabilistic crew. |
| Constraints as Enablers ("A river without banks is a swamp. Constraints create flow"; [crew-development research](../research/crew-development-research.md), [roadmap era 5](roadmap-era-5-completed.md)) | The same idea for an agent's own cognition. The invariants are the ship's banks: few, fixed and justified by a failure they prevent. |
| [Engineering Principles](engineering-principles.md) and the [Evidence Standard](../../.github/copilot-instructions.md) | How the invariants are kept in code: one owner per responsibility, the "propagate" exception tier for security and data integrity, raw trust parameters, cloud-ready storage, and claims of absence backed by a search that was actually run. |

## References

- E. N. Lorenz, "Deterministic Nonperiodic Flow", *Journal of the Atmospheric Sciences*, 1963.
- F. C. Bartlett, *Remembering*, Cambridge University Press, 1932.
- H. J. Nissen, P. Damerow and R. K. Englund, *Archaic Bookkeeping*, University of Chicago Press, 1993; R. K. Englund, ["Accounting in Proto-Cuneiform"](https://cdli.ucla.edu/staff/englund/publications/englund2011a.pdf), 2011. Dates for the start of proto-cuneiform range from about 3350 to 3300 BCE ([overview](https://en.wikipedia.org/wiki/Proto-cuneiform)).
- [Code of Hammurabi](https://www.worldhistory.org/Code_of_Hammurabi/) and the Code of Ur-Nammu (World History Encyclopedia).
- On early double-entry ledgers (Farolfi, 1299-1300; Genoa, 1340) and Pacioli's *Summa* (1494): [ICAEW, earliest books on bookkeeping](https://www.icaew.com/library/library-collection/historical-accounting-literature/earliest-books-on-bookkeeping). Which ledger counts as earliest depends on how strictly "double-entry" is defined.
- [Real Property Act 1858](https://en.wikipedia.org/wiki/Real_Property_Act_1858) (South Australia, Torrens title).
- H. de Soto, *The Mystery of Capital*, 2000.
- J. C. Scott, *Seeing Like a State*, Yale University Press, 1998; *Against the Grain*, Yale University Press, 2017.
- In agent tooling, GitHub Agentic Workflows ([github/gh-aw](https://github.com/github/gh-aw)) applies the same split: the agent job holds read-only credentials and emits typed requests, and separate "safe output" jobs hold the scoped write permission, validate each request and act ([absorption note](../research/gh-aw-absorption.md)).
- In software, the same split is known as "functional core, imperative shell" (G. Bernhardt, "Boundaries", 2012) and as event sourcing, where state is derived from an append-only log of changes.
