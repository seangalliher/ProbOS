# ProbOS Build Prompt Review Criteria

This file is read by the reviewer agent when auditing a build prompt before it goes to the builder. The reviewer should flag issues in three tiers: **Required** (must fix), **Recommended** (should fix), **Nit** (style/minor).

---

## 1. Boundary Enforcement

- **Who owns the constraint?** If a fix sanitizes, validates, or transforms data, does it happen at the boundary that owns the constraint (e.g., NATSBus owns NATS subject rules, not callers)?
- **Future callers protected?** Would a new caller passing unsanitized input silently break, or does the boundary enforce safety automatically?
- **Caller audit:** For every changed function, list all callers. Verify the change is safe for each. State the count explicitly ("4 callers: ...").

## 2. Silent Failure Audit

- **Exception swallowing:** Grep for `except Exception` blocks near the change. Are failures logged AND propagated appropriately? Check the Fail Fast three-tier model:
  - Swallow: non-critical, no user impact (rare, must justify)
  - Log-and-degrade: visible degradation acceptable
  - Propagate: security, data integrity, safety
- **Layered swallowing:** Check if multiple `try/except` layers compound to silently hide failures (BF-229 lesson: two layers of silent swallow).
- **Recovery guidance:** ERROR-level logs should include actionable recovery steps, not just "failed."

## 3. Namespace & State Consistency

- **NATS state layers:** If touching NATS subjects/prefixes, verify all three layers are addressed: (1) core subscriptions, (2) JetStream stream subject filters, (3) JetStream durable consumer filter_subjects. (BF-221/222/223 lesson.)
- **Depth preservation:** Subject/namespace changes must preserve token depth. Dots split NATS tokens. Underscores don't.
- **Reverse mapping:** Verify no code reverse-parses the changed value back to its original form. Grep for reverse patterns.

## 4. Scope & Completeness

- **"What This Does NOT Change" section:** Does the prompt explicitly list what is NOT being modified? Are there adjacent systems that a reader might assume are affected? List them.
- **Existing test impact:** Grep for the changed values/patterns in `tests/`. List every test that will need assertion updates. Missing this causes false failures in CI.
- **Operational cleanup:** If the fix leaves stale server-side state (streams, consumers, caches), document the one-time cleanup steps.

## 5. Engineering Principles Compliance

- **SOLID:** Single responsibility (is the fix scoped to one concern?), Open/closed (extending not patching?), Dependency inversion (injected abstractions not concretions?).
- **Law of Demeter:** No reaching through objects (`a.b._c`).
- **DRY:** Does the fix duplicate logic that exists elsewhere? Should it extract a shared helper?
- **Cloud-Ready:** New DB access through abstract interface, not direct `aiosqlite.connect()`.

## 6. Code Accuracy (Build Prompt Verification Standing Order)

- **Import paths exist:** Every import referenced in the prompt must exist in the codebase.
- **Function signatures match:** Parameter names, types, return types must match the live code, not memory.
- **Line numbers are approximate:** State "around line N" not "line N" for anything that may shift.
- **Interface patterns match reality:** e.g., is it `_emit_event_fn(callable)` or `event_bus.emit()`? Check.
- **Enum vs string constants:** Verify casing and type of constants referenced.
- **Constructor patterns:** Does the class accept the dependencies the prompt injects?

## 7. Test Coverage

- **Every fix path has a test:** Each distinct code change should have at least one test verifying it.
- **Boundary tests:** Happy path + error/edge case + empty/None where applicable.
- **Regression tests:** Existing tests that touch the changed area should be listed. Any needed assertion updates called out.
- **Mock consistency:** If using MockNATSBus or similar, verify the mock receives the same fix as the real class.

## 8. Design Choices

- **Alternatives considered?** For non-obvious design choices (e.g., underscore vs dot replacement), is the rationale documented in the prompt?
- **Consistency with prior art:** Does the fix pattern match how similar issues were resolved before? Check DECISIONS.md for precedent.
- **Rollback path:** If the fix causes problems, can it be reverted cleanly? Any migration or state change that complicates rollback?

## 9. Prompt Structure

- **Sections are implementable:** Each `###` section should be self-contained enough that the builder can implement it independently.
- **Current vs new code blocks:** For modifications, show the current code (what the builder will search for) and the new code (what replaces it). Current code must match the live file.
- **Verification section:** The prompt should end with specific test commands the builder should run.
- **Tracking section:** List which files to update (PROGRESS.md, roadmap.md, DECISIONS.md) and what to write.

---

## Output Format

Structure findings as:

### Required (must fix before building)
1. [Finding with specific file:line references]

### Recommended (should fix)
1. [Finding with rationale]

### Nits (style/minor)
1. [Finding]

### Verified (looks good)
- [List of areas that passed review]
