# Wave 49 Dispatch — AD-647c v1

**Single AD continuous-build wave.** AD-647c v1 = Process Chains ↔ Bills + Watch Bill integration. NATS pipeline coupling (AD-641g #403) is **separately tracked** and out of scope for this wave. CONSULT step kind is shipped as a semantic label only (executor already awaits async handlers natively); suspend-and-resume across process restart deferred to placeholder AD-647d (no GH issue v1).

**Issues to close:** #405

**Spec:** [`prompts/ad-647c-bills-integration-v1.md`](./ad-647c-bills-integration-v1.md)

---

## Highest-risk constraints (read before building)

1. **`bill_step_id` (NOT `bill_id`).** User spec called the field `bill_id`, but `bill_id` is overloaded across the Bills surface (`BillDefinition.bill` is the bill slug; `BillInstance.bill_id` is the slug too). The chain step's field maps to `BillStep.id` — the **step id within a bill**. The prompt names it `bill_step_id` for disambiguation. Do **not** rename to `bill_id` during the build.

2. **Three-guard defense for bill recording.** Bill side-effects fire only when **all three** are true: `step.bill_step_id != ""` AND `context.get("bill_instance_id")` AND `self._bill_runtime is not None`. Tests #4 + #5 enforce this. Do not collapse the guards.

3. **Bill recording is tier-2 log-and-degrade.** Every call to `bill_runtime.complete_step / fail_step / get_instance` MUST be wrapped in `try/except Exception → logger.warning`. Bill-side errors must never propagate up into chain execution. Test #7 verifies (`bill_runtime.complete_step.side_effect = RuntimeError`).

4. **Backward compat — AD-647 v1 + AD-647b v1 tests must pass UNCHANGED.** Do not edit `tests/test_ad647_process_chains.py` or `tests/test_ad647b_chain_registry.py`. The new ctor kwarg `bill_runtime=None` and the new step fields `bill_step_id=""` / `assigned_role=""` all default to no-op; old call sites stay green.

5. **CONSULT step kind = enum value only, NO executor change.** The current executor already runs `step_output = await step.handler(running)` (`process_chains.py:131`), which natively supports `async def __call__` handlers that internally await any async resource. CONSULT semantically signals human/cross-agent consultation; behaviorally identical to TRANSFORM in v1. Do **not** add a separate executor branch for CONSULT.

6. **`runtime.bill_runtime` property** is a 1-line public alias added immediately after `runtime.billet_registry` (line 985). Do **not** remove `runtime._bill_runtime` — the adoption site at `runtime.py:1553` writes to the private name and the new public property reads it.

7. **`register_bill_chain` is fail-fast.** Mismatched `bill_step_id` raises `ValueError` and the chain is **not** registered (Test #11 asserts `registry.get_chain("bad") is None`). Empty `bill_step_id` strings skip validation (Test #12).

---

## Phantom-API pre-check

Run after draft is in place:

```powershell
scripts/phantom-api-precheck.ps1 prompts/ad-647c-bills-integration-v1.md
```

**Expected 6 candidates ALL FPs (verified by architect at draft time):**

- `class:SimpleNamespace` — stdlib `types.SimpleNamespace` (test fixtures).
- 3× `ProcessChainRegistry.register_bill_chain` (method_phantom) — **introduced by this prompt** in Section 3; not yet in class index at draft time. AD-685b would correctly flag these post-build if not for the in-prompt definition.
- 2× `ProcessChainStep.bill_step_id` / `ProcessChainStep.assigned_role` (field_phantom, AD-685d category) — **introduced by this prompt** in Section 1b; the dataclass fields don't exist yet at draft time. Test fixtures in Section 5 reference them. Post-build the field index will pick them up.

**0 NEW phantoms.** Same intra-prompt-introduction FP class as Waves 27-48 — fields/methods that Section N introduces, exercised by Section M tests at draft time.

---

## Test gate

Baseline (Wave 48 final): **11146**. Target: **11158** (+12).

Run sequence per Builder Execution Plan:

```powershell
# Focused per-prompt
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad647c_bills_integration.py -v -n 0

# Verify back-compat (AD-647 + AD-647b unchanged)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad647_process_chains.py tests/test_ad647b_chain_registry.py -v -n 0

# Full parallel gate
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

`-n auto` is forbidden until AD-682 lands. If parallel gate hits xdist worker crash, fall back to `-n 0` per Builder Execution Plan.

---

## Hard-stop conditions

1. AD-647 or AD-647b regression test fails after the build (back-compat invariant violated).
2. `BillRuntime.complete_step` / `fail_step` signature drift discovered at HEAD that wasn't caught by verify-first.
3. Property-collision on `runtime.bill_runtime` (e.g., a private `bill_runtime` attribute already exists somewhere unaccounted for).
4. Pre-existing test pollution surfaces under `-n 0` that wasn't in the baseline — quarantine with BF entry per execution plan.

For 1-3, hard stop and surface to architect. For 4, quarantine with BF and resume.

---

## Tracker updates (per spec)

- **PROGRESS.md**: prepend AD-647c v1 entry to top of file; bump baseline 11146 → 11158.
- **docs/development/roadmap.md**: status flip on the AD-647c row under the AD-647 family (Scoped → Complete).
- **DECISIONS.md**: prepend `### AD-647c — Process Chains Bills/Watch Bill Integration` block under Era V using the `## Era V — Civilization (Phases 31-36)\n\n### AD-647b` two-line anchor (Wave 41 prepend lesson).

---

## Single commit

```
git add -A
git commit -m "Wave 49: AD-647c v1 Process chains Bills/Watch Bill integration (#405)"
git push
```

GH issue close (`gh issue close 405`) BLOCKED by EMU 403 in continuous-build environment — Captain closes manually, same as Waves 31-48.
