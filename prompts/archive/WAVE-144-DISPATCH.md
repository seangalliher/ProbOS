# Wave 144 — Dispatch (Builder-facing)

**Date:** 2026-05-10
**Theme:** Avatar self-image cluster — sensorium dispatch unification (eliminates the dual-wire tax)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**ADs in this wave:** AD-723 (#581)
**Mode:** Single-prompt wave, single commit
**Architect approval:** clean (3 review passes — see §6)

---

## 1. Context

Waves 140-143 shipped the avatar telemetry read side and the first write-back loop:

- **Wave 140 (AD-722 v1):** read-only avatar telemetry endpoint + `_build_avatar_self_observation` sensorium method. Captain BF immediately followed: avatar wired only into chain baseline; DM had no avatar awareness. Fix-up commit dual-wired the avatar block into the DM branch.
- **Wave 141 (AD-722-1, AD-722f):** modulation manifest + adaptive sampling state machine.
- **Wave 142 (AD-722b):** WebSocket push channel.
- **Wave 143 (AD-722a):** intent-vs-presentation divergence detector + asymmetric trust/Hebbian wiring. Added `_build_intent_self_tag_instruction` — and ALSO had to hand-wire it into BOTH baseline AND DM, deliberately deferring registration of the new method in `SENSORIUM_REGISTRY` to AD-723.

That's the dual-wire tax: every sensorium AD pays it twice or dies on whichever path the implementer forgot. The `SENSORIUM_REGISTRY` `ClassVar[dict]` at `cognitive_agent.py:122` is **inventory** — documented but never iterated. AD-723 makes the registry the *dispatcher*: each entry declares a `paths` tuple, and `_build_cognitive_baseline` / `_build_situation_awareness` / `_build_user_message` (DM and WR branches) each call `await self._dispatch_sensorium(path, observation)` exactly once.

**Constraint — keep the System-1 / System-2 split.** AD-723 unifies the wiring registry, NOT the paths. DM stays one-shot. Chain stays multi-LLM. WR stays peer-audience-shaped. Per Captain ruling 2026-05-10, the split is intentional and permanent.

**Acceptance gate:** golden-text snapshot tests assert that the rendered prompt for one chain, one DM, and one WR observation is byte-identical pre- vs post-refactor. The dispatcher is correct iff the diff is zero.

---

## 2. Build order (one prompt = one commit)

Single build group, single commit:

| # | Prompt | Commit message |
|---|---|---|
| 1 | [`prompts/ad-723-sensorium-dispatch.md`](ad-723-sensorium-dispatch.md) | `AD-723: sensorium dispatch unification — registry becomes dispatcher (zero behavioural change)` |

---

## 3. Pre-flight checklist (before starting Wave 144)

```pwsh
# 1. Working tree must be clean (or only untracked runtime artifacts).
git status --short
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5
# If any tracked file shows >200 deletions, STOP. Surface to architect.
# DO NOT git stash. DO NOT git reset --hard.

# 2. Establish baselines.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
# Record: pre-Wave-144 Python test count (Wave 143 closed at ~13160 — record actual).

# AD-723 is Python-only — no UI delta expected. Skip vitest baseline unless
# the Builder's diff touches ui/.
```

If the baseline pytest gate is red (tests failing pre-Wave-144), STOP. Surface to architect. Do not begin Wave 144 on a red baseline.

---

## 4. Per-commit workflow

### Commit 1: AD-723

1. Read [`prompts/ad-723-sensorium-dispatch.md`](ad-723-sensorium-dispatch.md) end-to-end before editing — this is a large refactor; reading the §5 extraction tables in advance prevents partial application.
2. **Capture pre-refactor snapshot fixtures FIRST.** Build a one-shot script that constructs a `CognitiveAgent` with a deterministic fake runtime and the canned observations specified in §8.1, runs the EXISTING `_build_cognitive_baseline` / `_build_user_message` methods, and writes verbatim output to `tests/fixtures/sensorium_snapshots/{chain_baseline,dm_oneshot,wr_oneshot}.txt`. Commit these fixtures alongside the refactor — they ARE the safety net.
3. Apply deliverables in dependency order:
   - **D1** — new types: `SensoriumPath`, `SensoriumEntry` (§4).
   - **D2** — registry literal replacement (§5.1 + §5.3). Use the §5.1 table as the source of truth.
   - **D3** — extracted methods per §5.2 (one method per inline block; signature `(self, observation: dict) -> str | None`).
   - **D4** — wrappers for incompatible signatures (`_sensorium_temporal_context`, etc.) per §6.2.
   - **D5** — `_dispatch_sensorium_sync` + `_dispatch_sensorium_async` dispatchers per §6.1. Chain paths use sync (all registered chain methods are sync at HEAD); DM/WR paths use async (registered methods include `_build_dm_self_monitoring` and the extracted introspective-telemetry method, both async).
   - **D6** — call-site shims: `_build_cognitive_state`, `_build_cognitive_baseline`, `_build_cognitive_extensions`, `_build_situation_awareness` STAY SYNC and delegate to `_dispatch_sensorium_sync` (§7.1-7.3). **No `await` additions in `perceive()`.** This preserves ~17 existing test call sites across `tests/test_ad646_cognitive_baseline.py`, `tests/test_ad646b_chain_parity.py`, `tests/test_ad635f_clinical_proactive_context.py`, `tests/test_ad648_post_capability_profiles.py` without modification.
   - **D7** — DM branch of `_build_user_message` refactored per §7.4 (inline blocks stay inline; sensorium dispatched).
   - **D8** — WR branch of `_build_user_message` refactored per §7.5.
   - **D9** — tests per §8 (snapshot + path-coherence + dispatcher unit + AD-646 regression).
4. Pay special attention to:
   - **D2 / D3 — method-name correctness.** Every key in `SENSORIUM_REGISTRY` MUST resolve to a real method on `CognitiveAgent`. Test §8.2 `test_all_registered_methods_exist` is the guard.
   - **D5 — `inspect.iscoroutinefunction(bound_method)` is the correct primitive.** NOT `iscoroutine` (that's for an already-called awaitable). The sync dispatcher raises `RuntimeError` if it encounters an async method on a chain path — defense-in-depth guard against future regressions. The async dispatcher handles both sync and async methods uniformly.
   - **D6 — chain shims stay SYNC.** The legacy test call sites depend on this. The sync dispatcher's `RuntimeError` guard ensures that if a future AD registers an async method on a chain path without architect review, the failure is loud, not silent. DM/WR branches at §7.4 / §7.5 use `_dispatch_sensorium_async`.
   - **D7 / D8 — block-order preservation.** The key tuple in the §7.4 / §7.5 examples MATCHES the existing inline order. Builder MUST NOT reorder. Snapshot diff is the gate.
   - **D7 — what STAYS inline in DM.** Boot-camp ship state (AD-683, cold-start preamble), session history (`params["session_history"]`), and the terminal `Captain says:` footer. These are not pure sensorium — they're DM-shape-specific.
   - **D8 — what STAYS inline in WR.** Channel/thread header preamble, augmentation skill task framing (AD-626/631), conversation context body, author footer, mention guidance. These are audience-shaped, not sensorium.
   - **D8 — WR omissions (per AD-722 addendum h).** Avatar block, intent self-tag, DM self-monitoring (only fires inside WR via `dm-*` channels — keep the `paths=(WR_ONESHOT,)` registration; the registered method's body retains the `dm-*` channel guard), boot-camp snippet, session history, captain footer. Test §8.2 `test_avatar_not_in_wr_paths` and `test_intent_self_tag_not_in_wr_paths` are the regression guards.
   - **AD-646 None-removal semantics.** `_sensorium_ext_no_memories_flag_override` returns `None` to remove the baseline-set flag when memories are present. The dispatcher's `if result is None: merged.pop(entry.output_key, None)` is the load-bearing line. Test §8.5 `test_extensions_no_memories_removal` regression-guards this.
   - **`_track_sensorium_budget` is preserved as-is.** Its two-dict signature is fed by two `_dispatch_sensorium` calls in `perceive()` (baseline+extensions merged into one dict, situation into the other). AD-666 observability is unchanged.

5. **Run the snapshot tests FIRST after refactor.** They are the byte-equality gate. If a snapshot fails, the refactor is incorrect — diff the actual vs expected and find the missing/reordered/duplicated block. Do NOT update the snapshot to match the new output; that defeats the purpose.

6. Per-commit gate:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad723_sensorium_dispatch.py -v -n 0
# Then the full parallel gate:
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected test delta: **+22 Python**. No Vitest delta.

---

## 5. Hard-stop conditions

Stop and surface to architect if:

1. **Snapshot byte-equality fails on first refactor pass AND the diff is not obviously a missing `await` or block-reorder bug.** Could indicate a deeper semantic drift in the extraction — needs architect review before "fixing" by updating the snapshot.
2. **A registered method's signature doesn't fit `(self, observation: dict) -> str | dict | None`** and no obvious wrapper makes it fit. Surface the method and the architect will revise §6.2.
3. **An existing test in `tests/test_ad722*.py` or `tests/test_ad646*.py` regresses** post-refactor. These are the closest neighbors to AD-723's surface and the most likely to surface a real semantic break.
4. **Working tree shows tracked-file deletions > 200 lines that you didn't author.** Per standing rule. Surface; do NOT `git reset --hard`.
5. **The async / sync detection logic doesn't work for a specific registered method.** The dispatcher uses `inspect.iscoroutinefunction(bound_method)`. If a method is decorated in a way that confuses introspection, surface — architect will revise.

Per cluster-plan standing rules, environmental xdist worker-crash failures that don't reproduce serially are NOT hard stops — quarantine per BF procedure if needed.

---

## 6. Architect review trail (informational — Builder skip)

Three review passes against the AD-723 prompt:

- **Pass 1:** registry shape + dispatcher semantics. Decisions D-1 through D-12 ratified. Phantom-API check: every method named in §5.1 / §5.2 verified to exist at HEAD via grep (see §2 of the prompt). The cluster-plan's mention of "AD-722a divergence-note registration" reviewed: confirmed embedded in `_build_avatar_self_observation` (no separate entry needed). The user-supplied design hint suggested separately registering `_build_intent_self_tag_instruction` — accepted (D-10).
- **Pass 2:** call-site refactor + sync/async split. Original draft made chain shims async; verify-first review caught ~17 existing test call sites that call them synchronously (`tests/test_ad646_cognitive_baseline.py`, `tests/test_ad646b_chain_parity.py`, `tests/test_ad635f_clinical_proactive_context.py`, `tests/test_ad648_post_capability_profiles.py`). Verified at HEAD: zero async methods are registered for any chain path. Resolution: split the dispatcher into `_dispatch_sensorium_sync` (for chain paths, raises on async) + `_dispatch_sensorium_async` (for DM/WR). Chain shims stay sync; no `await` additions in `perceive()`. AD-646 None-for-removal preserved via single-dict dispatch loop in `_build_cognitive_state`. `_track_sensorium_budget` integration: no signature change.
- **Pass 3:** verify-first pass against HEAD. All grep hits in §2 of the prompt confirmed. Block-order tuples in §7.4 / §7.5 cross-checked against the inline order at lines 5063-5300 (DM) and 5301-5466 (WR). Snapshot-first workflow (capture pre-refactor → commit fixtures → refactor → assert byte equality) confirmed as the load-bearing safety net. Three passes converged on the prompt as drafted.

No outstanding architect concerns.

---

## 7. Issues closed

- [#581](https://github.com/seangalliher/ProbOS/issues/581) — AD-723 sensorium dispatch unification.

No forward markers filed in this wave. Wave 145 (AD-721d-1 — DSL draft preview / revision cycle) is the next planned wave per the cluster plan.

---

## 8. Post-commit handoff

After Wave 144 ships:

- **PROGRESS.md** status line updated to record Wave 144, test count delta, AD-723 closed.
- **progress-era-5-unification.md** appended entry summarizing AD-723's dual-wire tax removal.
- **docs/development/roadmap.md** AD-723 / #581 marked SHIPPED.
- **DECISIONS.md** AD-723 entry (lines 1731-1742) appended with `**Shipped:** 2026-05-NN — Wave 144.` line.
- Notify architect: ready for Wave 145 dispatch drafting (AD-721d-1 DSL draft preview).

---

## 9. AD-numbering check

- Pre-Wave-144 highest AD in `DECISIONS.md`: **AD-729** (Wave 142 forward marker).
- AD-723 is an existing entry, not a new allocation. No collision risk.
- Next architect-drafted AD will be at AD-730 or higher.
