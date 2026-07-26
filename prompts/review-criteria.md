# ProbOS Build Prompt Review Criteria

This file is read by the reviewer agent when auditing a build prompt before it goes to the builder. The reviewer should flag issues in three tiers: **Required** (must fix), **Recommended** (should fix), **Nit** (style/minor).

---

## 1. Boundary Enforcement

- **Who owns the constraint?** If a fix sanitizes, validates, or transforms data, does it happen at the boundary that owns the constraint (e.g., NATSBus owns NATS subject rules, not callers)?
- **Future callers protected?** Would a new caller passing unsanitized input silently break, or does the boundary enforce safety automatically?
- **Caller audit:** For every changed function, list all callers. Verify the change is safe for each. State the count explicitly ("4 callers: ...").
- **Hostile type boundary:** If input crosses HTTP/WebSocket/NATS/plugin boundaries, does validation require the exact trusted enum/contract and canonical value? Flag permissive `isinstance` checks where `str`/`StrEnum` subclasses or lookalike objects can spoof the wire type.

## 1a. Ownership and Exactly-Once Effects

- **Durable authority:** Name the single store/service that owns each state transition. Flag split-brain writes across route, service, and store layers.
- **Lifecycle owner:** Name the sole owner of start, task references, retry, restart recovery, drain, and stop. Flag duplicate startup wiring or unowned background tasks.
- **Event owner:** A mutation must emit from one source only. If the store/service emits, routes/adapters must not mirror the same event. Require a count assertion proving exactly once.
- **Replay safety:** Delivery, trust application, metrics, terminal notification, and artifact publication need durable idempotency before externally visible effects.
- **Projection parity:** Initial bounded snapshots, live reducers, reconnect/resync, and stale-response rejection must converge on the same visible state.

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
- **Clean-checkout portability:** Reject tests tied to an operator-local or skip-worktree config hash, local cache/model availability, generated UI bundle, machine uptime, or nondeterministic timestamp ordering. Non-mutation tests snapshot before and compare after.
- **Evidence freshness:** If source/tests/prompts changed after a reported gate, require the narrow affected gate again; require the consolidated gate again for shared behavior or collection changes.
- **Gate economy:** During coding, require focused changed-slice and adjacent regression checks. Require Architect review before the single broad wave-close gate; do not demand a full repository run after every prompt in a batch.

## 8. Design Choices

- **Alternatives considered?** For non-obvious design choices (e.g., underscore vs dot replacement), is the rationale documented in the prompt?
- **Consistency with prior art:** Does the fix pattern match how similar issues were resolved before? Check DECISIONS.md for precedent.
- **Rollback path:** If the fix causes problems, can it be reverted cleanly? Any migration or state change that complicates rollback?

## 9. Prompt Structure

- **Sections are implementable:** Each `###` section should be self-contained enough that the builder can implement it independently.
- **Current vs new code blocks:** For modifications, show the current code (what the builder will search for) and the new code (what replaces it). Current code must match the live file.
- **Verification section:** The prompt should end with specific test commands the builder should run.
- **Tracking section:** List which files to update (PROGRESS.md, roadmap.md, DECISIONS.md) and what to write.
- **Freeze point:** Multi-AD waves record approved prompt hashes and freeze prompt/source/test inputs before the consolidated gate.
- **Worktree safety:** Prompts name shared dirty files and require explicit-path or partial-hunk staging plus cached-diff inspection; `git add -A` is never prescribed.

## 10. Startup Phase Ordering (BF-259/260/261/262 lesson)

Four bugs in one audit shared the same root cause: features wired in finalize (Phase 8) but consumed by earlier startup phases, with `getattr(runtime, "x", None)` silently returning `None`.

- **Phase ordering audit:** If the prompt creates a new service/object in `finalize.py`, grep for every `getattr(runtime, "<attr>", None)` reference to that attribute. If any reference occurs in a phase that runs BEFORE finalize (Phase 8), flag it — the attribute won't exist yet. Known phase order: Phase 2 (communication) → Phase 3 (agent fleet) → Phase 5 (cognitive services) → Phase 7 (boot camp) → Phase 8 (finalize).
- **Result dataclass unpacking:** If the prompt adds a field to a Result dataclass in `startup/results.py` (e.g., `DreamingResult`, `CommunicationResult`, `CognitiveServicesResult`), verify the corresponding unpacking line exists in `runtime.py`. A field in the Result with no matching `self.x = result.x` in runtime is a guaranteed silent failure for any finalize consumer.
- **Late-bind target verification:** If the prompt late-binds an object into another (e.g., `_ds._manifest = ...`), verify the target object is the one that actually reads the attribute. Grep the target class for `self._manifest` (or whatever attribute). If zero references, the binding is on the wrong object.
- **Guard clause log levels:** If a feature is config-enabled (`enabled=True` default) but fails to wire due to a guard clause, the guard should log at WARNING, not DEBUG. Silent failure of an enabled feature is a diagnostic trap. DEBUG is appropriate only for features that are config-disabled.

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
