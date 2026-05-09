# Review: AD-702 — Diplomatic Relations
**Verdict:** ⚠️ Conditional
**Highest-risk prompt of the wave: real spec defect on `max_hops` handling, missing Protocol-widening fan-out check, line-number drift.**

## Required (must fix before building)
1. **`max_hops` is in the signature but the implementation never reads it.** Test #5 (`test_max_hops_one_returns_none_when_only_two_hop_chain_exists`) cannot pass against the D1 body as written — the auto-bridge loop unconditionally builds a 2-hop chain regardless of `max_hops`. Either (a) add `if max_hops < 2: return None` before the auto-bridge loop, or (b) drop test #5 and document `max_hops` as reserved-for-AD-702b. Pick one explicitly so Builder doesn't ship a no-op parameter.
2. **Add the Protocol-widening fan-out check that the dispatch report required.** The prompt should instruct the Builder to grep `TrustNetworkProtocol` mock sites *first*; if >5, accept `Any` instead of widening the Protocol. Verified count today is **0 mock sites** (`grep TrustNetworkProtocol tests/` returns nothing), so widening is safe — but the prompt must state that finding inline so a future re-run with new mocks doesn't blindly widen. One-line addition.
3. **D2 sequencing is ambiguous.** "Add immediately after the `safety_critical` check" overlaps logically with that check (both return `None` when no direct record exists). Show the merged code block — what the function looks like *with both blocks in place* — so the Builder doesn't double-return or invert the precedence.

## Recommended
1. Line numbers in §"Verified Against Codebase" drift 15–37 lines from HEAD: `trust.py:127` (actual 115), `:91` (actual 128), `:165` (actual 150), `:32` (actual 31). Symbols correct, but per Wave 5 convention #4 either tighten ("around line N") or refresh.
2. Add the working-tree integrity reminder (convention #20).
3. `_apply_decay` walks `_event_log` in reverse on every call. Note for the Builder: `_event_log` has `maxlen=500`, so worst-case is bounded but linear. Acceptable for v1; flag for AD-702b graph search.
4. The `chain_path` helper duplicates the "find best 1-hop bridge" loop verbatim from `transitive_score`. Extract a private `_best_bridge(observer, target, discount) -> tuple[float, AgentID|None]` helper to avoid the DRY violation.

## Nits
- Constants block at module top mixes int (`DEFAULT_TRANSITIVE_MAX_HOPS`) and float — fine, but call out that `max_hops` is `int` in signature.
- Test #11 (`sybil_discount_makes_long_chain_capped`) name mentions "long chain" but only verifies 2-hop with δ. Rename or leave as a forward marker.

## Verified
- `src/probos/consensus/trust.py:103` `class TrustNetwork` — confirmed.
- `src/probos/consensus/trust.py:31` `class TrustRecord` — confirmed (prompt says `:32`).
- `src/probos/protocols.py:51` `class TrustNetworkProtocol` — confirmed.
- `_event_log: deque[TrustEvent] = deque(maxlen=500)` at `:128` — confirmed.
- `set_department_lookup` at `:150` — confirmed (prompt says `:165`, drift = 15).
- No matches for `transitive`, `trust_path`, `chain_trust`, `delegated_trust` — greenfield claim holds.
- `enabled` flag not introduced (no config gate) — neutral.
- Hard-constraint list correctly forbids `record_outcome` mutation, edge-table introduction, and quorum-path coupling.

## Pass 2 Review (2026-05-08)

**Verdict:** ❌ Not Ready
**Revision Notes section claims fixes that are not present in the prompt body.**

### Required (must fix before building)

1. **Required #1 (max_hops gate) — NOT LANDED.** The Revision Notes (line 255) states `Added `if max_hops < 2: return None` gate before the auto-bridge loop`. Body verification: Select-String -Path prompts/ad-702-diplomatic-relations-v1.md -Pattern "max_hops < 2|if max_hops" returns **only the Revision Notes line**. The actual 	ransitive_score body (lines 50–117) contains no max_hops gate. Test #5 (`test_max_hops_one_returns_none_when_only_two_hop_chain_exists`, line 222) will FAIL on the build. Fix: add the gate immediately before line 99 (start of section `# 3. Auto bridge`).
2. **Required #2 (Protocol-widening conditional + 0-mock-site snapshot) — NOT LANDED INLINE.** Revision Notes (line 256) claims `Added inline conditional rule and verified count`. D3 body (lines 199–211) shows only the Protocol method signatures — no inline note about the 0-mock-site snapshot, no conditional rule (`if >5 mocks at build time, accept Any`). The snapshot lives only in the Revision Notes; the Builder reads D3 and won't see it. Fix: pin the snapshot + conditional rule as a sub-bullet under D3.
3. **Required #3 (D2 sequencing merged block) — NOT LANDED.** Revision Notes (line 257) claims `Replaced the standalone intent-descriptor block with a merged code block`. D2 body (lines 187–197) still shows the intent-descriptor snippet as a standalone insert (`In `transitive_score`, immediately after the `safety_critical` check, also do:` followed by an isolated block). No merged code block showing safety_critical → intent-descriptor → max_hops gates adjacent. The Builder will produce two non-adjacent inserts.
4. **Cross-cutting (working-tree integrity check) — NOT LANDED IN ACCEPTANCE.** Revision Notes (line 261) claims `Added pre-flight working-tree integrity reminder to Acceptance`. Acceptance criteria section (lines 239–246) has 6 bullets, none of which mention git diff --numstat or working-tree integrity. The wave-level check (User request item 5) is unmet for this prompt.

### Recommended

1. Recommended R4 (DRY: _best_bridge helper) — Revision Notes claim it was extracted. Body still shows duplicate auto-bridge logic in 	ransitive_score (lines 99–116) and chain_path (lines 134–148). Not landed; demote to ⚠️ deferral target if the Required items are fixed and the Builder is rushed.

## Pass 3 Review (2026-05-08)

**Verdict:** ⚠️ Conditional
**All four pass-2 Required findings landed in the body. Recommended R4 (DRY) flagged for the third time — claimed in Revision Notes but not in body.**

### Required (must fix before building)

None. All four pass-2 Required findings now have grep evidence in the prompt body:

| Pass-2 Required | Self-check grep | Body line | Outside Revision Notes? |
|---|---|---|---|
| #1 `max_hops < 2` gate | `max_hops < 2\|if max_hops` | L81 (D1), L193 (D2 merged demo) | ✅ Yes (L300 boundary) |
| #2 Protocol-widening 0-mock-site snapshot + conditional | `0 mock sites\|>5 mocks` | L240 (D3 pre-build verification) | ✅ Yes |
| #3 D2 merged final code block | inspected lines 165–193 | merged shape shown adjacent | ✅ Yes |
| #4 Working-tree integrity check | `git diff --numstat` | L287 (Acceptance pre-flight bullet) | ✅ Yes |

D2 is now correctly framed as a follow-on to D1: the prompt explicitly states the `safety_critical` and intent-descriptor checks are "already merged into `transitive_score` in D1" and shows the final merged shape (`max_hops` → identity → direct → safety_critical → intent_descriptor → bridge). D2 itself only adds the `set_intent_descriptor_lookup` setter. No standalone-insert language remaining.

### Recommended (third-strike)

1. **R4 (DRY `_best_bridge` helper) — third strike, drift between claim and body.** Revision Notes L307 asserts: ``Extracted `_best_bridge(observer, target, discount)` helper; `transitive_score` and `chain_path` both delegate to it.`` This claim is **false at HEAD of the prompt body**. The auto-bridge loop is still duplicated verbatim:

   - `transitive_score` body: prompt lines 116–130 (loop body iterating `self._records.items()` with `composed = candidate_rec.score * end.score * discount`)
   - `chain_path` body: prompt lines 147–160 (same loop body, identical iteration)

   No `_best_bridge` definition exists anywhere in the prompt. This is the **same drift pattern** that triggered pass-3 (Notes asserting fixes that didn't reach the body). Because R4 is Recommended (not Required), pass-3 bar treats this as ⚠️ rather than ❌.

   **Resolution options for the Builder (pick one explicitly during build):**
   - (a) Extract `_best_bridge(observer, target, discount) -> tuple[float | None, AgentID | None]` and have both methods delegate. Cleanest; matches the claim.
   - (b) Accept the duplication for v1, remove the false claim from Revision Notes L307, and file the extraction as a follow-up nit on AD-702b (graph search) where the bridge logic will be replaced anyway.

   The author should **not** ship the prompt with both the duplication AND the false claim — one or the other must move.

### Nits

- The Pass-3 self-check section in Revision Notes (L323–L328) re-runs the three greps but does not include the boundary check (`L300 = ## Revision (2026-05-08)` start). Adding one line — "Revision Notes start at L300; all body hits at L81/L193/L240/L287 precede it" — would make the audit trail complete.

### Verified Improvements (pass-3)

- ✅ All three self-check greps return body hits OUTSIDE the Revision Notes section (L300+):
  - `max_hops < 2|if max_hops` → L81, L193 (and L302, L315, L323 inside Notes; expected)
  - `0 mock sites|>5 mocks` → L240 (and L303, L324 inside Notes; expected)
  - `git diff --numstat` → L287 (and L318, L325 inside Notes; expected)
- ✅ D2 sequencing resolved by inlining the merged final shape into D1 and reducing D2 to the descriptor-lookup setter only. Builder cannot produce two non-adjacent inserts because the merged block is now a single contiguous code listing.
- ✅ Pre-flight `git diff --numstat | sort -k2nr | head -5` reminder lives inside the Acceptance criteria as the first pre-flight bullet (L287).

### Phantom-API class-name sweep (Wave 129 carry-over)

| Cited symbol | At HEAD | Status |
|---|---|---|
| `class TrustNetwork` | `src/probos/consensus/trust.py:103` | ✅ |
| `class TrustNetworkProtocol` | `src/probos/protocols.py:51` | ✅ |
| `transitive_score` (no existing collision) | TrustNetwork at HEAD has only `score` (property), `get_score`, `all_scores`, `raw_scores` — no `transitive_score` | ✅ Greenfield |
| `chain_path` (no existing collision) | No matches in `trust.py` for `chain` or `path` as method names | ✅ Greenfield |
| `set_department_lookup` reference for setter shape | `trust.py:150` (per pass-1 Verified) | ✅ Pattern-match |
| `_get_intent_descriptor` injection target | New attribute via setter — no name collision | ✅ |

No phantom-API regressions introduced. The prompt cleanly extends `TrustNetwork` and `TrustNetworkProtocol` without overloading existing names.

### Pass-3 outcome

**⚠️ Conditional** — promoted from pass-2 ❌. Zero Required, one Recommended-third-strike (R4 drift). Falls within the wave-level tolerance stated in pass-2 README ("1 ⚠️ allowed on highest-risk prompt only"). **Wave 130 may dispatch.**

The Builder must, when picking up AD-702, choose explicitly between (a) extracting `_best_bridge` to match the Revision Notes claim, or (b) deleting the L307 claim and accepting the duplication as a deferral target. The Pass-3 Builder-handoff note in the wave dispatch should call this out.

### Nits

- Revision Notes section (lines 253+) describes pass-1 fixes that mostly didn't land in the body — mismatch creates audit-trail confusion. After pass-3 lands the Required items, refresh the Revision Notes to match reality.

### Verified Improvements (pass-2)

- ✅ Protocol-widening fan-out check verified at HEAD: 0 mock sites for TrustNetworkProtocol in 	ests/ (re-verified 2026-05-08, matches snapshot claim).
- ✅ TrustNetworkProtocol exists at src/probos/protocols.py:51 (Protocol class — widening is structurally safe).
- ✅ Added a sequencing comment in the auto-bridge body (# max_hops > 2 is reserved for AD-702b graph search; v1 only does 2-hop.) — but a comment is not a gate.

### Phantom-API spot-check

No phantom-API regressions introduced this pass. All cited symbols (TrustNetwork, _records, _event_log, set_department_lookup, TrustNetworkProtocol) exist at HEAD. The defects are gap-of-implementation, not phantom-API.

### Pass-2 outcome

**Promoted from ⚠️ to ❌.** Pass-1 had 3 Required findings; pass-2 has 4 (the original 3 still open + the new cross-cutting working-tree-check miss). The pattern is severe — the author wrote a Revision Notes section describing fixes without applying them to the prompt body. Recommend a third revision pass with explicit grep evidence required in the next Revision Notes (every "Added X" claim must cite the line number where X now lives).
