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

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**Required #1 resolved via Option B (shared pre-filter in PowerShell wrapper); all 4 Recommended folded; all 4 Nits applied; no new findings.**

Revision (commit eeaf9c7) cleanly addresses the recursive-validity gap surfaced in pass-1. The shared pre-filter is correctly scoped to the wrapper layer (so the existing symbol check benefits without rewriting its regex tunings), the AST-index cache promotion to v1 is a module-level dict only (no caching infrastructure smuggled in beyond AD-685's scope), and the recursive-validity gate is correctly framed as a Builder-side acceptance check rather than a pre-dispatch precondition.

### Resolution Audit

| Pass-1 Required | Status | Evidence |
|---|---|---|
| R1 (shared pre-filter; lift heuristics to wrapper) | ✅ Resolved | Section 2 rewritten: `shared body pre-filter step` produces ``; symbol check (L97/L105/L114 regexes) reads filtered body; kwarg helper also reads filtered body. Solution Overview now lists 2 capabilities. `Note on "preserved verbatim"` clarifies logic preserved, input changed. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| R1 (AST-index cache → v1) | ✅ Applied | Section 1 step 3: `AST-index caching is v1 (not a fallback)`. Process-local module-level dict. Hard-Stop reworded to `>30s on cold first build`. No sidecar JSON / no separate cache infra — module-level global only. |
| R2 (test #4 fence breadth) | ✅ Applied | Test #4 renamed `test_helper_skips_kwargs_in_non_python_fenced_blocks`; covers pwsh + bash + sh + text + bare-fence (no language tag); Section 2 step 1 lists same fence types. |
| R3 (any-definition limitation in DECISIONS) | ✅ Applied | DECISIONS.md draft block lists receiver-class resolution as AD-685d deferred limitation. v1 deferral list also includes AD-685d. |
| R4 (calibration corpus named) | ✅ Applied | Section 3: `ad-641c-*` (test #2 regression) + `ad-500-*` (test #3 regression) + `≥3 other archived Wave 8/9/10 prompts` (Builder picks). |

| Pass-1 Nit | Status | Notes |
|---|---|---|
| N1 (drop `preserved verbatim`) | ✅ Applied | Replaced everywhere with `logic preserved; input changed to pre-filtered body`; explicit callout in Section 2. |
| N2 (recursive-validity in Hard-Stops) | ✅ Applied | Now appears in BOTH Acceptance Criteria AND Hard-Stops. |
| N3 (`any_overload` → `any_definition`) | ✅ Applied | Test #6 renamed; DECISIONS.md and Section 1 use `same-named definition` instead of `overload`. |
| N4 (UTF-8 stdout) | ✅ Applied | Section 1 step 5: `sys.stdout.reconfigure(encoding='utf-8')` or `write bytes directly`. |

### New Findings (introduced during revision)

None. Five-point verification:

1. **Shared pre-filter resolution.** Section 2 step 1 defines the pre-filter ONCE (3 heuristics: non-Python fence mask, `## Revision` mask, prose-table cell mask); steps 2–3 explicitly route both the existing symbol regexes (L97/L105/L114) and the new AST helper through ``. `Note on "preserved verbatim"` makes the logic-vs-input distinction explicit. Recursive-validity gate appears as Builder-side Acceptance Criterion + Hard-Stop (correct framing — not a pre-dispatch precondition). Solution Overview header line `v1 ships 2 capabilities` matches the body. `What This Does NOT Change` correctly excludes AD-685b (field-name) and AD-685c (type-shape).
2. **AST-index cache scope discipline.** Section 1 step 3 specifies `module-level global` and `short-circuit on subsequent calls within the same process` — a sidecar dict, not a persisted cache. No new caching infrastructure (no JSON sidecar, no DB, no IPC). Hard-Stop targets cold-build time only. Scope-appropriate.
3. **Test plan expansion.** 8 → 9 tests. Test #9 (`test_powershell_wrapper_shared_prefilter_suppresses_prose_table_phantom`) directly covers Required #1 against the AD-685-self-reference case. Test #4's purpose now lists 5 fence types. All 9 tests map to real behaviors (3 regression cases, 3 heuristic cases, 1 same-name-definition case, 2 wrapper-integration cases).
4. **Pre-check status documented.** Revision section explicitly notes: `the existing pre-check STILL flags WorkItemStore.get_pending as 1 phantom on this revised prompt — that is correct and expected`. Confirmed by run: `./scripts/phantom-api-precheck.ps1 prompts/ad-685-...md` exits 1 with 1 phantom (`WorkItemStore.get_pending`), identical to pass-1 baseline. No new phantoms introduced by the 11-surface revision.
5. **Solution Overview / DECISIONS.md consistency.** Top-of-prompt `v1 ships 2 capabilities` aligns with Acceptance Criteria gates (3 of 8 bullets reference shared-pre-filter behavior). DECISIONS.md draft block correctly enumerates AD-685b/c/d deferrals (b: field-name, c: type-shape, d: receiver-class resolution). Cross-link to `Wave 11 pass-1 review Required #1` present.

### Hard-Stop Verification (per dispatch's four pre-conditions)

| Hard-Stop | Triggered? | Notes |
|---|---|---|
| 1. R1 not addressed | No | Verified above; Section 2 wrapper-level shared pre-filter is the chosen resolution. |
| 2. New Required-class issue introduced | No | Five-point verification clean; revision strictly reduces surface. |
| 3. AST-index cache promoted infrastructure beyond scope | No | Module-level dict only; no JSON sidecar, no persistence layer, no IPC. |
| 4. v1 scope creep (AD-685b folded in) | No | Test plan + Section 1 contain zero field-name assertions; `WorkItem(payload=...)` cited only in motivation table. |

### Recursive-Validity Gate Framing (architectural confirmation)

The revision correctly frames the recursive-validity check as **Builder-side acceptance**:

- Acceptance Criteria bullet: `Recursive-validity gate (also Hard-Stop): ./scripts/phantom-api-precheck.ps1 prompts/ad-685-...md exits 0 with 0 phantoms after AD-685 ships. Currently exits 1 with the documented WorkItemStore.get_pending self-reference; the shared pre-filter must suppress it.`
- Hard-Stops bullet: `Recursive-validity gate fails: post-build pre-check still flags any phantom — pre-filter is incomplete; tune before merge (do NOT special-case the AD-685 file by name).`

This is the architecturally correct choice: pre-dispatch the prompt cannot satisfy a check that depends on its own implementation. Builder runs the gate after Section 2 lands; if it fails, the pre-filter is incomplete and tuning is required (no allowlist short-circuit). Pass-1 review's Required #1 option (a) recommended this exact framing.

### Conclusion

Revision is tight, scope-disciplined, and converges to ✅. Recommend single-commit Builder dispatch.
