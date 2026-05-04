# Review: AD-530 v1 — Information Classification Enforcement (Disclosure Gate)
**Verdict:** ❌ Not Ready
**Two HARD-STOPs both fired by the prompt's own checklist: `_CLASSIFICATION_LEVELS` keys differ (`confidential` does not exist) AND the disclosure-direction check is inverted relative to records_store semantics.**

Scope assessment: v1 deferral honesty is clean (no AD-530b/c/d smuggled in), privacy invariant is correct, sibling-pattern conformance with AD-456 is good. The blockers are semantic (hierarchy keys + comparison direction), not architectural.

## Required (must fix before building)

1. **`_CLASSIFICATION_LEVELS` keys differ from prompt's assumption — Hard-Stop #1 fired.**

   `grep -n "_CLASSIFICATION_LEVELS = " src/probos/knowledge/records_store.py` (line 27):
   ```python
   _CLASSIFICATION_LEVELS = {
       "private": 0,
       "department": 1,
       "ship": 2,
       "fleet": 3,
   }
   ```

   AD-530 assumes the keys are `ship` / `department` / `confidential` (Section 2 docstring, Test #13 name, prompt prose, DECISIONS entry, Solution Overview). The key `confidential` **does not exist** in the live hierarchy; the key `private` (0) and the key `fleet` (3) do.

   Concrete breakage in Section 2:
   - `confidential_lvl = _CLASSIFICATION_LEVELS.get("confidential", 0)` → returns the default `0` because no `confidential` key exists. By accident this equals `_CLASSIFICATION_LEVELS["private"]`, but the intent is opaque and a future re-numbering breaks it silently.
   - `# default: ship-level` comment + `.get(source_classification, 2)` defaults unknown source to `ship` (the *broadest* level) — see Required #2.

   Fix: rewrite Section 2 around the real 4-tier hierarchy. The `confidential` framing in the docstring, DECISIONS entry, and Test #13 name must change to `private` (the actual most-restricted level) or to a deliberate not-tied-to-key-name phrasing. Pattern-skip logic must reference the real most-restricted level (`private`, value 0) directly, not a `.get("confidential", 0)` accident.

2. **Disclosure check direction is inverted relative to records_store semantics — Hard-Stop #1 (semantic variant).**

   `_CLASSIFICATION_LEVELS` numbers represent *openness* (higher index = more broadly readable), confirmed by records_store.py:841:
   ```python
   if _CLASSIFICATION_LEVELS.get(doc_class, 0) > _CLASSIFICATION_LEVELS.get(scope, 2):
       continue  # doc is more-open than search scope; filter out
   ```
   And by records_store.py:716–725 — `private` is the most restricted (only author reads), `ship` is broadly readable by all crew, `fleet` even broader.

   AD-530 Section 2 reads:
   ```python
   if dst_lvl < src_lvl:  # destination cannot see this restriction
       decision = DisclosureDecision(allowed=False, ...)
   ```

   Walk-through with real keys:
   - Source = `ship` (2, broadly readable), destination = `department` (1) → `1 < 2` → BLOCK. **Wrong.** Ship-level content IS readable by department members per records_store.read_document.
   - Source = `private` (0, author-only), destination = `ship` (2) → `2 < 0` is False → ALLOW. **Wrong.** Private content must NOT disclose to broad audiences.

   The check is BACKWARDS for *openness* semantics. Disclosure is allowed when content is *more open* than the destination requires, i.e. `src_lvl >= dst_lvl`. So the gate should BLOCK when `src_lvl < dst_lvl` (content is more restricted than destination's openness expectation).

   Or, recommended for clarity: introduce explicit "restriction level" semantics (invert the numbering for the disclosure check) so the comparison matches operator intuition. Either approach is acceptable; the prompt must pick one and rewrite Section 2 + tests #4–7 accordingly.

3. **Unsafe-direction default for unspecified source classification.**

   `src_lvl = _CLASSIFICATION_LEVELS.get(source_classification, 2)` defaults unknown source to `ship` (2, broadest openness). For a *disclosure gate*, an unlabeled source should be treated as MOST restrictive (i.e. `private`, value 0) so unlabeled content cannot leak by mistake.

   Default destination to `2` (ship) is also wrong-direction once you pick disclosure semantics; should default to most restricted destination so unknown destinations are gated.

   Fix in tandem with Required #2 once the comparison direction is settled. Test #7 (`test_check_disclosure_unspecified_classification_defaults_to_ship`) must rename and re-assert against the safe-default direction.

4. **`api_key_like` regex has high false-positive rate against existing fixture shapes — pattern set must be tightened or pattern removed from v1 default.**

   Pattern: `r"\b[A-Za-z0-9_-]{32,}\b"`. Confirmed matches:
   - UUIDs: 36 chars `0-9a-f-`. The `-` is allowed → matches. Fixtures use UUIDs widely (event IDs, agent IDs in some forms, work item IDs, doc IDs).
   - Commit hashes: 40 hex chars → match.
   - Base64-ish blobs: match.
   - Long agent_id strings without `:` separators (some legacy paths): match.
   
   Per Hard-Stop #5 in the prompt, "pattern set causes excessive false positives in existing tests" is a hard-stop. Even though v1 is observational (no message mutation), every false-positive triggers a `CLASSIFICATION_DISCLOSURE_BLOCKED` event. That makes the event channel noise, not signal.

   Two acceptable fixes (architect's call):
   - **(A) Drop `api_key_like` from `_DEFAULT_SENSITIVE_PATTERNS` for v1.** Keep it as a `register_pattern()` opt-in. Rationale: v1's job is to ship a gate plumbing surface; the highest-FP pattern should not be in the default set. AD-530 v2 / d revisits patterns once integration data exists.
   - **(B) Tighten to formats that do NOT collide with UUID/hash shapes.** E.g. require at least one of: prefix `sk-`, `pk_`, `Bearer `, `AKIA`, `ghp_`, etc. (typical real API-key prefixes). Drop the bare-32-char rule.
   
   Strong preference for (A) given v1's observational scope. Update Test #9 accordingly (assert no default pattern matches a 40-char hex string when scanner is at default config; assert opt-in via `register_pattern()` re-introduces the 32-char heuristic).

## Recommended

1. **Wave 5 convention #14 — DECISIONS entry needs explicit forcing functions for AD-530b/c/d.**
   
   Current entry says "deferred to AD-530b/c/d" but only AD-530b lists a forcing function ("a designed agent (Worf/SecurityAgent) needs the runtime API"). AD-530c and AD-530d need concrete forcing functions: e.g. AD-530c "Audit trail extension when Wave-N introduces structured-classified-read pattern" or "after AD-530d's first integration site needs blame attribution"; AD-530d "after AD-530b's first Standing Order changes a label and the Captain reviews the resulting blocked-event volume."

2. **AD-456 sibling-pattern divergence — `_emit_event` field naming.**
   
   AD-456 uses `emit_event` (public field on dataclass). AD-530 uses `_emit_event` (underscored kwarg into `__init__`). Per Wave 5 convention #1 (public attributes), align with AD-456: rename to `emit_event` (no underscore) on `ClassificationGate.__init__`. Trivial change; keeps the security/ package internally consistent.

3. **Defensive try/except around emit log-level diverges from AD-456.**
   
   AD-456 `_emit_blocked` logs `logger.warning("AD-456: EGRESS_BLOCKED emit failed ...")`. AD-530 logs `logger.debug("AD-530: emit_event failed", exc_info=True)`. A blocked emit failure is operational signal worth a `logger.warning` to stay parallel with AD-456. Trivial fix.

4. **`register_pattern` lacks duplicate-name protection.**
   
   `self._patterns.append((name, re.compile(pattern)))` will accept the same `name` twice. For v1 observational it's harmless, but the second registration silently masks/duplicates. Add a one-line guard: skip if `name` already registered (or warn-and-replace; pick one). Defer test if you prefer; at minimum document the chosen semantics in the docstring.

5. **DECISIONS entry "private prefixes" pattern wording overlaps the classification key `private`.**
   
   After Required #1's rewrite, the DECISIONS sentence "Built-in pattern set (4 regex patterns for api-key shapes, captain-directive markers, **private prefixes**, secret formats)" becomes ambiguous: "private prefixes" reads as "the `private` classification level" not "regex pattern matching strings beginning with `private:`." Rename pattern in code from `private_marker` to `restricted_prefix` (or similar) and update DECISIONS accordingly. Avoids semantic collision with the now-known-real key.

## Nits

- Section 4 wiring uses `runtime.classification_gate._patterns` to log the pattern count. Wave 5 convention #1: don't reach through underscored attrs from outside the owning class. Add a public `pattern_count: int` property (or just `len(runtime.classification_gate.patterns)` if you make `_patterns` public). Same fix as Wave 14 review's "private-attr access in wiring code" anti-pattern.
- Section 1's `DisclosureDecision.reason` field uses unstructured strings (`"ok"`, `"clearance_below_source"`, `"sensitive_pattern_matched"`). Consider an enum or `Literal[...]` for type-safety. Optional; v1 has only 3 values.
- Test plan lists 18 tests; verify acceptance-criteria language matches ("18 tests pass" — exact count).
- "Verified Against Codebase" footer says `(Builder reads exact hierarchy at line 27-32 to match)` — that's a delegation, not a verification. Fix the prompt to actually state the keys (`private`/`department`/`ship`/`fleet`) so the Builder cannot accidentally re-introduce the `confidential` assumption.

## Verified

- **Privacy invariant ✓.** Section 2 `_emit_blocked` payload contains `content_length` (NOT content) and `blocked_phrases` is a list of pattern *names* (NOT matched substrings). Tests #14/#15 assert both. Privacy regression risk is correctly mitigated.
- **Pre-deferral honesty ✓.** v1 ships only ClassificationGate + pattern scanner + EventType + Pydantic config + finalize wiring. No Security Chief runtime API (AD-530b smuggled in). No full-audit-trail event-on-every-read (AD-530c). No mutation/redaction in WardRoomService.create_post or LLMClient prompt builder (AD-530d). "What This Does NOT Change" section explicitly enumerates each.
- **AD-456 sibling-pattern conformance (mostly) ✓.** Module placement at `src/probos/security/classification.py` mirrors `security/egress.py`. Defensive try/except around emit_event matches the AD-456 pattern. Public `runtime.classification_gate` attribute (no underscore). Wiring location (alongside `_wire_creative_expression` etc. in `startup/finalize.py:80–280`) is correct. Divergences flagged as Recommended #2/#3 only.
- **EventType `CLASSIFICATION_DISCLOSURE_BLOCKED` is collision-free ✓.** `grep -n "CLASSIFICATION_DISCLOSURE_BLOCKED\|EGRESS_BLOCKED" src/probos/events.py` returns only the AD-456 EGRESS_BLOCKED entry; no existing classification-* event.
- **`runtime.classification_gate` attribute is free ✓.** `grep -rn "runtime.classification_gate" src/probos/` returns 0 hits before AD-530.
- **Pre-check FP documented ✓.** `SystemConfig.classification_gate` introduced by Section 3 wiring per Wave 5 convention #1; legitimate.
- **AD-685 / AD-685b coverage:** ClassificationGate is sync (no async/sync mismatch risk); return shape `DisclosureDecision` is a frozen dataclass with explicit fields; public-attribute wiring follows convention #1. No phantom-API findings beyond Required #1's `confidential` key issue.

---

## Convention Audit (23 standing conventions; convention #15 tolerance breached)

| # | Convention | Status |
|---|---|---|
| 1 | Public attributes (no `_` from outside) | ⚠ Section 4 reaches `._patterns` (Nit) |
| 2 | Sibling-pattern conformance | ✓ (minor: emit_event field naming, log level) |
| 3 | Default-False on transitional flags | n/a (no transitional flag; `enabled: bool = True` is the gate's normal-on switch) |
| 4 | Aggressive pre-deferral | ✓ |
| 5 | Phantom-API discipline | ❌ Required #1 |
| 6 | Frozen-dataclass field ordering | ✓ |
| 7 | Pydantic Field(default_factory=...) for mutables | ✓ (no mutable defaults) |
| 8 | Wiring at finalize.py | ✓ |
| 9 | EventType collision-free | ✓ |
| 10 | Privacy in event payloads | ✓ |
| 11 | Test-count accuracy | ✓ (18 tests; matches acceptance criteria) |
| 12 | DECISIONS entry forcing functions | ⚠ Recommended #1 |
| 13 | "What This Does NOT Change" explicit | ✓ |
| 14 | v1 scope minimal | ✓ |
| 15 | ≤1 ⚠ tolerance | ❌ Breached (4 Required + 5 Recommended) |
| 16 | Verified-Against-Codebase footer with grep | ⚠ Footer present but delegates ("Builder reads exact hierarchy") instead of stating real keys |
| 17 | Reuse existing infra (no duplication) | ✓ (consumes `_CLASSIFICATION_LEVELS` read-only) |
| 18 | Sync vs async match call pattern | ✓ (sync gate, sync caller path) |
| 19 | Hard-stops explicit and concrete | ✓ (5 hard-stops listed) |
| 20 | Test plan boundary cases | ✓ (happy + clearance-fail + pattern-fail + privacy-leak) |
| 21 | Cross-link orthogonal ADs in DECISIONS | ✓ (AD-456 + AD-679 cited as orthogonal) |
| 22 | Acceptance criteria itemized | ✓ |
| 23 | Module placement under existing package | ✓ (`security/classification.py`) |

Convention #15 breach (4 Req > 1 ⚠) → revision required (Stage 2 pass-2).

## Top failure modes if shipped as-drafted

1. Test #6 (`test_check_disclosure_blocked_when_clearance_lower`) passes by accident because the inverted comparison happens to match the inverted setup the test author wrote. Real callers (when integrated in AD-530d) experience the inversion and broadly-readable `ship` content gets blocked from `department` viewers. The gate is unusable.
2. Every Ward Room post containing a UUID, commit hash, or any 32+ char alphanum-ish token emits a `CLASSIFICATION_DISCLOSURE_BLOCKED` event. Builder's tests pass (synthetic content), but downstream consumers see noise. Builder's `pytest tests/` does not catch this because no current test feeds real Ward Room fixture content through the gate.
3. `confidential` key absence is masked by Python's `dict.get(key, default)` returning 0 by accident. Future Builder edits to the hierarchy (e.g. rename `private` → something else) will produce silent semantic drift.

## Re-review checklist for Pass 2

After revision, verify:
- [ ] Required #1: All `confidential` references replaced with the real key set (`private`/`department`/`ship`/`fleet`); pattern-skip logic uses an explicit constant or `.get("private", 0)` with comment.
- [ ] Required #2: Disclosure direction matches records_store openness semantics (or hierarchy is inverted with explicit comment); tests #4–7 re-asserted.
- [ ] Required #3: Unspecified-source default is most-restrictive; Test #7 renamed.
- [ ] Required #4: `api_key_like` removed from `_DEFAULT_SENSITIVE_PATTERNS` (preferred) or tightened; Test #9 updated.
- [ ] Recommended #1–#5 addressed or explicitly waived with rationale.
- [ ] Verified-Against-Codebase footer states the real 4-tier keys verbatim.
