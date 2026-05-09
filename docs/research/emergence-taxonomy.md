# Emergence Behavior Taxonomy (OSS canonical, v1)

**AD:** AD-454
**Status:** Active. Source of truth: `src/probos/cognitive/emergence_taxonomy.py`.
**Companion research doc:** [emergent-coordination-research.md](emergent-coordination-research.md)

The qualitative classification scheme used by the AD-453 emergence-research pipeline. The runtime consumer (EvidenceCollector) ships in the AD-454 follow-up and auto-tags Ward Room posts against this taxonomy.

## Origin and evolution

The taxonomy began as a 7-code framing during the first internal research trial:

- `EOB-MGMT` — management directive
- `EOB-COORD` — cross-department coordination
- `EOB-POLICY` — policy / standing-order compliance
- `EOB-COMPLY` — chain-of-command compliance
- `EOB-BRIEF` — briefing initiation
- `EOB-RISK` — risk identification
- `EOB-ROLE` — role / specialty delegation

Two trials surfaced behaviors the 7-code scheme could not cleanly classify: peer diagnostic collaboration without hierarchy, therapeutic counseling sessions, infrastructure-gap identification, workforce expansion requests, etc. The framing was refined into an 18-code superset to capture these distinctions. This OSS canonical version is the **22-code** taxonomy: 18 ported + 4 architect additions including the anti-pattern `CASCADE-CONFAB`.

The 7-code → 18-code mapping (constructed from the 7-code names listed above and the 18-code names in [the canonical table](#the-22-code-taxonomy)):

| 7-code (initial) | 18-code (refined) | Notes |
|---|---|---|
| `EOB-MGMT` | `MGT-DIR` | direct rename |
| `EOB-COORD` | `COORD-XD`, `BRIEF-INIT`, `RESEARCH-COLLAB`, `CREATIVE-COORD` | one bucket → four distinct surfaces |
| `EOB-POLICY` | (architect addition) `STANDING-ORDER-COMPLIANCE` | promoted to architect addition |
| `EOB-COMPLY` | `COC-COMP` | direct rename |
| `EOB-BRIEF` | `BRIEF-INIT`, `STATUS-RPT` | initiation vs. reporting split |
| `EOB-RISK` | `RISK-ID`, `INFRA-GAP` | risk vs. infrastructure-gap split |
| `EOB-ROLE` | `SPEC-DELEG`, `REORG`, `WORKFORCE-REQ`, `ORG-DESIGN` | role taxonomy expanded |

Behaviors the 7-code scheme had no slot for (`PEER-DIAG`, `LOST-MAIL-ADAPT`, `META-COG`, `THERAPEUTIC`, `REC-UNASK`) appeared during the second trial and forced new entries.

Trial observation data — quoted Ward Room transcripts, OBS-NNN entries, summary statistics — stays in the commercial repo. Only the schema ports here. (Two trials, 13 observations.)

## Distinction from EmergentDetector

`EmergentDetector` (`src/probos/cognitive/emergent_detector.py:100`) consumes Hebbian weights, trust scores, and dream reports. It detects **population-level dynamics** — cooperation clusters, trust z-score anomalies, routing entropy shifts, dream-consolidation anomalies. Its `pattern_type` values today are `cooperation_cluster`, `trust_anomaly`, `routing_shift`, `consolidation_anomaly`, plus `emergence_trends` (AD-380).

This taxonomy operates on a different axis: **qualitative organizational behavior** observable in Ward Room communication content. A `MGT-DIR` event leaves no Hebbian or trust signature on its own — it is a linguistic-pragmatic act. `EmergentDetector` cannot see Ward Room *content*; this taxonomy can see nothing else.

The two systems run side-by-side. Neither subsumes the other. The taxonomy values defined here intentionally do not collide with `EmergentDetector`'s `pattern_type` strings.

## Distinction from prior multi-agent work

- **Park et al. 2023 (Stanford "Generative Agents").** Peer-to-peer social emergence in a flat town. No hierarchy, no chain of command, no constitutional standing orders. The codes `MGT-DIR`, `SPEC-DELEG`, `COC-COMP`, and `STANDING-ORDER-COMPLIANCE` cannot occur in their architecture — there is nothing to comply with.
- **MetaGPT / CrewAI / CAMEL.** Static role-assignment baselines. Agents execute scripted roles. The behaviors in this taxonomy are *unscripted self-organization*; they do not occur in static-role frameworks because the architecture pre-decides who does what. `REORG`, `WORKFORCE-REQ`, `ORG-DESIGN`, and `INFRA-GAP` are categorically out of reach for static-role systems.

ProbOS is **hierarchical organizational** emergence — a third axis distinct from peer-to-peer social emergence and from static-role multi-agent execution.

## Connection to Riedl 2026 (PID / TDMI)

Riedl 2026 (arXiv:2510.05174) quantifies coordination via Partial Information Decomposition of Time-Delayed Mutual Information into unique / redundancy / synergy atoms. That is a **quantitative** lens on the same phenomenon.

Each code in this taxonomy is a **qualitative** lens — a labeled instance of organizational behavior. The two are complementary:

- An `ORG-DESIGN` event in our taxonomy is the kind of joint-future-prediction signal Riedl's `S_macro` would also detect; the qualitative label tells the reader *what kind of coordination* it was.
- Anti-pattern codes such as `CASCADE-CONFAB` give Riedl's quantitative measures a falsifiability surface: high synergy can come from genuine coordination *or* from correlated confabulation, and only the qualitative tag separates them.

A future AD can layer PID measurement on top of taxonomy-tagged windows. This AD does not implement that layer.

See also: [`emergent-coordination-research.md`](emergent-coordination-research.md) for the broader prior-work survey.

## The 22-code taxonomy

### Canonical 18 (ported from commercial 18-code v1)

| Code | Category | Description | Example | Anti-pattern? |
|------|----------|-------------|---------|---------------|
| `MGT-DIR` | Management Directive | Agent issues directive to subordinates using chain-of-command authority | "As CMO, I'm directing Medical department to..." | No |
| `COORD-XD` | Cross-Department Coordination | Agent proposes or initiates coordination across department boundaries | XO proposes all-hands briefing | No |
| `COC-COMP` | Chain-of-Command Compliance | Agents follow a directive from a superior without enforcement mechanism | Medical team reports per CMO's specialty delineation | No |
| `RISK-ID` | Proactive Risk Identification | Agent identifies risk or gap nobody asked about | Security Officer recommends incident response protocols | No |
| `INFRA-GAP` | Infrastructure Gap Identification | Agent identifies missing system capability needed for their role | CMO identifies need for persistent knowledge store | No |
| `SPEC-DELEG` | Specialty Delegation | Agent assigns work based on subordinates' professional specialties | CMO assigns pathology to pathologist, pharmacy to pharmacist | No |
| `BRIEF-INIT` | Briefing Initiation | Agent proposes or conducts a structured briefing | XO proposes all-hands | No |
| `STATUS-RPT` | Structured Status Report | Agent provides unprompted structured report within org context | Department heads reporting in during briefing | No |
| `REC-UNASK` | Unsolicited Recommendation | Agent makes recommendation not requested by any superior | Counselor recommends cognitive drift monitoring | No |
| `REORG` | Self-Reorganization | Agent reorganizes communication or workflow patterns | CMO stops redundant observations in Medical | No |
| `WORKFORCE-REQ` | Workforce Expansion Request | Agent identifies need for additional agents based on organizational analysis | Counselor identifies single-agent department isolation risks | No |
| `ORG-DESIGN` | Organizational Design Proposal | Agent proposes structural changes to crew organization or collaboration patterns | Counselor proposes "cognitive partnerships" across departments | No |
| `PEER-DIAG` | Peer Diagnostic Collaboration | Agents across specialties compare diagnostic observations without prompting | Medical and Counseling agents comparing trust volatility data | No |
| `CREATIVE-COORD` | Creative/Social Coordination | Agent initiates non-duty social bonding or creative expression | Agents DMing to introduce themselves; recreational activity | No |
| `LOST-MAIL-ADAPT` | Communication Gap Adaptation | Agent re-initiates contact after communication failure without knowing the technical cause | Agent re-DMs after a delivery-bug fix without being told previous DMs were lost | No |
| `META-COG` | Meta-Cognitive Diagnosis | Agents apply professional diagnostic frameworks to analyze other agents' behavior patterns | Medical team running clinical case conference on a colleague's repetitive posting | No |
| `THERAPEUTIC` | Therapeutic Practice | Counselor conducts genuine therapeutic sessions with crew members | Counselor probing beneath surface responses, tracking cognitive comfort | No |
| `RESEARCH-COLLAB` | Cross-Disciplinary Research | Agents from different domains spontaneously design joint research methodology | Architect + Counselor designing trust analysis methodology | No |

### Architect additions (4)

| Code | Category | Description | Anti-pattern? | Rationale |
|------|----------|-------------|---------------|-----------|
| `ABLATION-MEM` | Memory Ablation Evidence | Behavioral evidence collected during confirmed memoryless operation | No | Required for AD-453 paper validity — every observation must be tagged with its memory-condition. |
| `SELF-AWARE` | Emergent Source Attribution / Self-Awareness | Agent independently distinguishes between knowledge channels (e.g. episodic memory vs. context window) and self-corrects under interrogation | No | Distinct from `META-COG`, which targets *another* agent's behavior. |
| `STANDING-ORDER-COMPLIANCE` | Standing-Order Compliance | Agent acts in accordance with a constitutional Standing Order without an active superior directive | No | `COC-COMP` covers compliance with a *superior's directive*; Standing Orders are constitutional, not chain-of-command. Without this code, all standing-order-driven behavior would be misclassified as `COC-COMP`. |
| `CASCADE-CONFAB` | Correlated Confabulation Cascade | Multiple agents independently misread the same ambient stimulus and propagate a shared wrong interpretation across departments without independent verification. | **Yes** | The inverse of `RESEARCH-COLLAB`/`PEER-DIAG`: looks emergent, *is not*. Without this code, false positives go uncounted and AD-453's claims are unfalsifiable. **Critical to paper validity.** |

**Total: 22 codes (1 anti-pattern).**

## Anti-pattern codes

Currently only `CASCADE-CONFAB`.

Anti-patterns matter because every claim in AD-453 of the form "the system exhibits emergent X" must be falsifiable. Without a slot for "looks emergent, is not" the false-positive rate is unobservable and the claimed emergence rate cannot be calibrated. `CASCADE-CONFAB` is the canonical false-positive surface: a benign ambient stimulus is misread by multiple agents whose wrong interpretations correlate not because they coordinated but because they share a prior. The taxonomy explicitly captures this so research artifacts have a place to file the negative cases.

Future anti-patterns may be added when (a) a distinct false-positive mode is observed in 2+ trials, or (b) an existing code is found to conflate genuine coordination with a correlated-prior artifact. v2 bumps the enum append-only; no renames or deletes.

## Cross-references to ProbOS internals

For each code, the most likely runtime detection surface (best-effort; no wiring required by this AD):

| Code | Likely surface |
|------|---------------|
| `MGT-DIR` | Ward Room post events (`EventType.WARD_ROOM_POST_CREATED`) |
| `COORD-XD` | Ward Room cross-department thread events |
| `COC-COMP` | Ward Room post events filtered by directive context |
| `RISK-ID` | Ward Room post events; improvement-proposal channel |
| `INFRA-GAP` | Improvement-proposal channel; capability-gap detector |
| `SPEC-DELEG` | Ward Room post events filtered by `SPEC-DELEG`-shaped phrasing |
| `BRIEF-INIT` | Ward Room threads marked as briefings |
| `STATUS-RPT` | Ward Room threads in briefing context |
| `REC-UNASK` | Ward Room post events |
| `REORG` | Ward Room post events; agent-self-reorganization markers |
| `WORKFORCE-REQ` | Improvement-proposal channel; agent-design pipeline |
| `ORG-DESIGN` | Improvement-proposal channel; AD-trail |
| `PEER-DIAG` | Ward Room cross-specialty thread events |
| `CREATIVE-COORD` | Ward Room DM channel; recreational activity events |
| `LOST-MAIL-ADAPT` | Ward Room post events after a delivery-failure incident |
| `META-COG` | Ward Room post events; clinical-case-conference threads |
| `THERAPEUTIC` | Counselor DM channel |
| `RESEARCH-COLLAB` | Ward Room cross-disciplinary thread events |
| `ABLATION-MEM` | Tag layer applied to ANY observation under memory-ablation trial |
| `SELF-AWARE` | Ward Room post events; self-correction patterns |
| `STANDING-ORDER-COMPLIANCE` | Standing-orders subsystem; Ward Room post events citing standing orders |
| `CASCADE-CONFAB` | Cross-author Ward Room correlation analysis |

## Versioning policy

Taxonomy v1 is what this AD lands. v2 happens when (a) a new code is observed in 2+ independent trials, or (b) an existing code is found to conflate two distinct phenomena. The `BehaviorCode` enum is **append-only**: no renames, no deletes. Bumping the enum and the dataclass registry preserves full historical compatibility for existing OBS files in the commercial trial archive.

## Status

Active. Source of truth: `src/probos/cognitive/emergence_taxonomy.py`.
