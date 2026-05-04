# Review: AD-525 — Agent Creative Expression v1 (Skills Inventory + Records Output)

**Verdict:** ⚠️ Conditional
**Three Required findings — write-path spec gap on `RecordsStore.write_entry`, missing wire-call-site invocation in Section 6, and CrewProfile Big Five field shape (nested under `.personality`, not flat) — all surface-correct in v1's generic `dict[str, float]` interface but mis-narrated in the Dependencies / Verified footer.**

Wave 16 single-prompt review. AD-685b dispatch-time pre-check already caught the original `crew_profile_store` phantom (validated; commit 77788e2). Remaining FP (`SystemConfig.creative_expression`) is the introduced-by-Section-5 pattern (Wave 5 convention #1, expected). v1 scope-discipline confirmed: no smuggled time-allocation / code-as-creative / cultural-emergence / collaboration logic. AD-526 orthogonality confirmed (`creative/` vs `recreation/`).

---

## Required (must fix before building)

### 1. `RecordsStore.write_entry` write-path spec gap (Section 4)

`Section 4 — CreativeOutputWriter.publish` describes the public interface but never specifies what arguments it actually passes to `RecordsStore.write_entry(...)`. Verified signature at `knowledge/records_store.py:89`:

```
async def write_entry(
    self,
    author: str,
    path: str,
    content: str,
    message: str,                       # required positional
    *,
    classification: str = "ship",
    status: str = "draft",
    department: str = "",
    topic: str = "",
    tags: list[str] | None = None,
    metrics: ...                        # truncated by read window
)
```

Section 4 currently shows only the `publish(...)` signature, no body. The Builder needs explicit guidance for:

- **`author`** — should be `author_callsign` (verify or use a different identity field).
- **`message`** — git commit message; not derivable from caller args. Suggest `f"creative({medium}): {topic_slug} by {author_callsign}"`.
- **`status`** — Section 4 doesn't pass it; defaults to `"draft"` per signature. AD-525 design implies published works should be `status="published"` or similar — needs a decision.
- **`topic`** — likely `topic_slug` itself (or empty).
- **`tags`** — `[skill_id, medium]` would be reasonable; prompt is silent.
- **`metrics`** — None / empty for v1.
- **Frontmatter discipline.** Solution Overview claims frontmatter `type: creative`, `medium`, `author`, `department`. `RecordsStore.write_entry` accepts `content` as the body — the Builder needs to decide whether the writer prepends a YAML frontmatter block to `content` itself (likely yes; mirrors notebook pattern) or whether `write_entry` does it. Verify how notebooks add frontmatter today (grep `_records_store.write_notebook` and `write_entry` callers).

**Fix:** Add a `Section 4a — write_entry call shape` subsection that shows the explicit kwarg-by-kwarg call and the frontmatter assembly pattern, with grep evidence from an existing `write_entry` caller (e.g. `proactive.py:3033` or `cognitive/dreaming.py:816`).

### 2. Section 6 — `_wire_creative_expression` invocation site missing

The prompt defines `_wire_creative_expression(...)` but does not specify where it is *called* in `finalize.py`. Verified call-site pattern at `startup/finalize.py:249` and `:252`:

```
   249: if _wire_anomaly_window(runtime=runtime, config=config):
   252: if await _wire_self_distillation(runtime=runtime, config=config):
```

Without an explicit instruction to add `if await _wire_creative_expression(runtime=runtime, config=config):` into the entry-point function (around the same band as the other wires), the Builder may add the function and leave it as dead code on warm boot.

**Fix:** Add explicit Section 6 sub-instruction:

> Add invocation in the wire-orchestration entry point in `startup/finalize.py` at the band where `_wire_anomaly_window` (line 249) and `_wire_self_distillation` (line 252) are invoked. Pattern: `if await _wire_creative_expression(runtime=runtime, config=config): logger.info("...")` (the function is async because future-proofs for I/O if any sub-AD adds persistence; keep it async even though v1 body has no awaits).

(If v1 body really has no `await`, drop `async` to match `_wire_anomaly_window`'s sync shape — pick one and lock it.)

### 3. CrewProfile Big Five fields are NESTED, not flat — Dependencies + Verified footer mis-narrate

User's verification point #6 confirmed by grep:

```
grep -n "openness" src/probos/crew_profile.py
   55:    - openness: ...                    (PersonalityTraits docstring)
   65:    openness: float = 0.5              (PersonalityTraits field)
```

`CrewProfile` is at `crew_profile.py:116`. Its Big Five fields live on a nested dataclass:

```
@dataclass
class CrewProfile:
    ...
    personality: PersonalityTraits = field(default_factory=PersonalityTraits)
    personality_baseline: PersonalityTraits = field(default_factory=PersonalityTraits)
```

Real callers must pass `profile.personality.openness`, NOT `profile.openness`. The prompt's Dependencies section says:

> `runtime.profile_store` — read-only consumer for Big Five trait fields (verified at acm.py:300; real attribute name is `profile_store` NOT `crew_profile_store`).

Two problems:

- **(a) `runtime.profile_store` is never actually wired.** `acm.py:300` is `if hasattr(runtime, 'profile_store') and runtime.profile_store:` — defensive `hasattr` guard. Grep confirms `runtime.profile_store = ...` is **not assigned anywhere in `src/probos/`**. The wired stores are `runtime._counselor_profile_store` (private), `HttpFetchAgent._profile_store` (class-level), and `runtime.service_profiles` (`ServiceProfileStore`). `ProfileStore` (crew_profile.py:215) exists as a class but no public-attribute wiring exists. AD-685b's catch fixed `crew_profile_store` → `profile_store`, but the deeper truth is *neither* is wired. The "verified" footer asserts a runtime attribute that does not exist — verify-first slip.
- **(b) `dict[str, float]` adapter pattern.** v1's `affinity_score(skill_id, traits: dict[str, float])` is generic enough to *survive* the nested-vs-flat issue, but only because callers will need to call `profile.personality.to_dict()` (verified at `crew_profile.py:86` returns the `dict[str, float]` shape via `asdict`). The prompt should document this adapter explicitly.

**Build doesn't break in v1** (the interface is generic). Narrative does break — Builder reading top-to-bottom will be confused, future grandchild ADs will inherit the wrong dependency claim, and AD-685b's pre-check is left looking like it caught a smaller issue than it did.

**Fix:** Three edits.

- Dependencies section: replace the `runtime.profile_store` line with:
  > `crew_profile.PersonalityTraits.to_dict()` — used by callers to project a `CrewProfile` into the `dict[str, float]` shape `affinity_score` expects. v1 does NOT depend on `runtime.profile_store` — that attribute is currently a `hasattr`-guarded defensive read (acm.py:300) with no wiring; whether to wire it is out of scope (file as separate hygiene AD if desired).
- Verified Against Codebase footer: drop the `runtime.profile_store` claim; replace with:
  > `grep -n "openness" src/probos/crew_profile.py` → confirms PersonalityTraits at crew_profile.py:65 has flat Big Five floats. CrewProfile (crew_profile.py:116) nests these under `.personality: PersonalityTraits` (verified line 138). Callers project via `profile.personality.to_dict()` → `dict[str, float]`.
- Test plan: add `test_affinity_score_accepts_personality_traits_to_dict_shape` — explicitly calls `affinity_score(skill_id, PersonalityTraits().to_dict())` to lock the adapter contract into the test surface.

---

## Recommended (should fix)

### 1. `CreativeOutputError` referenced but undefined (Section 4 + Test 17)

Section 4's docstring says:

> Raises: `CreativeOutputError`: if records_store unavailable or write fails.

Test 17 (`test_publish_raises_when_records_store_unavailable`) asserts it. The exception class is never defined. Section 1's package layout lists `__init__.py`, `skills_registry.py`, `output_writer.py` — no `errors.py`.

**Fix:** Either define `class CreativeOutputError(Exception): ...` at the top of `output_writer.py` or add `errors.py` to Section 1. Per Wave 5 convention #20 (reality-check small types) define inline in `output_writer.py` to avoid orphan modules.

### 2. `Section 5 — skills_catalog: list[str]` is dead code in v1

Field is added to Pydantic config but explicitly "v1 ignores." Per convention #7 (no-theater) and convention #14 (aggressive pre-deferral): drop it from v1 and add it in AD-525b with the plugin loader. If kept, document with an explicit `# Reserved for AD-525b plugin loader; v1 reads but ignores` comment in the source so future code-search hits the rationale.

### 3. `Section 4 — list_works_by_author` not in test plan

Method is in the public surface but no test exercises it. Either add `test_list_works_by_author_returns_only_authors_works` (already named in test plan #18 — verify it actually targets this method) or drop the method from v1.

(Re-reading test plan #18 in the prompt: the test name does match. Mark this finding as "scratch" if the test body actually exercises `list_works_by_author`. Builder should confirm during test stub-out.)

### 4. Wire function async/sync mismatch (related to Required #2)

Section 6's `_wire_creative_expression` is declared `async def` but has no `await` in the body. Compare:

- `_wire_anomaly_window` — sync (`def`), no I/O.
- `_wire_self_distillation` — async (`async def`), opens a SQLite connection via `await`.

AD-525 v1 has no I/O in wiring. Make it sync (`def`) to match `_wire_anomaly_window`'s shape. If a future grandchild AD adds persistence (e.g. AD-525b's plugin loader reading from disk), promote to async at that point.

---

## Nits (style/minor)

### 1. `proactive.py:2111` citation is stale

Solution Overview claims notebook pattern verified at `proactive.py:2111`. Current code:

```
proactive.py:2508: await self._runtime._records_store.write_notebook(...)
proactive.py:3033: await self._runtime._records_store.write_entry(...)
proactive.py:3013: entry = await self._runtime._records_store.read_entry(...)
```

The actual `write_entry` caller is at `proactive.py:3033`. Update citation. Note also that the notebook pattern uses `write_notebook` (specialized) while AD-525 uses `write_entry` (generic) — these are *different* methods. Builder should not assume `write_notebook`'s frontmatter assembly applies; check `write_entry` callers (e.g. `cognitive/dreaming.py:816`) for frontmatter discipline.

### 2. "Idempotent on skill_id (overwrites)" — wording

`register_skill()` overwriting is not idempotent in the strict sense (idempotent = same outcome on repeat). Either:
- "Last-write-wins on `skill_id` collision" (clearer), or
- Just "Overwrites existing entry with same `skill_id`."

### 3. Section 5 `default_classification: str` should be `Literal["ship", "department", "private"]`

Pydantic v2 supports `Literal` for enum-like string fields. Documented values are listed in the docstring; lift them into a `Literal[...]` type for fail-fast at config parse time (Engineering Principles standing rule: validation at parse time, not runtime). Defer if Pydantic v2 import surface friction is high — sub-nit.

---

## Verified (passed review)

### Pre-deferral honesty (user verification point #1)

- v1 ships ONLY `CreativeSkillsRegistry` + `CreativeOutputWriter`.
- No time-allocation gating logic. `publish()` has no rank check, no rate limiter, no budget enforcement. (Hard-stop #6 satisfied.)
- No code-as-creative branching. `publish()` writes Markdown only; no BuildSpec hooks.
- No cultural-emergence detection. No multi-agent corpus analysis; no Archive (AD-434) consumer.
- No collaboration logic. Single-author writes only; no co-author parameter.

### AD-526 orthogonality (user verification point #2)

- `src/probos/recreation/` exists with `engine.py`, `metadata.py`, `preferences.py`, `service.py` (4 files; verified by `file_search`).
- AD-525 creates `src/probos/creative/` (does NOT exist today; verified by `file_search`).
- Zero file-name collisions. Orthogonal package paths.

### AD-685b dispatch-time catch validation (user verification point #3)

- `crew_profile_store` → `profile_store` was caught by AD-685b's method-call AST validator at dispatch (commit 77788e2 per user).
- This is AD-685b's first non-trivial real-world catch. Wave 15 tooling validated.
- Remaining 1 documented FP (`SystemConfig.creative_expression`) confirmed to be Section 5's introduced-by-prompt wiring (Wave 5 convention #1 pattern). Not a real defect.
- **Caveat:** AD-685b caught the *typo* but did not catch the *deeper* defect — that `runtime.profile_store` itself is not wired (Required #3). AD-685b validates "does the receiver class exist and does the method exist on it" but not "is the receiver attribute actually assigned in startup wiring." That latter check is AD-685c/d territory or a separate hygiene candidate. Document as limitation.

### Section 0 EventType collisions (user verification point #4)

- `grep -n "CREATIVE" src/probos/events.py` — zero hits. Confirmed collision-free.
- Both `CREATIVE_WORK_PUBLISHED` and `CREATIVE_SKILL_AFFINITY_QUERIED` are net-new.

### Public-attribute wiring (Wave 5 convention #1, user verification point #5)

- `runtime.creative_skills_registry` — no leading underscore. ✅
- `runtime.creative_output_writer` — no leading underscore. ✅
- Both are net-new attributes; no collision with existing `runtime.*` (verified by grep).

### `runtime.records_store` shape

- `runtime.records_store` is a public `@property` at `runtime.py:951` returning `self._records_store` (assigned at `runtime.py:1315` from `cog.records_store`).
- AD-525's `CreativeOutputWriter` constructor's fallback `records_store or runtime.records_store` is correct.

### Frozen-dataclass field ordering (Section 2)

- All Big Five fields default to `0.5`; `medium: tuple[str, ...]` has no default. Field order `skill_id, name, medium, openness, conscientiousness, ...` correctly places non-defaulted fields first. No Wave 5 convention #5 violation.

### Hard-stops (dispatch points 1-6)

| # | Hard-stop | Status |
|---|---|---|
| 1 | Phantom API in shipping content beyond 1 documented FP | None found beyond noted Required #3 footer slip (narrative, not code-shape) |
| 2 | AD-526 file-name collision | None |
| 3 | CrewProfile Big Five fields don't exist with assumed names | **Hit — see Required #3.** Real shape: nested under `.personality: PersonalityTraits`. v1 surface survives via `dict[str, float]` adapter. |
| 4 | Section 0 EventType collisions | None |
| 5 | v1 scope creep | None |
| 6 | `creative/` namespace already in use | None (verified `file_search` zero hits) |

Required #3 is a soft hard-stop hit per dispatch text ("If field names differ ... surface as Required") — surfaced as Required, not as a build blocker beyond the Dependencies/footer fix.

---

## Convention Audit (23 standing conventions)

Audited against Wave 5 #1-7, Wave 5-7 Addendum #8-15, Wave 8 Addendum #16-19, Wave 9 Addendum #20-22. Per #15 relaxed tolerance: 1 ⚠️ allowed.

| # | Convention | Compliance |
|---|---|---|
| 1 | Public-attribute wiring | ✅ |
| 2 | stdlib-only persistence | N/A (no persistence in v1) |
| 3 | Coordinator-then-dispatch | ✅ (Skills Registry + Output Writer; no dispatch logic) |
| 4 | Onboarding superset-filter | N/A |
| 5 | `init_communication` emit_event_fn | N/A (uses `runtime.emit_event` via `_emit_event_fn` late-bind) |
| 6 | PowerShell `\b` rename | N/A |
| 7 | Two-pass review converges | (process; deferred to pass-2) |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A (no cross-layer import) |
| 9 | ASCII-only source comments | ✅ (prompt body uses `--` and `->`; no Unicode arrows) |
| 10 | `runtime.work_item_store` clarity | N/A |
| 11 | `__new__`-bypass defensive `getattr` | N/A |
| 12 | Solution Overview ↔ Revision drift | N/A first pass |
| 13 | Pool template name collision | N/A (no new pool) |
| 14 | Aggressive pre-deferral | ✅ (3 of 5 capabilities deferred at draft time; convention exemplar) |
| 15 | Relaxed tolerance | (3 Required → ⚠️ Conditional verdict) |
| 16 | Dispatch-time phantom-API pre-check | ✅ ran; caught `crew_profile_store` real phantom |
| 17 | Mutable client state on instance | ✅ (no class-level mutables) |
| 18 | `httpx.Response` mocks | N/A (no httpx) |
| 19 | MCP session-id from headers | N/A |
| 20 | Cross-wave dep verification reads SHIPPED CODE | ⚠️ slip on `runtime.profile_store` (Required #3) |
| 21 | Structural-defect propagation | (process; reactive only on this single AD) |
| 22 | v1 isolation as Northstar default | ✅ (no integration into AD-526, AD-434, AD-357 in v1) |
| (23) | AD-685b method-call AST | ✅ ran; caught typo |

**Compliance:** 1 slip on convention #20 (`runtime.profile_store` shipped-code claim is wrong). Within tolerance per #15. → ⚠️ Conditional.

---

## Summary

| Tier | Count |
|---|---|
| Required | 3 |
| Recommended | 4 |
| Nits | 3 |
| Verified | 7 areas + Hard-stop matrix + Convention audit |

**Verdict:** ⚠️ Conditional — apply Required #1-3 in revision. Recommended #1-4 fold unless scope creep. Nits judgment-call. Re-converge in pass-2.

**Top failure modes if Required not addressed:**
1. **Required #1** — Builder will guess at `RecordsStore.write_entry` kwargs, likely producing inconsistent commit messages and incorrect frontmatter assembly. Test 14 may pass while real artifact shape regresses notebooks-vs-creative consistency.
2. **Required #2** — Wired services land but `_wire_creative_expression` is never invoked; `runtime.creative_skills_registry` is `None` at runtime; tests 19-20 still pass (they construct the writer directly).
3. **Required #3** — Narrative drift in DECISIONS.md and grandchild ADs; AD-525b/d/e consumers will inherit the wrong attribute claim and re-introduce phantom dependencies.


---

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**All three Required addressed in Section 4a (write_entry kwarg call), Section 6b (wire invocation), and Dependencies/Section 3 (nested Big Five + `to_dict` adapter). All four Recommended folded; all three Nits applied. One residual DECISIONS.md draft contradiction noted as Nit-only.**

### Resolution Audit

| Pass-1 Required | Status | Evidence |
|---|---|---|
| R1 (`write_entry` kwarg spec) | ✅ | New Section 4a explicit kwarg call (`author`, `path`, `content`, `message`, `classification`, `status="published"`, `department`, `topic=topic_slug`, `tags=["creative", medium, skill_id]`, `metrics=None`); all match `records_store.py:89-103` signature. Solution Overview corrected: frontmatter assembled by `write_entry` itself (verified at records_store.py:113-148), `medium`/`skill_id` encoded via `tags`. `message=f"Creative work: {topic_slug} (medium={medium}; skill={skill_id})"` is descriptive. Caller pattern citation updated to `proactive.py:3033`. |
| R2 (wire invocation site) | ✅ | Section 6 split into 6a (define) + 6b (invoke). 6b inserts `if _wire_creative_expression(runtime=runtime, config=config):` at `startup/finalize.py:253`, immediately after `_wire_self_distillation` invocation block. `_wire_creative_expression` declared sync `def` (matches `_wire_anomaly_window` line 25 shape). No `await` in invocation — explicitly called out. Recommended #4 absorbed. |
| R3 (nested Big Five + adapter) | ✅ | Dependencies section deletes false `runtime.profile_store` claim, adds `crew_profile.PersonalityTraits.to_dict()` as canonical adapter with grep evidence. Section 3 `affinity_score` interface stays generic `dict[str, float]`. Section 3 example block shows `traits = profile.personality.to_dict()`. Test #21 (`test_affinity_score_accepts_personality_traits_to_dict_shape`) added — locks adapter contract. Soft-warning on unwired `runtime.profile_store` documented (read-only consumer; affinity returns 0.0 when absent — locked by test #7). |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| Rec #1 (`CreativeOutputError`) | ✅ | Section 1 specifies `class CreativeOutputError(Exception)` inline at top of `output_writer.py` (Wave 9 convention #20). Section 4a raises on missing `records_store` and chains via `from exc` on `write_entry` failure. |
| Rec #2 (`skills_catalog` dead-code) | ✅ | Dropped from Section 5; deferred to AD-525b plugin loader. Convention #14 honored. |
| Rec #3 (`list_works_by_author` coverage) | ✅ | Test #18 (`test_list_works_by_author_returns_only_authors_works`) targets it — already in plan; pass-1 marked scratch; revision left as-is. |
| Rec #4 (wire async/sync mismatch) | ✅ | Folded into R2: `_wire_creative_expression` is sync `def`, invocation is `if _wire_...(...)` not `if await _wire_...(...)`. |

| Pass-1 Nit | Status | Notes |
|---|---|---|
| Nit #1 (stale `proactive.py:2111`) | ✅ | Solution Overview + Verified footer updated to `proactive.py:3033`. |
| Nit #2 (idempotency wording) | ✅ | Section 3 docstring: "Last-write-wins on `skill_id` collision". |
| Nit #3 (`Literal` type) | ✅ | Section 5: `default_classification: Literal["ship", "department", "private"]`. |

### Verification Points

1. **R1 kwargs match signature.** Verified live: `records_store.py:89-103` exposes `(author, path, content, message, *, classification="ship", status="draft", department="", topic="", tags=None, metrics=None)`. Section 4a publish() body passes all kwargs in correct shape; `tags=["creative", medium, skill_id]` is the chosen encoding for the otherwise-unsupported `medium`/`skill_id`. `message` is descriptive. ✅
2. **R2 invocation is sync.** Verified at `startup/finalize.py:25` (`_wire_anomaly_window` sync `def`, sync invocation at line 249) vs `:80` (`_wire_self_distillation` async, awaited at line 252). Section 6b mirrors the line 249 pattern (sync). No `await`. Insert band line 253 verified. ✅
3. **R3 nested Big Five + adapter.** Verified live: `crew_profile.py:51` `class PersonalityTraits` (flat floats), `:138` `personality: PersonalityTraits` field on `CrewProfile`. `to_dict()` lives at `crew_profile.py:85` (prompt cites `:86` — off-by-one cosmetic, sub-nit, not flagging). Adapter contract locked by new test #21. `runtime.profile_store` unwired-soft-warning honored. ✅
4. **Frontmatter shape correction.** Solution Overview no longer claims arbitrary `type/medium/author/department` keys. Section 4a uses `tags=["creative", medium, skill_id]` consistently. **Residual contradiction (NEW Nit, see below):** DECISIONS.md draft block in Tracking section still says `Frontmatter includes type: creative, medium, author, department.` ✅ for the build-driving sections; ⚠ for the DECISIONS draft only.
5. **Pre-check.** `./scripts/phantom-api-precheck.ps1 prompts/ad-525-creative-expression-v1.md` → 1 phantom (`SystemConfig.creative_expression`, documented FP introduced by Section 5, Wave 5 convention #1 pattern), 0 NEW phantoms. `runtime.creative_skills_registry.list_skills(...)` flagged as `[no_class_resolution]` skip (introduced by Section 6a wiring; expected). ✅

### New Findings

1. **Nit-N1 (DECISIONS.md draft residual).** The DECISIONS.md draft inside the Tracking section (line ~258 of the prompt) still reads:
   > Frontmatter includes `type: creative`, `medium`, `author`, `department`.

   This contradicts the corrected Section 4a (frontmatter is auto-assembled by `write_entry`; `medium`/`skill_id` are encoded via `tags`). Because the build-driving sections (Solution Overview, Section 4a) are correct, this is a Nit only — Builder will follow Section 4a. Recommended fix during commit:

   > Frontmatter is assembled by `RecordsStore.write_entry` (author, classification, status, created/updated, optional department/topic/tags); AD-525 encodes `medium` and `skill_id` in `tags=["creative", medium, skill_id]`.

   Not blocking ✅. File the edit as a single-line touch alongside Builder's normal DECISIONS.md write.

### Pre-Check Output

```
=== prompts/ad-525-creative-expression-v1.md ===
  1 phantom symbol(s):
    - [<Class>.<method>] SystemConfig.creative_expression       (FP — introduced by Section 5)
  Skipped (unresolved class):
    ~ [no_class_resolution] runtime.creative_skills_registry.list_skills(...)   (FP — introduced by Section 6a)

=== Summary ===
Prompts scanned: 1
Total phantom candidates: 1
```

0 NEW phantoms. Wave 5 convention #1 expected pattern (introduced-by-prompt wiring) accounts for both items.

### AD-685b Catches-Per-Wave Note

- Wave 15 (own-validation): 0 catches. (AD-685b validated against post-AD-680 ledger; tooling clean.)
- Wave 16 (this wave): **1 real catch** — `crew_profile_store` → `profile_store` typo at draft time (commit 77788e2). First non-trivial real-world catch since rollout.
- Caveat re-affirmed (carried forward from pass-1 § Verified): AD-685b validates **method existence on receiver class**, not **runtime attribute wiring**. The deeper "is `runtime.profile_store` actually wired?" check is AD-685c/d territory. Document as limitation, file separate hygiene-AD if/when warranted.

Catches-per-wave count: **Wave 15 = 0; Wave 16 = 1.** AD-685b ledger updated.

### Convention Compliance (post-revision)

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ |
| 7 | Two-pass review converges | ✅ (this is pass-2; ✅ Approved) |
| 9 | ASCII-only prompt body | ✅ |
| 14 | Aggressive pre-deferral | ✅ (3 of 5 capabilities deferred + skills_catalog dropped) |
| 15 | Relaxed tolerance | N/A — 0 Required remaining |
| 16 | Dispatch-time phantom-API pre-check | ✅ (1 documented FP, 0 NEW) |
| 20 | Cross-wave dep verification reads SHIPPED CODE | ✅ (false `runtime.profile_store` dep deleted) |
| 23 | AD-685b method-call AST | ✅ (caught real phantom at draft) |

**Verdict:** ✅ Approved. Builder may proceed. One Nit-only DECISIONS.md draft adjustment recommended at commit time but is non-blocking.
