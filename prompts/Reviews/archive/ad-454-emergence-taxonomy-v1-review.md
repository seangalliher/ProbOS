# Review: AD-454 — Emergence Behavior Taxonomy (v1)

**Prompt:** `prompts/ad-454-emergence-taxonomy-v1.md`
**Pass:** 1
**Date:** 2026-05-08
**Verdict:** ✅ **Approved**
**Headline:** Doc + data-only taxonomy AD; all 22 codes present, anti-pattern flag wired, frozen-dataclass ordering correct, verify-first findings carried into prompt body.

## Required (must fix before building)

*None.*

## Recommended

1. **D1 §1 historical mapping table risks bleeding commercial content.** The "old 7-code → 18-code superset" reference table asks the Builder to reconstruct a mapping that is not present in the OSS codebase. The 7-code names (`EOB-MGMT`, `EOB-COORD`, etc.) are only listed in the prompt body, so reconstruction is mechanical, but a careless Builder might be tempted to cite the commercial doc to justify the superset. Tighten the instruction to: *"Build the mapping using only the 7-code names in this prompt's Origin section as the left column. Do NOT cite or quote the commercial source doc."* This eliminates the temptation outright.

2. **Test #8 is non-exercisable as written.** `test_get_entry_raises_keyerror_on_missing` reads:

   > use a sentinel string-bypass cast or simply note that all enum members are present so this is exercised by `len(TAXONOMY) == 22`.

   The fallback note isn't a test — it's a tautology. Recommend replacing with an explicit:
   ```python
   def test_get_entry_with_unknown_string_value_raises():
       with pytest.raises(KeyError):
           # Bypass the enum to reach the dict lookup
           TAXONOMY[cast(BehaviorCode, "NOT-A-REAL-CODE")]  # type: ignore[arg-type]
   ```
   or drop the test and bump the optional ninth (`test_taxonomy_dict_iteration_matches_enum_declaration_order`) to required. The prompt would still meet the 8-test minimum.

## Nits

- **D4 era-file routing is soft** ("likely `decisions-era-5-unification.md`; if a different era file is canonical for the current wave, follow that"). Acceptable because the Builder must grep at commit time anyway, but a single-line confirmation in the wave-orchestrator state file would remove ambiguity.
- **`as_classifier_prompt()` "exact prompt body is the Builder's call"** is correct in spirit but slightly loose. The deterministic-output test (#7) and the substring tests (#4, #5, #6) collectively pin enough behavior; no change needed.
- **`references: tuple[str, ...]`** uses `field(default_factory=tuple)` — correctly avoids the bare-mutable-default trap. Verified.

## Verified

- **All 18 commercial codes present** in the canonical table: `MGT-DIR`, `COORD-XD`, `COC-COMP`, `RISK-ID`, `INFRA-GAP`, `SPEC-DELEG`, `BRIEF-INIT`, `STATUS-RPT`, `REC-UNASK`, `REORG`, `WORKFORCE-REQ`, `ORG-DESIGN`, `PEER-DIAG`, `CREATIVE-COORD`, `LOST-MAIL-ADAPT`, `META-COG`, `THERAPEUTIC`, `RESEARCH-COLLAB`. Count = 18.
- **All 4 architect additions present:** `ABLATION-MEM`, `SELF-AWARE`, `STANDING-ORDER-COMPLIANCE`, `CASCADE-CONFAB`. Each has Category + Description + Anti-pattern column + Rationale.
- **Anti-pattern flag wired** via `is_anti_pattern: bool = False` on `TaxonomyEntry`; only `CASCADE-CONFAB` carries `True`. `anti_pattern_codes()` accessor + dedicated test (#3) cover it.
- **Frozen-dataclass field ordering correct:** `code, category, description, example` (non-defaulted) before `is_anti_pattern: bool = False, references: tuple[str, ...] = field(default_factory=tuple)` (defaulted). No field-ordering trap.
- **Bare-mutable-default avoided:** `references` uses `field(default_factory=tuple)`.
- **Distinction from `EmergentDetector`** explicitly contrasts `pattern_type` strings (`cooperation_cluster`, `trust_anomaly`, `routing_shift`, `consolidation_anomaly`) — the prompt warns the new taxonomy must not collide. Verified at `src/probos/cognitive/emergent_detector.py:39-40`.
- **`emergence_taxonomy.py` does not exist at HEAD** — prompt creates it. No naming collision.
- **`docs/research/emergence-taxonomy.md` does not exist at HEAD** — prompt creates it. `docs/research/emergent-coordination-research.md` exists for cross-link.
- **Working-tree integrity pre-flight bullet present** in Acceptance criteria (Wave 129/130 convention #20).
- **OSS-vs-commercial boundary explicit:** trial observation data and OBS-NNN entries explicitly out of scope; only the schema ports.
- **Public-API typing** required by Acceptance.
- **Versioning policy** spelled out (append-only, no renames/deletes).

---

*No re-review needed unless the two Recommended items prompt a revision pass.*
