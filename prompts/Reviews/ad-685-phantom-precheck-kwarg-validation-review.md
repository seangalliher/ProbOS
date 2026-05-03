# Review: AD-685 — Phantom-API Pre-Check Method-Kwarg Shape Validation
**Verdict:** ⚠️ Conditional
**Recursive validity gap: AD-685's prose-backtick heuristic is scoped to the new kwarg check only; the existing symbol check is "preserved verbatim" (line 74), so AD-685's own prompt will continue to fail the pre-check after shipping unless the heuristic is extended or the prompt body is reworded.**

Wave 11 single-prompt tooling sweep. The intent is sound, the deferral boundary is honest, and the test plan maps tightly to observed failures. One architectural concern blocks ✅: the recursive-validity property the dispatch asks me to confirm is not actually delivered by the prompt as drafted.

## Required (must fix before building)

1. **Recursive validity failure is locked in by line 74.** The dispatch's high-priority point #1 asks me to confirm the heuristic list eliminates the `WorkItemStore.get_pending` self-reference. It does not.
   - Pre-check run on AD-685 itself: 1 phantom flagged (`WorkItemStore.get_pending`). Documented FP per dispatch.
   - AD-685's heuristics (skip non-Python fences, skip backticked prose call expressions, skip `## Revision`, accept-any-overload) are described under Section 1 ("Add Python AST helper script") and apply to the **new kwarg check** only.
   - Section 2 wires the helper as additive: "Existing symbol-existence check — preserved verbatim" (line 74).
   - The existing symbol check's regex `\b([A-Z][a-zA-Z0-9_]+)\.([a-z_][a-z0-9_]+)` matches `WorkItemStore.get_pending` whether it's inside backticks or not. The existing tunings (negative framing, runtime.X self-introduction) do not catch the prose-table-row case.
   - Result: after AD-685 ships, `./scripts/phantom-api-precheck.ps1 prompts/ad-685-...md` still exits 1.
   - The Acceptance Criteria explicitly require "Pre-check still passes on the AD-685 prompt itself (recursive validity)". This will not hold.

   **Resolution options (pick one in revision):**
   - (a) Lift the prose-backtick + `## Revision`-section heuristics out of the AST helper and apply them as a **shared pre-filter** in the PowerShell wrapper before BOTH the symbol check and the kwarg check run. Drop "preserved verbatim" from line 74; replace with "preserved logic; pre-filter applied to both checks". Lowest-risk; one extra Section 2 step.
   - (b) Reword the prompt body so the literal `Class.method` token does not appear in plain prose. For example, render Wave 10 examples as a fenced ```text block, or write `WorkItemStore#get_pending` (hash separator) in prose. Smallest patch, but fragile — future prompts citing past phantoms hit the same trap.
   - (c) Add an explicit `--allowlist` flag or a `<!-- precheck-allow: WorkItemStore.get_pending -->` HTML comment convention to the existing wrapper, used in the AD-685 prompt to suppress the documented self-reference. New surface area; defer to a follow-up unless (a) is rejected.

   **Recommendation:** option (a). It generalizes the heuristic the prompt already wants for the new check, costs ~10 lines in the wrapper, and keeps the Acceptance Criterion honest. State this explicitly in Section 2.

## Recommended (should fix)

1. **Performance estimate is tight; pre-build a cached AST index across calls.** `src/probos` currently has 403 Python files (verified via `Get-ChildItem -Recurse -Filter *.py | Measure-Object`). A cold `ast.parse` walk over 403 files typically takes 1.5–3s on this hardware; with prompt-body parsing + signature matching the <5s target is plausible but not comfortable. The Hard-Stops section already mentions index caching as a fallback. Promote it to a v1 implementation note: a single helper invocation per orchestrator stage often scans ≥3 prompts in a row, so caching the signature index in a process-local module-level dict (or a sidecar JSON keyed by `src/probos` mtime) is cheap and removes the 30s hard-stop risk entirely. Specify this in Section 1 step 3 rather than leaving it as a runtime escape hatch.
2. **Test #4 ("skip kwargs in fenced pwsh code block") covers only one non-Python fence type.** Builder should also assert the heuristic skips `bash`, `sh`, `text`, and bare-fence (no language tag) blocks. Add a sub-bullet to Test #4's purpose: "verify pwsh + bash + bare fence; only ` ```python ` fences are scanned." Three lines of test body, no new test slot.
3. **"Accept kwarg if any overload matches" worsens the `runtime.work_item_store.add` case AD-685 cites as motivation.** The prompt body acknowledges `add` exists on other classes (Wave 10 false-negative). Under the new rule, if `add(work_item)` is called positionally, kwarg validation has nothing to check — neutral. But if a future prompt writes `add(work_item=foo)` and `add` exists on _any_ class with parameter `work_item`, it passes. This is a documented limitation, not a defect — but the DECISIONS.md entry should call it out as a known limitation handed off to AD-685c (type-shape) or a future AD-685d (receiver-class resolution). Two-line addition to DECISIONS.md.
4. **Calibration sweep targets are listed in the dispatch but not in the prompt.** The Wave 11 dispatch names `prompts/archive/ad-641c-*.md` and `prompts/archive/ad-500-*.md` as required calibration corpus. The prompt's Section 3 ("Calibration sweep") just says "archived Wave 8/9/10 prompts." Naming the two specific files in the prompt body removes ambiguity for the Builder and makes the test #2 / test #3 regression mapping verifiable.

## Nits

1. Line 74 phrase "preserved verbatim" will be wrong if Required #1 is resolved via option (a). Replace with "preserved logic; pre-filter applied uniformly".
2. Acceptance Criteria bullet "Pre-check still passes on the AD-685 prompt itself (recursive validity)" is also a Hard-Stop on Builder side. Consider duplicating it under Hard-Stops for prominence.
3. Test #6 name `test_helper_accepts_kwarg_matching_any_overload` is fine; consider renaming to `..._any_definition` since "overload" implies typing-level overloads in Python and these are just same-named methods on different classes.
4. Section 1 step 5 says "JSON to stdout"; specify UTF-8 encoding explicitly to avoid Windows console codepage surprises (the existing pre-check has had this class of bug before).

## Verified

- **Aggressive pre-deferral (convention #14):** v1 = kwarg validation only; AD-685b (field-name) and AD-685c (type-shape) explicitly deferred with rationale. Boundary is honest — no field-name validation has leaked into Section 1, and Test #2 (`event_log.query(event_type=...)`) is correctly framed as a kwarg-name check, not a field-name check.
- **No `WorkItem(payload=...)` slip into v1.** Wave 10's field-name miss is named in the motivation table and explicitly attributed to AD-685b, not v1. Test plan contains zero field-name assertions.
- **Convention #11 (Revision-section audit-trail handling):** addressed by heuristic #3.
- **Convention #14 (aggressive pre-deferral):** explicitly applied; 1 of 3 capabilities.
- **Convention #15 (verdict tolerance):** review surfaces 1 architectural Required → ⚠️ verdict, within tolerance.
- **Convention #16 (phantom-API pre-check):** this AD strengthens the convention itself.
- **Layer discipline / SOLID / Demeter / DRY:** N/A — tooling, no runtime code touched.
- **Security:** N/A — script reads source; no network, no untrusted input.
- **Test plan completeness:** 8 tests; each maps to a concrete observed failure (Wave 9B `query`, Wave 10 `get_pending`, fenced-code skip, revision-section skip, multi-definition acceptance) plus 2 integration tests. Mapping is tight.
- **Performance estimate:** 403 Python files in `src/probos` (verified). <5s estimate is plausible but tight without caching; see Recommended #1.
- **What This Does NOT Change:** present and accurate aside from the line 74 phrasing nit.
- **Tracking section:** PROGRESS.md prepend, DECISIONS.md Era V entry (verbatim text supplied), roadmap.md tooling/hygiene entry — complete.
- **Hard-Stops:** three concrete failure conditions, all measurable. >30s parse, >5 FPs per archived prompt, exit-code regression. Good.

## Heuristic Completeness Assessment

| Heuristic in AD-685 | Motivating Wave/case | Gap? |
|---|---|---|
| Skip non-Python fenced blocks | Waves 8/9 had `pwsh` examples in prompts | None for kwarg check; **yes for symbol check** (see Required #1) |
| Skip backticked prose call expressions | Wave 10 `WorkItemStore.get_pending` cited inline | Same as above — heuristic exists for new check only |
| Skip `## Revision` audit-trail sections | Wave 5 Retrospective convention #11 | None for kwarg check; same scoping issue for symbol check |
| Accept kwarg if any overload matches | Wave 10 `add` exists-on-other-classes pattern | Acknowledged limitation; see Recommended #3 |

**No known false-positive class from Waves 8/9/10 is left entirely unaddressed for the new check.** The only completeness gap is the scoping issue raised in Required #1 — the existing check does not benefit from the new heuristics.

## Top Failure Modes If Shipped As-Is

1. AD-685 lands; first Builder run of `phantom-api-precheck` against any future prompt that cites past phantoms (e.g., a Wave 12 retrospective referencing AD-685's own phantoms) flags them. Architect spends review cycles re-explaining the documented-FP rule. **Severity: medium; cumulative friction.**
2. Acceptance Criterion "pre-check still passes on AD-685 prompt itself" fails on first Builder verification gate. Builder hard-stops; Architect must revise. **Severity: high; blocks the wave's own close-out.**
3. Performance is fine on first prompt, slow on third (no cache); >30s hard-stop hits during a pre-flight sweep of an archived corpus. **Severity: low–medium; recoverable in-place.**

## Recursive Validity Conclusion

**Will the planned heuristics suppress the AD-685 self-reference once AD-685 ships?**
**No** — not as drafted. The new heuristics are scoped to the new kwarg check; the existing symbol check (which produced the flag) is "preserved verbatim." Required #1 resolves this with option (a): lift the heuristics to a shared pre-filter.

## Revision (2026-05-03) — placeholder for Stage 2

(Architect will append revision response after Stage 2 dispatch.)
