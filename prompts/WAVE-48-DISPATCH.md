# Wave 48 Dispatch — AD-647b v1 Process Chain Registry + BF-209 Removal

**Issue:** #404
**Prompt:** [`prompts/ad-647b-chain-registry-v1.md`](./ad-647b-chain-registry-v1.md)
**Builder mode:** continuous (single AD; no inter-section pause)
**Test gate:** `pytest tests/ -q -n 8 --dist=loadfile` — target `11146 passed` (`11134` baseline + 12 new).

---

## Highest-risk constraints

1. **Handler refactor is mechanical, not semantic.** The four
   `_scout_step_*` methods move from bound instance methods to
   module-level functions. Each `self.X` becomes `agent.X` where
   `agent = ctx["_agent"]`. Body content is unchanged — same parsing
   logic, same filter call, same Discord delivery. Do NOT rewrite the
   handler bodies; just rebind the receiver.

2. **`_deliver_discord` STAYS a bound instance method.** It reads
   `self._runtime`, `self.config` (via runtime), `self.id` at call
   time. Module-level `_scout_step_notify_and_deliver` calls
   `await agent._deliver_discord(filtered, date_str)` — the bound-method
   call remains valid because `agent` is the ScoutAgent instance.

3. **Section 3 has TWO removals that must both land.** (a) Replace
   `class ScoutAgent` declaration with the "module-level handlers ABOVE
   class" block (search anchor: the class docstring). (b) DELETE the
   four old `_scout_step_*` instance methods at `scout.py:449/475/489/506`.
   The prompt's Section 3 includes a "_REMOVED" rename marker on the
   first instance method as a safety bumper — Builder must follow up
   with a deletion block that removes all four method bodies. Leaving
   any `_scout_step_*_REMOVED` placeholder in production source is a
   review blocker.

4. **`_should_activate_chain` modification preserves Gate 1 + Gate 2
   behavior.** The new Gate 0 is purely additive. The two `intent =
   observation.get("intent", "")` assignments after the patch are
   redundant (one inside Gate 0, one inside Gate 2) — leave both. No
   refactor.

5. **`process_chain_id` collision check.** `grep -rn "process_chain_id"
   src/probos/` should return zero hits before this AD. After: only the
   `CognitiveAgent` class attribute and the `ScoutAgent` override.

6. **`runtime.process_chain_registry` collision check.**
   `grep -rn "process_chain_registry" src/probos/` should return zero
   hits before this AD. After: only the wirer + Scout's `act()` lookup.

7. **Wirer ordering.** `_wire_process_chain_registry` runs BEFORE
   `_wire_consultation_workspaces`. Scout doesn't depend on the
   registry being wired during finalize (Scout agents are spawned
   later), but tests that import `SCOUT_REPORT_CHAIN` rely on the
   constant being defined at module-import time — the wirer just
   composes the registry, it does not define the chain.

8. **Test #10 is structural, not behavioral.** It asserts
   `ScoutAgent._should_activate_chain is CognitiveAgent._should_activate_chain`.
   This is the BF-209 closure verification. If the override is left in
   place by mistake, this test fails with a clean object-identity
   mismatch.

9. **Phantom-API pre-check expectation.** Self-test on this prompt
   (run at draft time): 2 candidates, both FPs, 0 NEW phantoms.
   - `ScoutAgent.__new__` — stdlib object protocol used in Section 6
     test scaffolding (same FP class as Wave 34 build).
   - `class:SimpleNamespace` — stdlib FP (Waves 27–47 precedent).
   - Standard skips: `runtime.process_chain_registry.get_chain` and
     `runtime.process_chain_registry.list_chains`
     (`no_class_resolution` — public attribute introduced by this
     prompt, not yet in class index).

   None of these block the build.

10. **The `else` fallback in `act()` is intentional.** When
    `runtime.process_chain_registry.get_chain("scout_report")` returns
    `None` (e.g. wirer disabled via config), `act()` falls back to the
    module-level `SCOUT_REPORT_CHAIN` constant. This is defense in
    depth — Captain explicitly defaulted the config to `enabled=True`,
    but the fallback prevents a config flip from breaking Scout.

---

## Verified at HEAD `893f29b` (Wave 47 commit)

```text
src/probos/cognitive/process_chains.py:108  ProcessChainExecutor
src/probos/cognitive/scout.py:206          class ScoutAgent(CognitiveAgent)
src/probos/cognitive/scout.py:253-268      BF-209 _should_activate_chain override
src/probos/cognitive/scout.py:407-434      inline ProcessChainDefinition (target of removal)
src/probos/cognitive/scout.py:449/475/489/506  _scout_step_* bound methods (target of removal)
src/probos/cognitive/cognitive_agent.py:1685  _should_activate_chain (target of patch)
src/probos/tools/registry.py:113           ToolRegistry.register replace+WARN precedent
src/probos/config.py:1904                  ConsultationWorkspaceConfig (anchor for new config)
src/probos/config.py:2260                  consultation_workspaces: ConsultationWorkspaceConfig (anchor)
src/probos/startup/finalize.py:515         _wire_consultation_workspaces (anchor for wirer)
src/probos/startup/finalize.py:853         cascade slot for new wirer call
tests/test_ad647_process_chains.py:146     test_scout_act_runs_through_process_chain (Section 6 amendment target)
```

---

## Go signal

Builder may proceed when all 10 constraints above are reviewed. No
parallel sections. Apply Sections 1 → 2 → 3 → 4 → 5 → 6 in order. After
Section 3, run `pytest tests/test_ad647_process_chains.py -v -n 0` to
confirm the existing 8 tests still pass before moving to Section 4.

After all sections land, run the focused gate first, then the full gate:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad647b_chain_registry.py tests/test_ad647_process_chains.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

Expected: `12 passed` and `8 passed` for the focused gate, then
`11146 passed, 15 skipped` for the full gate. Closes #404.
