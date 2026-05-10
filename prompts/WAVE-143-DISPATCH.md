# Wave 143 — Dispatch (Builder-facing)

**Date:** 2026-05-10
**Theme:** Avatar self-image cluster — intent-vs-presentation divergence detector (closes read→write loop)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**ADs in this wave:** AD-722a (#567)
**Mode:** Single-prompt wave, single commit
**Architect approval:** clean (3 review passes documented in §6 below)

---

## 1. Context

Wave 140 shipped AD-722 v1 (read-only avatar telemetry). Wave 141 shipped AD-722-1 (modulation manifest) + AD-722f (per-agent adaptive sampling). Wave 142 shipped AD-722b (WebSocket push channel). The READ side is now complete and the surface is "proprioception" rather than "inventory" per Counselor's framing.

AD-727 (Captain ruling 2026-05-10) partitioned the coherence-check landscape into three distinct ADs:

- **Self-coherence: AD-722e** — deterministic projection of digital state to structured English (forward marker; not yet shipped).
- **Intent-vs-presentation: AD-722a** — does the agent's stated emotional intent match the modulation that was actually projected? ← **THIS WAVE**.
- **Digital-vs-analog: AD-728** — does the vision-LLM observation of the rendered avatar match the digital state? (forward marker; hard-gated on AD-721i renderer).

Wave 143 ships the SECOND of those three. AD-727 rule #1 ("aesthetic READ-ONLY on trust; reasoning-vs-output FAIR on trust") explicitly authorizes trust wiring for AD-722a's category by construction — the detector ingests no pixels, invokes no vision LLM, and compares only the LLM's `<intent emotion=…>` self-tag against the deterministic modulation rule output.

**The cluster-plan phantom that must be corrected:** the cluster plan at `prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md:152` cites `runtime.trust_network.observe(agent_id, delta=...)`. No such method exists. The real API is `record_outcome(agent_id, success, weight, intent_type, episode_id, verifier_id, source) -> float`. The Wave 143 prompt corrects this throughout.

---

## 2. Build order (one prompt = one commit)

Single build group, single commit:

| # | Prompt | Commit message |
|---|---|---|
| 1 | [`prompts/ad-722a-divergence-detector.md`](ad-722a-divergence-detector.md) | `AD-722a: intent-vs-presentation divergence detector + asymmetric trust/Hebbian wiring (default OFF)` |

---

## 3. Pre-flight checklist (before starting Wave 143)

```pwsh
# 1. Working tree must be clean (or only untracked runtime artifacts).
git status --short
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5
# If any tracked file shows >200 deletions, STOP. Surface to architect.
# DO NOT git stash. DO NOT git reset --hard.

# 2. Establish baselines.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
# Record: pre-Wave-143 Python test count (= Wave 142 baseline = 13140).

cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
# Record: pre-Wave-143 Vitest count (= Wave 142 baseline = 561).
# AD-722a has ZERO UI surface in v1; Vitest count delta is expected to be 0.

cd ui; npm run build 2>&1 | Select-Object -Last 10; cd ..
# Must be clean. Sanity check only — AD-722a is Python-only.

# 3. Confirm no pending tracked changes from prior session.
git diff --stat
# Should print no output. If anything shows, surface to architect.
```

If the baseline pytest gate is red (tests failing pre-Wave-143), STOP. Surface to architect. Do not begin Wave 143 on a red baseline.

---

## 4. Per-commit workflow

### Commit 1: AD-722a

1. Read [`prompts/ad-722a-divergence-detector.md`](ad-722a-divergence-detector.md) end-to-end before editing.
2. Apply deliverables in dependency order: **D1** (new `divergence_detector.py` module — pure Python, no I/O) → **D2** (config extension on `AvatarTelemetryConfig` — 4 new fields + validator) → **D3** (runtime `divergence_results: dict` initialization adjacent to AD-722b's `avatar_event_bus`) → **D4** (system-prompt instruction injection — new `_build_intent_self_tag_instruction` method + two call-site additions in chain and DM paths) → **D5** (extend `_build_avatar_self_observation` with divergence-note block + add `_build_divergence_note` helper) → **D6** (chat-handler detector call BETWEEN `response_text` post-process and `mark_reply_emitted`) → **D7** (no-op — Hebbian rel_type registration is a string namespace; documented, no code) → **D8** (Python tests).
3. Pay special attention to:
   - **D1** — the `INTENT_EXPECTED_RULES` table values MUST be valid subsets of the `apply_voice_modulation` fired-rule names (`"responding_rate"`, `"blocked_rate_pitch"`, `"high_trust_pitch"`, `"low_trust_pitch"`, `"tier3_rate_volume"`). Any typo here silently breaks the divergence math — there is no schema validator.
   - **D2** — **TWO thresholds**, not one. `divergence_negative_threshold: float = 0.3` (output diverged AWAY) and `divergence_positive_threshold: float = 0.5` (output exceeded SAME direction — higher bar). Both with corresponding asymmetric weights. The `field_validator` lists ALL FOUR fields.
   - **D3** — `runtime.divergence_results: dict[str, "DivergenceResult"] = {}` uses a STRING annotation to avoid an import cycle. Do NOT add a top-level `from probos.avatars.divergence_detector import DivergenceResult` to `runtime.py`. If a `TYPE_CHECKING` block exists at the top of `runtime.py`, you may add the typed import there; otherwise the string annotation alone is sufficient (Python does not evaluate string annotations at runtime).
   - **D4** — TWO call-site additions for the instruction injection: ONE in `_build_cognitive_baseline` (chain path, line 4537 region) and ONE in the DM inline-assemble (line 5155 region). The new method `_build_intent_self_tag_instruction` is **NOT** a sensorium method — it is NOT added to `SENSORIUM_REGISTRY`. Adding it would change the registry shape; AD-722a deliberately preserves the registry intact.
   - **D5** — `_build_avatar_self_observation` is **synchronous**. Reads `runtime.divergence_results[agent_id]` directly. The new `_build_divergence_note` helper is tier-2 wrapped — returns empty string on any failure. The phrasing rule (OUTPUT-as-subject, never agent-as-subject) is regex-tested in D8 test #24.
   - **D6** — the divergence-detector call sits BETWEEN response post-processing (line 763 region) and the existing `mark_reply_emitted` block (line 908). Exactly one new call site — the AD-722 single-call-site invariant is preserved. The strip MUST be **unconditional when feature ON**, even on parse failure, so the tag NEVER leaks to the Captain. Trust update is gated by the **asymmetric** thresholds: `magnitude > divergence_negative_threshold` for the `signed_divergence < 0` branch; `magnitude > divergence_positive_threshold` for the `signed_divergence > 0` branch.
   - **D8** — tests #15-#21 form the chat-handler integration sub-suite. Use REAL `TrustNetwork(data_dir=tmp_path)` and REAL `HebbianRouter()` (not MagicMocks); the test-as-spec depends on observing directional weight changes. Trust assertions use `pytest.approx` with absolute tolerance ≥ 0.001 — do not assert exact arithmetic against the dampened trust math.
4. After all deliverables are applied, run focused gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722_avatar_telemetry.py tests/test_ad722f_adaptive_sampling.py tests/test_ad722b_websocket_push.py tests/test_ad722a_divergence_detector.py -v -n 0
   ```
   Expect: every existing AD-722 / AD-722f / AD-722b case still passes; ≥ 18 new AD-722a cases pass.
5. Run the TS side as a sanity check:
   ```pwsh
   cd ui; npx vitest run; cd ..
   ```
   Expect: byte-identical to baseline (no UI changes in this wave).
6. **Run `cd ui && npm run build` BEFORE pushing** (HARD RULE — sanity only here; AD-722a touches zero TSX).
7. Run the full parallel gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
   ```
   Expect: Python test count = baseline (13140) + ≥ 18.
8. `git diff --cached --stat` — sanity-check the commit's deletion footprint. The only intended deletions are the SEARCH blocks in D2 (config field block, ~6 lines), D3 (runtime init block, ~10 lines), D4 (two call-site SEARCH blocks, ~8 lines each), D5 (return-block ~8 lines), D6 (single SEARCH block ~3 lines). Anything that deletes more than ~30 lines in a file is a red flag.
9. Commit: `git commit -m "AD-722a: intent-vs-presentation divergence detector + asymmetric trust/Hebbian wiring (default OFF)"`.

---

## 5. Test gates

| Gate | Command | When |
|---|---|---|
| Full parallel | `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile` | Pre-flight, after commit, post-wave |
| Focused per-prompt | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722*.py -v -n 0` | After commit, before pushing the parallel gate |
| Vitest | `cd ui && npx vitest run` | Pre-flight, after commit (no delta expected) |
| TypeScript build | `cd ui && npm run build` | Pre-flight, after commit (sanity only) |

**`-n auto` is forbidden** until AD-682 lands. Use `-n 8` (verified ceiling on this codebase).

**Per-commit gate failure interpretation:**
- Failures under the parallel gate that do NOT reproduce under `-n 0` are environmental — document and continue.
- Real failures that reproduce serially in files you changed are blockers. Stop, triage.
- The chat-handler integration tests (`test_ad722a_divergence_detector.py` §D rows 15-21) construct an `_endpoint_runtime`-style fixture with REAL `TrustNetwork` and `HebbianRouter`. If those tests pass serially but flake under parallel, run isolated (`-n 0`) to triage.

---

## 6. Architect review status

Three review passes were run against `prompts/review-criteria.md` and `.github/copilot-instructions.md`. Findings:

**Pass 1 (verify-first):**
- ✅ Every API reference, import path, function signature, and line number in the prompt grep-confirmed against HEAD (2026-05-10).
- ✅ License check: zero new Python or JS deps. Apache 2.0 boundary preserved.
- ✅ Phantom API correction: the cluster plan's `runtime.trust_network.observe(agent_id, delta=...)` is a phantom (no such method on `TrustNetwork` at consensus/trust.py:112). The real method is `record_outcome(agent_id, success, weight, intent_type="", episode_id="", verifier_id="", source="verification") -> float` (consensus/trust.py:217). Every call site in the prompt uses the real signature with `source="avatar_divergence"` and `intent_type="avatar_divergence"` (a new namespace that doesn't collide with existing `record_outcome` callers).
- ✅ `HebbianRouter.record_interaction(source, target, success, rel_type=REL_INTENT)` (routing.py:177) signature verified. The new `rel_type="avatar_intent"` is a string namespace; no edit to `routing.py` required because the parameter accepts arbitrary strings. The `_is_utility_pair` check at routing.py:215 is a no-op for namespaced target strings (the target `"avatar:emotion:warm"` is never registered as an agent_id, so the tier-registry lookup returns no entry and the guard returns False).
- ✅ `runtime.trust_network` and `runtime.hebbian_router` are public attributes (runtime.py:389, :352).
- ✅ `runtime.avatar_event_bus` is the Wave-142 anchor for `divergence_results`'s init location (runtime.py:428). Phase ordering correct: init in `__init__`, not finalize.
- ✅ `mark_reply_emitted` is exactly one call site (`routers/agents.py:909`); the AD-722a detector call sits immediately before it in the SAME block — single-call-site invariant preserved.
- ✅ `_last_self_avatar_snap` is a real CognitiveAgent attribute (cognitive_agent.py:192), populated by `observe_self_avatar()` (cognitive_agent.py:2656).
- ✅ `_build_avatar_self_observation` is a synchronous method (cognitive_agent.py:2659) — divergence-note injection stays synchronous.
- ✅ `apply_voice_modulation` fired-rule names match the `INTENT_EXPECTED_RULES` table values (telemetry.py:313-343).
- ✅ Pydantic v2 `@field_validator` pattern matches `AvatarTelemetryConfig` precedent at config.py:996-1018.
- ✅ AD ceiling: AD-729 (verified via DECISIONS.md). AD-722a is the AD itself; forward markers AD-722a-1 through AD-722a-6 use AD-722a's namespace and do NOT collide with the top-level ceiling.
- ✅ AD-727 rule #1 inheritance: the detector observes REASONING-vs-OUTPUT divergence by construction — it never ingests pixels, never invokes a vision LLM, never compares image to model. AD-727 explicitly authorizes trust wiring for this category (DECISIONS.md:1780).
- ✅ WR not wired (per AD-722 addendum (h) — DECISIONS.md:1699). DM-only scope; chain reply-emission is forward marker AD-722a-2.
- ✅ Pre-commit deletion sanity check (200 lines): largest single SEARCH block is the `_build_avatar_self_observation` return-text block (~8 lines). All replacements well below threshold.

**Pass 2 (revisions):**
- Caught: the original draft used a single `divergence_trust_threshold` for both positive and negative branches. The user-prompt explicitly specifies asymmetric thresholds (negative=0.3, positive=0.5 — positive requires higher magnitude because the trust update is informational, not punitive). Replaced with **two** thresholds + two weights. The `field_validator` now lists all four numeric fields. Test row #19b added to cover the new "between negative and positive thresholds" gap.
- Caught: the cluster-plan phantom-API line (`trust_network.observe`) appeared in three places (§1 TL;DR, §9 hard-stop reminder, §10 wave-specific reminder). Cross-referenced and consistent throughout the prompt.
- Caught: the `runtime.divergence_results: dict[str, "DivergenceResult"] = {}` annotation uses a string forward-reference to avoid a module-load cycle between `runtime.py` and `avatars/divergence_detector.py`. Documented explicitly so Builder doesn't add a top-level import.
- Caught: the divergence-note text contains the word "Your" (possessive, in "Your last reply was intended as `warm`"). The defensive phrasing-rule regex `\byou\b` uses word boundaries and will NOT match "Your" (which is "y-o-u-r" with no word boundary between `u` and `r`). Verified explicitly in the test description to prevent Builder confusion.
- Caught: the strip MUST be unconditional when feature ON, even on `parse_intent_self_tag` returning None (unknown emotion / malformed tag). Otherwise a malformed tag would leak to the Captain. Hard-stop rule #6 enforces this.
- Caught: the new method `_build_intent_self_tag_instruction` is NOT a sensorium method — it emits a SYSTEM-PROMPT INSTRUCTION, not a percept. Adding it to `SENSORIUM_REGISTRY` would change registry shape; AD-722a deliberately preserves the registry intact. The two call-site additions in D4 (chain at line 4537 region; DM at line 5155 region) append the instruction directly into the prompt-assembly path, mirroring how `_build_avatar_self_observation` is invoked at those same sites.

**Pass 3 (confirmation):**
- ✅ All Pass-2 revisions verified against the codebase one more time (grep re-run on every changed reference; `record_outcome` parameter list confirmed verbatim; `_build_avatar_self_observation` return-block SEARCH text matches HEAD).
- ✅ Engineering Principles compliance line present in the prompt (§12 row 10).
- ✅ "Non-goals" table explicit; six forward markers (AD-722a-1 through -6) tagged with one-line descriptions; tracking section §11 names them and Captain-files them post-build.
- ✅ No emoji in either prompt or in proposed code.
- ✅ Three-tier exception model honored — every new guard either swallows-with-justification (divergence-note rendering inside `_build_divergence_note`), logs-and-degrades (the entire chat-handler detector wrap in D6, the `_build_intent_self_tag_instruction` exception path), or propagates (config validator rejections for out-of-range thresholds/weights).
- ✅ AD-numbering: highest AD at HEAD = **AD-729**. AD-722a's tracking issue #567 already exists; no new top-level AD numbers minted. Forward markers AD-722a-1 through -6 are sub-numbers under AD-722a's namespace, not new top-level ADs (no ceiling collision risk).
- ✅ Phantom-API check: every method asserted on `runtime.trust_network`, `runtime.hebbian_router`, and CognitiveAgent is either confirmed at HEAD or being introduced by this AD. The four "introduced by this AD" symbols (`_build_intent_self_tag_instruction`, `_build_divergence_note`, `runtime.divergence_results`, the four new `AvatarTelemetryConfig` fields) are flagged in §2 with the "DOES NOT EXIST AT HEAD (greenfield)" annotation.
- ✅ Path-coherence: WR (ward_room) NOT wired. Chain reply-emission NOT wired (forward marker AD-722a-2). DM-only scope is consistent with the AD-722 single-call-site invariant.
- ✅ Phrasing rule (AD-727 #8 translated to OUTPUT): rendered divergence-note text uses "Your last reply was …" and "the modulation came out as …" — OUTPUT-as-subject by construction. Defensive regex test #24 enforces the boundary across all 8 emotion taxonomy entries × representative applied-rule tuples.
- ✅ AD-727 rule #1 inheritance check: the trust delta in this AD is for reasoning-vs-output divergence (fair). The detector observes no image, invokes no vision LLM, compares no pixels. The prompt does NOT introduce image-based or aesthetic-based trust updates (those are forbidden per AD-727 rule #1 — AD-722e/AD-728's territory).
- Pass 3 found nothing new. Prompt is READY FOR BUILDER.

---

## 7. Hard-stop conditions

Surface to architect immediately if any of the following occur:

1. **Tracked-file modifications you didn't make** in `git status` before or during the wave. Do NOT `git stash`. Do NOT `git reset --hard`. (See PROGRESS.md / user memory note about the 2026-05-08 working-tree wipe — this is the canonical trap.)
2. **Phantom API surface** — a method/attribute/import the prompt asserts exists but doesn't (and isn't being added by this AD). **Especially watch:** the cluster plan's `runtime.trust_network.observe(...)` is a phantom — the prompt corrects this to `record_outcome(...)`. Re-grep, then surface.
3. **Architectural change required** — the prompt cannot be built without modifying a base contract (BaseAgent / IntentMessage / `AvatarTelemetrySnapshot` in ways the prompt doesn't sanction). AD-722a is a CONSUMER of the existing telemetry surface — the snapshot dataclass MUST stay unchanged.
4. **Single call-site invariant broken** — if the chat handler's reply-emission path gains a second `mark_reply_emitted` site, the call moves into a private helper named `_finalize_chat_reply` (mirrors AD-722 D6 approach). VERIFY WITH ARCHITECT BEFORE REFACTORING — this is the kind of change that wants design review.
5. **Trust update fires on aesthetic/image judgment.** AD-727 rule #1 is non-negotiable. The detector's trust delta is bounded to the `(intent_emotion, fired_rules)` tuple by construction; if any deliverable ingests pixels, invokes a vision LLM, or compares image to model, hard stop.
6. **Tag leaks to Captain.** The strip MUST be unconditional when `divergence_detection=True`. Reviewer fails any code path that returns `<intent emotion=…>` text in the response payload when the feature is ON.
7. **Existing AD-722 / AD-722f / AD-722b tests fail.** The detector is additive — `_build_avatar_self_observation` gains a conditional appended block, but its return text when `runtime.divergence_results[agent_id]` is unset MUST be byte-identical to HEAD. If existing tests break, the cause is likely the divergence-note append running unconditionally (it must only append when the dict has an entry for `self.id`).
8. **Vitest existing 561 cases break.** AD-722a has zero UI surface; Vitest count must be byte-identical to baseline. Any delta is a bug.

---

## 8. Standing rules (carry forward from `.github/copilot-instructions.md`)

- **AD-numbering hard rule:** if any unforeseen need for a new AD/BF arises during the wave, read DECISIONS.md (current highest is **AD-729**), state the highest explicitly in your response, then assign sequentially. Never guess. The six forward markers in this wave (AD-722a-1 through -6) use AD-722a's namespace and do NOT collide with the top-level AD ceiling.
- **Forward markers must have GH issues:** AD-722a's primary tracker is **#567** (already filed; close on commit). The six forward markers are filed by Captain post-build (Builder lacks GH token scope for `seangalliher/ProbOS`). Builder lists the forward-marker text in the build report; Captain runs `gh issue create` after.
- **Pre-commit `git diff --cached --stat` deletion sanity check** — flagged in user memory. Anything that wipes >200 lines you didn't author is a stop-the-line. Largest intended SEARCH/REPLACE in this wave is the `_build_avatar_self_observation` return-text block (~8 lines).
- **Three-tier exception handling** — every new guard in the prompt is explicitly tagged: log-and-degrade (chat-handler detector wrap; divergence-note rendering; instruction-injection method), propagate (config validators for asymmetric threshold/weight bounds).
- **Cloud-ready storage** — AD-722a adds zero database access. `runtime.divergence_results` is in-memory by design — restart resets to empty.
- **HARD RULE — `cd ui && npm run build` AFTER UI code changes BEFORE pushing.** AD-722a has no UI changes; this gate is a sanity check only.

---

## 9. Post-wave checklist

After the commit lands and gates are green:

```pwsh
git log --oneline -3                 # Confirm AD-722a commit present.
git diff HEAD~1 --stat               # Wave-level diff sanity.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
cd ui; npm run build 2>&1 | Select-Object -Last 5; cd ..
```

Update `PROGRESS.md`, `docs/development/roadmap.md`, and `DECISIONS.md` per the prompt's tracking table (§11). Close GH issue **#567** with a "shipped in Wave 143 (AD-722a)" comment, citing the commit SHA. Captain files the six forward markers (AD-722a-1 / -2 / -3 / -4 / -5 / -6) as new GH issues after Builder lists the marker text in the build report.

If anything is unclear or any pre-flight gate fails, STOP and surface to architect before proceeding.
