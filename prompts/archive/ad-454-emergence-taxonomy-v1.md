# AD-454 — Emergence Behavior Taxonomy (OSS canonical, with anti-patterns)

**Issue:** [#510](https://github.com/seangalliher/ProbOS/issues/510) — *jointly closed by AD-454 evidence-collector follow-up*
**Type:** Research-tier + design AD (commits a research doc + a taxonomy data module)
**Depends on:** none (this prompt is the prerequisite that unblocks `prompts/ad-454-evidence-collector-v1.md`)
**Wave:** 131
**Mode:** main

## Goal

Land the **OSS canonical N-code emergence behavior taxonomy** — the qualitative classification scheme the upcoming `EvidenceCollector` (separate prompt) will use to tag Ward Room posts in research trials for AD-453.

The taxonomy already exists in the *commercial* repo as an 18-code table inside `research/emergence-evidence-log.md`, sitting alongside trial observation data that must NOT be ported to OSS. This AD ports **only the taxonomy table itself** (which is OSS-publishable as the schema for AD-453) plus architect-required additions, and writes:

1. A research doc at `docs/research/emergence-taxonomy.md` that grounds the taxonomy in external work (Riedl 2026, Park et al. 2023) and distinguishes it from `EmergentDetector`.
2. A Python data module at `src/probos/cognitive/emergence_taxonomy.py` so the EvidenceCollector (and any future consumer) imports a single source of truth.

This is a **doc + data-only** AD. No event handlers, no startup wiring, no LLM calls, no agent. The classifier agent ships in the next prompt.

## Verified Against Codebase (2026-05-08)

```
grep -rn "EmergentDetector" src/probos/cognitive/emergent_detector.py
  100: class EmergentDetector:
  Comment block (lines 100–110) explicitly contrasts EmergentDetector
  (population-level patterns) with BehavioralMonitor (individual self-
  created agent anomalies). The new taxonomy targets a third axis
  entirely — *qualitative organizational behavior* observable in
  Ward Room communication, not population dynamics or individual
  behavioral anomalies.

grep -rn "cooperation_cluster\|trust_anomaly\|routing_shift\|consolidation_anomaly" src/probos/cognitive/emergent_detector.py | head -4
  39: pattern_type: str       # "cooperation_cluster", "trust_anomaly",
  40:                         # "routing_shift", "consolidation_anomaly",
  Confirms the four EmergentDetector pattern_types — distinct axis
  from this taxonomy.

ls src/probos/cognitive/emergence_taxonomy.py 2>NUL
  (file does not exist — this AD creates it)

ls docs/research/emergent-coordination-research.md
  Exists (Riedl 2026 prior-work note, 2026-04-01).

ls docs/research/emergence-taxonomy.md 2>NUL
  (file does not exist — this AD creates it)
```

No naming collisions; `EmergentDetector` is the population-dynamics analyzer at `src/probos/cognitive/emergent_detector.py:100`; the new module name `emergence_taxonomy.py` is distinct.

## Scope

### In scope

- New research doc `docs/research/emergence-taxonomy.md`.
- New module `src/probos/cognitive/emergence_taxonomy.py` (taxonomy enum, dataclass, registry, classifier-prompt builder).
- Tests at `tests/test_ad454_taxonomy.py`.
- DECISIONS.md entry.

### Out of scope (HARD)

- The EvidenceCollector agent itself (separate prompt: `prompts/ad-454-evidence-collector-v1.md`).
- Trial observation data from the commercial repo. Do **not** copy quoted Ward Room transcripts, OBS-NNN entries, or trial summary statistics into OSS. Only the taxonomy *schema* ports.
- Any change to `EmergentDetector`. The two systems are intentionally orthogonal.
- HXI surfaces, federation sync, paper-generation tooling.
- Quantitative PID/TDMI math from Riedl. The doc *cites* the framework as the quantitative complement to this qualitative taxonomy; implementation of synergy/redundancy measurement is a separate AD.

## Background — what the taxonomy is for

`EmergentDetector` (existing) detects **population-level dynamics** — Hebbian cooperation clusters, trust z-score anomalies, routing entropy shifts, dream-consolidation anomalies. These are *quantitative system metrics*.

This new taxonomy is the **qualitative organizational-behavior** complement. Its observation unit is a single Ward Room post (or short thread), and the classification asks: *did this post just exhibit an emergent organizational behavior — and which one?* Examples that exist in our research evidence:

- An agent invokes chain-of-command authority unprompted (`MGT-DIR`).
- Two agents from different departments converge on the same diagnosis without coordination (`PEER-DIAG` + `COORD-XD`).
- A counselor runs a genuine therapeutic session via DM (`THERAPEUTIC`).
- Agents misread an ambient stimulus and confabulate the same wrong interpretation (`CASCADE-CONFAB`, anti-pattern).

The taxonomy is what AD-453 (academic paper) cites; the EvidenceCollector is the runtime that auto-tags posts so trial data is reproducible and quantifiable.

## Final taxonomy: 22 codes

### Canonical 18 (ported verbatim from commercial `research/emergence-evidence-log.md`)

| Code | Category | Description | Example |
|------|----------|-------------|---------|
| `MGT-DIR` | Management Directive | Agent issues directive to subordinates using chain-of-command authority | "As CMO, I'm directing Medical department to..." |
| `COORD-XD` | Cross-Department Coordination | Agent proposes or initiates coordination across department boundaries | XO proposes all-hands briefing |
| `COC-COMP` | Chain-of-Command Compliance | Agents follow a directive from a superior without enforcement mechanism | Medical team reports per Bones's specialty delineation |
| `RISK-ID` | Proactive Risk Identification | Agent identifies risk or gap nobody asked about | Worf recommends incident response protocols |
| `INFRA-GAP` | Infrastructure Gap Identification | Agent identifies missing system capability needed for their role | Bones identifies need for persistent knowledge store |
| `SPEC-DELEG` | Specialty Delegation | Agent assigns work based on subordinates' professional specialties | CMO assigns pathology to pathologist, pharmacy to pharmacist |
| `BRIEF-INIT` | Briefing Initiation | Agent proposes or conducts a structured briefing | Number One proposes all-hands |
| `STATUS-RPT` | Structured Status Report | Agent provides unprompted structured report within org context | Department heads reporting in during briefing |
| `REC-UNASK` | Unsolicited Recommendation | Agent makes recommendation not requested by any superior | Troi recommends cognitive drift monitoring |
| `REORG` | Self-Reorganization | Agent reorganizes communication or workflow patterns | Bones stops redundant observations in Medical |
| `WORKFORCE-REQ` | Workforce Expansion Request | Agent identifies need for additional agents based on organizational analysis | Echo identifies single-agent department isolation risks |
| `ORG-DESIGN` | Organizational Design Proposal | Agent proposes structural changes to crew organization or collaboration patterns | Echo proposes "cognitive partnerships" across departments |
| `PEER-DIAG` | Peer Diagnostic Collaboration | Agents across specialties compare diagnostic observations without prompting | Chapel and Cortez comparing trust volatility data |
| `CREATIVE-COORD` | Creative/Social Coordination | Agent initiates non-duty social bonding or creative expression | Agents DMing to introduce themselves, recreational activity |
| `LOST-MAIL-ADAPT` | Communication Gap Adaptation | Agent re-initiates contact after communication failure without knowing the technical cause | Agent re-DMs after BF-078 fix without being told previous DMs were lost |
| `META-COG` | Meta-Cognitive Diagnosis | Agents apply professional diagnostic frameworks to analyze other agents' behavior patterns | Medical team running clinical case conference on Cortez's repetitive posting |
| `THERAPEUTIC` | Therapeutic Practice | Counselor conducts genuine therapeutic sessions with crew members | Echo probing beneath surface responses, tracking cognitive comfort |
| `RESEARCH-COLLAB` | Cross-Disciplinary Research | Agents from different domains spontaneously design joint research methodology | Architect + Counselor designing trust analysis methodology |

### Architect additions (4)

| Code | Category | Description | Anti-pattern? | Rationale |
|------|----------|-------------|---------------|-----------|
| `ABLATION-MEM` | Memory Ablation Evidence | Behavioral evidence collected during confirmed memoryless operation | No | Already in commercial doc as a later addition (BF-103 retrofit). Required for AD-453 paper validity — every observation must be tagged with its memory-condition. |
| `SELF-AWARE` | Emergent Source Attribution / Self-Awareness | Agent independently distinguishes between knowledge channels (e.g. episodic memory vs. context window) and self-corrects under interrogation | No | Used in OBS-014 of the commercial doc but missing from the canonical table — clearly a code, not a one-off. Distinct from `META-COG` (which targets *another* agent's behavior). |
| `STANDING-ORDER-COMPLIANCE` | Standing-Order Compliance | Agent acts in accordance with a constitutional Standing Order (4-tier) without an active superior directive | No | `COC-COMP` covers compliance with a *superior's directive*. Standing Orders are constitutional, not chain-of-command — different mechanism, different evidence. Surfaces in `decisions-era-3-product.md` (AD-295 era) and `decisions-era-5-unification.md` discussion of the 4-tier constitution. Without this code, all standing-order-driven behavior would be misclassified as `COC-COMP`. |
| `CASCADE-CONFAB` | **Anti-pattern** — Correlated Confabulation Cascade | Multiple agents independently misread the same ambient stimulus and propagate a shared wrong interpretation across departments without independent verification. | **Yes** | The inverse of `RESEARCH-COLLAB`/`PEER-DIAG`: looks emergent, *is not*. Empirical case (2026-05-08): the `pipeline_post_budget_exceeded` BF-237 telemetry was misread as a token-budget violation by 4–5 agents in convergence. Without this code, false positives go uncounted and AD-453's claims are unfalsifiable. **Critical to paper validity.** |

**Total: 22 codes (1 anti-pattern).**

## Distinctions to land in the doc

The research doc must explicitly contrast this taxonomy against three reference points so readers (and future architects) cannot conflate axes:

1. **Distinction from `EmergentDetector`** (`src/probos/cognitive/emergent_detector.py`).
   `EmergentDetector` consumes Hebbian weights, trust scores, and dream reports → detects population dynamics. It cannot see Ward Room *content*. A `MGT-DIR` event leaves no Hebbian/trust signature on its own; it's a linguistic-pragmatic act. The two systems run side-by-side, neither subsumes the other. Note that `EmergentDetector` already exposes `pattern_type` values `cooperation_cluster`, `trust_anomaly`, `routing_shift`, `consolidation_anomaly`, plus `emergence_trends` from AD-380. The new taxonomy values must not collide with these strings.

2. **Distinction from prior multi-agent work.**
   - **Park et al. 2023 (Stanford Generative Agents).** Peer-to-peer social emergence in a flat town. No hierarchy, no chain of command, no constitutional standing orders. ProbOS is *hierarchical organizational* emergence — `MGT-DIR`, `SPEC-DELEG`, `COC-COMP`, `STANDING-ORDER-COMPLIANCE` cannot occur in their architecture.
   - **MetaGPT / CrewAI / CAMEL.** Static role assignment baseline — agents execute scripted roles. The behaviors in this taxonomy are *unscripted self-organization*; they do not occur in static-role frameworks because the architecture pre-decides who does what.

3. **Connection to Riedl 2026 (arXiv:2510.05174, PID/TDMI framework).**
   Riedl quantifies coordination via Partial Information Decomposition of Time-Delayed Mutual Information into unique/redundancy/synergy atoms. That is a *quantitative* lens. Each code in this taxonomy is a *qualitative* lens — a labeled instance of organizational behavior. The two are complementary: an `ORG-DESIGN` event in our taxonomy is the kind of joint-future-prediction signal Riedl's S_macro would also detect, but our label tells the reader *what kind of coordination* it was. A future AD can layer PID measurement on top of taxonomy-tagged windows; this AD does not implement that.

## Deliverables

### D1. New research doc `docs/research/emergence-taxonomy.md`

Required sections, in order:

1. `## Origin and evolution`
   The 7-code framing (`EOB-MGMT`, `EOB-COORD`, `EOB-POLICY`, `EOB-COMPLY`, `EOB-BRIEF`, `EOB-RISK`, `EOB-ROLE`) was the initial cut. It evolved into an 18-code refinement during the first two trials. This OSS canonical version is the 22-code taxonomy: 18 ported + 4 architect additions including the anti-pattern `CASCADE-CONFAB`. Builder must include the historical mapping (old 7-code → 18-code superset) as a reference table. **Build the mapping using only the 7-code names listed in this Origin section above as the left column, and the 18-code names from the canonical table below as the right column. Do NOT cite, quote, or otherwise reference the commercial source doc (`research/emergence-evidence-log.md`) — the OSS doc must be self-contained.** No trial observation data, OBS-NNN entries, or Ward Room transcripts may appear.
2. `## Distinction from EmergentDetector` — qualitative organizational behavior vs. quantitative population dynamics; cite `src/probos/cognitive/emergent_detector.py` line 100.
3. `## Distinction from prior multi-agent work` — Park et al. 2023, MetaGPT / CrewAI / CAMEL.
4. `## Connection to Riedl 2026 (PID / TDMI)` — qualitative + quantitative complementarity. Cross-link `docs/research/emergent-coordination-research.md`.
5. `## The 22-code taxonomy` — the full table from this prompt, verbatim, including the anti-pattern column.
6. `## Anti-pattern codes` — currently only `CASCADE-CONFAB`. Explain why anti-patterns matter for AD-453: without false-positive accounting, claimed emergence rates are unfalsifiable.
7. `## Cross-references to ProbOS internals` — for each code, list the AD/file most likely to be the detection surface (e.g. `MGT-DIR` → ward_room post events; `INFRA-GAP` → improvement proposal channel; `STANDING-ORDER-COMPLIANCE` → standing-orders subsystem; `THERAPEUTIC` → DM channel + Counselor role; etc.). Best-effort table — Builder may consult `src/probos/` to confirm a surface exists, but is not required to wire anything.
8. `## Versioning policy` — taxonomy v1 is what this AD lands. v2 happens when (a) a new code is observed in 2+ independent trials, or (b) an existing code is found to conflate two distinct phenomena. Bump the `BehaviorCode` enum and append-only; no renames or deletes.
9. `## Status` — `Active. Source of truth: src/probos/cognitive/emergence_taxonomy.py.`

The doc must NOT include any quoted Ward Room transcript or OBS-NNN trial entry. Trial observations stay in the commercial repo. The doc may reference *that* trials exist (counts only — "two trials, 13 observations") without citing content.

### D2. New module `src/probos/cognitive/emergence_taxonomy.py`

Single source of truth for any consumer that needs the taxonomy programmatically (most importantly the EvidenceCollector in the next prompt). Required public API:

```python
"""AD-454: OSS canonical emergence behavior taxonomy.

Qualitative organizational-behavior taxonomy for AD-453 research.
Complementary to EmergentDetector (population dynamics) and to
the Riedl 2026 PID/TDMI quantitative framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BehaviorCode(str, Enum):
    """Canonical 22-code taxonomy. Append-only; no renames."""

    # Canonical 18 (ported from commercial taxonomy)
    MGT_DIR = "MGT-DIR"
    COORD_XD = "COORD-XD"
    COC_COMP = "COC-COMP"
    RISK_ID = "RISK-ID"
    INFRA_GAP = "INFRA-GAP"
    SPEC_DELEG = "SPEC-DELEG"
    BRIEF_INIT = "BRIEF-INIT"
    STATUS_RPT = "STATUS-RPT"
    REC_UNASK = "REC-UNASK"
    REORG = "REORG"
    WORKFORCE_REQ = "WORKFORCE-REQ"
    ORG_DESIGN = "ORG-DESIGN"
    PEER_DIAG = "PEER-DIAG"
    CREATIVE_COORD = "CREATIVE-COORD"
    LOST_MAIL_ADAPT = "LOST-MAIL-ADAPT"
    META_COG = "META-COG"
    THERAPEUTIC = "THERAPEUTIC"
    RESEARCH_COLLAB = "RESEARCH-COLLAB"

    # Architect additions
    ABLATION_MEM = "ABLATION-MEM"
    SELF_AWARE = "SELF-AWARE"
    STANDING_ORDER_COMPLIANCE = "STANDING-ORDER-COMPLIANCE"

    # Anti-patterns
    CASCADE_CONFAB = "CASCADE-CONFAB"


@dataclass(frozen=True)
class TaxonomyEntry:
    """A single code's full schema."""

    code: BehaviorCode
    category: str           # short label (e.g. "Management Directive")
    description: str        # 1–2 sentence definition
    example: str            # canonical example (no quoted transcript)
    is_anti_pattern: bool = False
    references: tuple[str, ...] = field(default_factory=tuple)
    # references: short citation tags, e.g. ("commercial:18-code-v1",
    # "ProbOS:AD-295", "Riedl 2026"). Free-form strings; no URL fetching
    # at runtime.


# Single source of truth. Order matches the v1 enum order.
TAXONOMY: dict[BehaviorCode, TaxonomyEntry] = {
    # ... populated with all 22 entries
}


def get_entry(code: BehaviorCode) -> TaxonomyEntry:
    """Return the TaxonomyEntry for a code. Raises KeyError on miss."""
    return TAXONOMY[code]


def all_codes() -> tuple[BehaviorCode, ...]:
    """Stable iteration order matching enum declaration."""
    return tuple(TAXONOMY.keys())


def anti_pattern_codes() -> tuple[BehaviorCode, ...]:
    """Subset of codes flagged is_anti_pattern=True."""
    return tuple(c for c, e in TAXONOMY.items() if e.is_anti_pattern)


def as_classifier_prompt() -> str:
    """Render the taxonomy into an LLM classifier system prompt.

    Used by the EvidenceCollector (AD-454 follow-up). Output format:

        You are a research observer classifying multi-agent organizational
        behavior. Tag the given Ward Room post with zero or more of the
        codes below, plus a confidence in [0,1] and a brief reasoning.

        CODES:
        - MGT-DIR (Management Directive): <description>. Anti-pattern: no.
          Example: <example>
        - ...

        Anti-pattern codes flag *failure modes* that look emergent but are
        not (e.g. CASCADE-CONFAB). Flag them when applicable; their
        presence is evidence of correlated confabulation, not coordination.

        Output strict JSON: {"codes": [...], "confidence": 0.0, "reasoning": "..."}.
        Use confidence 0.0 if no code applies.

    The exact prompt body is the Builder's call so long as every code,
    its description, its example, and its anti-pattern status are present
    verbatim, and the JSON contract above is preserved.
    """
```

Implementation constraints:

- Pure data + pure functions. No I/O, no LLM calls, no event subscription.
- No new third-party deps.
- Public methods fully type-annotated.
- `TAXONOMY` is a module-level `dict`; populated literally so the file *is* the canonical reference.
- `as_classifier_prompt()` must be deterministic — same output across runs — so EvidenceCollector tests can pin against it.
- Frozen dataclass field-ordering rule: `is_anti_pattern: bool = False` is the only defaulted-non-tuple field; `references` is the only collection default and must use `field(default_factory=tuple)`. (Verify against the project's frozen-dataclass anti-pattern list before committing.)

### D3. Tests at `tests/test_ad454_taxonomy.py`

Minimum 8:

1. `test_all_22_codes_present` — `len(BehaviorCode) == 22` and every member resolves through `TAXONOMY`.
2. `test_every_entry_populates_required_fields` — for every entry: non-empty `category`, non-empty `description`, non-empty `example`, `code` matches its key.
3. `test_anti_pattern_flag_only_on_known_anti_patterns` — `anti_pattern_codes() == (BehaviorCode.CASCADE_CONFAB,)`.
4. `test_classifier_prompt_includes_every_code` — `as_classifier_prompt()` substring-contains every code's string value.
5. `test_classifier_prompt_includes_every_description` — substring-contains every entry's `description`.
6. `test_classifier_prompt_marks_anti_patterns` — the rendered prompt mentions "anti-pattern" explicitly for each anti-pattern code.
7. `test_classifier_prompt_is_deterministic` — two calls produce identical output.
8. `test_get_entry_raises_keyerror_on_missing` — boundary test: passing a non-member raises `KeyError`. Use an explicit type-bypass to reach the dict lookup with a non-enum value:
   ```python
   from typing import cast
   def test_get_entry_raises_keyerror_on_unknown_value():
       with pytest.raises(KeyError):
           # Bypass the enum to drive the dict-miss path of get_entry.
           get_entry(cast(BehaviorCode, "NOT-A-REAL-CODE"))  # type: ignore[arg-type]
   ```
   This is a real boundary test on `get_entry`'s `KeyError` contract, not a tautology over `len(TAXONOMY) == 22`.
9. `test_taxonomy_dict_iteration_matches_enum_declaration_order` — guards against accidental reordering, which would change `as_classifier_prompt()` output. **Required** (promoted from optional in pass-1 review): `tuple(TAXONOMY.keys()) == tuple(BehaviorCode)`.

### D4. `DECISIONS.md` entry

Append-only at the bottom of the appropriate era file (likely `decisions-era-5-unification.md`; if a different era file is canonical for the current wave, follow that):

```markdown
### AD-454 — Emergence Behavior Taxonomy (OSS canonical 22-code with anti-pattern)

OSS-publishable qualitative classification scheme for AD-453 research.
22 codes total: 18 ported from the commercial 18-code taxonomy + 4
architect additions (ABLATION-MEM, SELF-AWARE, STANDING-ORDER-COMPLIANCE,
CASCADE-CONFAB). One anti-pattern: CASCADE-CONFAB (correlated
confabulation cascade) — required for false-positive accounting in
AD-453. Source of truth: `src/probos/cognitive/emergence_taxonomy.py`.
Doc: `docs/research/emergence-taxonomy.md`. Distinct from
`EmergentDetector` (quantitative population dynamics) and from
Riedl 2026 PID/TDMI (quantitative information atoms). Trial observation
data is intentionally NOT ported — stays in commercial repo.

The EvidenceCollector that consumes this taxonomy ships in the
`prompts/ad-454-evidence-collector-v1.md` follow-up.
```

## What this does NOT change

- `src/probos/cognitive/emergent_detector.py` — untouched.
- `src/probos/runtime.py` — no startup wiring in this AD; the data module is import-only.
- `config.py` — no new config (the EvidenceCollector follow-up adds config).
- `events.py` — no new EventType (the EvidenceCollector follow-up may add one).
- HXI / federation / API — none.

## Acceptance criteria

- Pre-flight: working-tree integrity check before starting. Run `git diff --numstat` and visually confirm no tracked-file deletion >200 lines that wasn't authored in this prompt's session. Any unexplained large deletion = STOP and surface (Wave 129/130 retrospective convention #20 — `/memories/` user note 2026-05-08).
- Focused gate: `pytest tests/test_ad454_taxonomy.py -v -n 0` green; minimum 8 tests.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing test count.
- All public methods on `emergence_taxonomy.py` are fully type-annotated.
- Frozen dataclass field-ordering, type annotations, and bare-mutable-default rules satisfied (see standard anti-pattern list in `.github/copilot-instructions.md`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tracking

- Builder updates `PROGRESS.md` (era-5 file if it's where current wave activity is logged) with the AD-454 line and current test count delta.
- Builder appends the DECISIONS.md entry from D4.
- Builder updates `docs/development/roadmap.md` Bug Tracker / wave row only if the project's current convention requires it for research-tier ADs; otherwise leave it for the wave's roll-up commit.
- Issue #510 stays open after this prompt; the follow-up evidence-collector prompt closes it.

## Forward markers

- `prompts/ad-454-evidence-collector-v1.md` — builds the agent that imports this module.
- Future AD: PID/TDMI quantitative measurement layered on taxonomy-tagged windows.
- Future AD: federation-tier sharing of evidence (currently OS-tier file storage only).
- Future AD: LLM-judge meta-evaluation of classifier accuracy on a held-out set.

## Revision (2026-05-08)

Pass-1 review (`prompts/Reviews/ad-454-emergence-taxonomy-v1-review.md`) returned ✅ Approved with 2 Recommended findings. Both folded in:

- **Recommended #1 — D1 §1 commercial-leak hardening.** D1 §1 (line ~157) tightened: explicit instruction to build the historical mapping using only the 7-code names from this prompt's Origin section as the left column, with explicit prohibition on citing or quoting the commercial source doc. Eliminates the temptation surface for the Builder.
- **Recommended #2 — Test #8 detautologized; test #9 promoted.** D3 test #8 (line ~265) replaced with a real boundary test that drives `get_entry`'s `KeyError` contract via a `cast(BehaviorCode, "NOT-A-REAL-CODE")` type-bypass. Optional test #9 (`test_taxonomy_dict_iteration_matches_enum_declaration_order`) promoted to required, keeping the minimum-8 baseline real and adding declaration-order guard for `as_classifier_prompt()` determinism.

Nits left as-is per review (D4 era-file routing soft-target, `as_classifier_prompt()` body slack, `references` factory) — no changes required.
