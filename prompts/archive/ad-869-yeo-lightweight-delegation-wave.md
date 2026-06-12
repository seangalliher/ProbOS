# Wave: Yeo Lightweight-by-Default Delegation (AD-869 · AD-870 · AD-846 · AD-847)

**Status:** Draft for Architect review (verify-first). Builder executes one AD = one commit with a gate between each.
**Goal (Captain):** Make Yeo act *lightweight by default* — answer a quick read in the same turn it replies — and escalate to a tracked task or a specialist only when the work won't fit in one reversible step. Then close the async loop (completion DM + desktop notification) so the full delegation experience is testable end-to-end with Yeo.
**Research basis:** graduated-autonomy doctrine — navy command-by-negation + Mission Command; Anthropic workflows-vs-agents + three-layer/subsumption robotics; Vroom–Yetton / Situational Leadership / transaction-cost economics. Full research artifact lives in the private commercial repo; the OSS code ships WITHOUT naming any of that framing (boundary rule).

**Tracking issues (close via commit `closes #NNN`):** AD-869 → [#839](https://github.com/seangalliher/ProbOS/issues/839) · AD-870 → [#840](https://github.com/seangalliher/ProbOS/issues/840) · AD-846 → [#841](https://github.com/seangalliher/ProbOS/issues/841) · AD-847 → [#842](https://github.com/seangalliher/ProbOS/issues/842).

---

## AD numbering — hard rule honored

- **Current highest committed AD = AD-868** (PROGRESS.md, Wave 215). State this in any review response.
- **New ADs in this wave: AD-869, AD-870** (assigned sequentially from 868).
- **AD-846 and AD-847 are PRE-RESERVED** by the AD-845 epic (see `prompts/ad-845-yeo-async-task-workflow.md` + the AD-845 DECISIONS.md entry, which forward-marks both as "gated follow-ups, NOT built here"). They were reserved before the codebase reached 868. This wave **builds them under their reserved numbers** — do NOT renumber them, and do NOT reuse 869/870 for them.
- AD-840–844 remain reserved for the Desktop Console epic — untouched here.

## The 4-tier model (target state)

| Tier | Name | Mechanism | Status before this wave |
|---|---|---|---|
| 1 | Answer | Plain conversational reply | ✅ exists |
| 2 | **Do-and-report** | Synchronous mesh **read** resolved inline (~5s, reads-only) | ❌ **the gap → AD-869** |
| 3 | Write-it-down | `[CREATE_TASK]` → dispatchable WorkItem → kanban | ✅ AD-845 |
| 4 | Get-help | Assign to a specialist via `specialist=@callsign` | ◐ partial (AD-845) |

**Threshold rule taught to Yeo (AD-870):** *"If I can get the answer in the time it takes to reply, and it doesn't change anything — I just do it. Otherwise I write it down."* Two axes: latency (does it finish this turn?) and reversibility/cost (does it change anything?).

---

## What ALREADY EXISTS (verified against HEAD — do not rebuild)

| Capability | Where (verified) |
|---|---|
| Synchronous targeted read primitive | `IntentBus.send(intent) -> IntentResult \| None` [mesh/intent.py:407](../src/probos/mesh/intent.py) — awaits a single handler up to `intent.ttl_seconds`, returns one `IntentResult` (NOT `broadcast`, which fans out to all subscribers — avoid the N-agent anti-pattern). |
| Non-consensus read intents | `read_file`/`stat_file` (filesystem), `list_directory` (directory), `search_files` (search), `web_search` (WebSearchAgent, BF-599), `read_page` (PageReaderAgent, BF-599). **`http_fetch` is consensus-gated — NOT in the allowlist.** |
| Reply-tag parse/strip precedent | `DmSanityGate` [dm_sanity_gate.py](../src/probos/cognitive/dm_sanity_gate.py): `_MOVE_RE`/`_CREATE_TASK_RE` + `extract_create_task`/`strip_create_task`. |
| Ordered reply pipeline | `DmReplyPipeline` [cognitive/dm/reply_pipeline.py:101-103](../src/probos/cognitive/dm/reply_pipeline.py): `step_4f_extract_artifacts` → `step_4g_create_task_parse` (AD-845) → `step_5_episodic_store`. Each step runs under a top-level try/except (Tier-2). |
| Yeo conversational hooks | `_conversational_capability_block` [yeoman.py:262](../src/probos/cognitive/yeoman.py) (BF-599) + `_conversational_task_protocol` [yeoman.py:319](../src/probos/cognitive/yeoman.py) (AD-845), appended in the `is_conversation` branch of `_decide_via_llm`. `DELEGATION_MAP` + `resolve_delegate` [yeoman.py:505](../src/probos/cognitive/yeoman.py). |
| Capability → agent resolution | `callsign_registry.resolve` + `resolve_delegate` (used by `_resolve_specialist_agent_id` [reply_pipeline.py:880](../src/probos/cognitive/dm/reply_pipeline.py)); capability lookup via `capability_registry.query`. |
| Completion event | `WORK_ITEM_STATUS_CHANGED` [events.py](../src/probos/events.py) on every status change (no `WORK_ITEM_DONE` event — do not assume one). |
| Captain-DM pattern | AD-485 [proactive.py:3861-3886](../src/probos/proactive.py): find/create `dm-captain-{agent.id[:8]}` channel → `ward_room.create_thread(...)`. |
| Desktop notification primitive | `notify(args, activator)` [desktop/src/main/notifications.ts:22](../desktop/src/main/notifications.ts); `ipcMain` wired in [desktop/src/main/index.ts](../desktop/src/main/index.ts). |

---

## AD-869 — Tier-2 synchronous mesh-read seam (the do-and-report default)

**Problem.** Yeo's conversational path can answer (Tier 1) or open an async task (Tier 3, AD-845) but has **no way to perform a quick reversible read and answer in the same turn**. The Captain has to wait for a kanban round-trip to learn what's in a directory. This is the missing default.

**Approach (reply-tag + inline `IntentBus.send`, sibling of AD-845):**

1. **Sanity-gate parse/strip.** Add `_MESH_READ_RE` + `extract_mesh_read(text) -> tuple[str, dict[str,str]] | None` + `strip_mesh_read(text) -> str` to `DmSanityGate`, mirroring `_CREATE_TASK_RE`/`extract_create_task`/`strip_create_task`. Tag shape: `[MESH <intent> key=value key=value]` (e.g. `[MESH list_directory path=/etc]`, `[MESH web_search query=Nvidia SPARK RTX]`). Length-ceiling each field (runaway-backtracking guard); lax strip removes well-formed AND malformed variants so nothing leaks to Captain-visible text.
2. **Allowlist constant.** A module-level frozenset of permitted **read** intents: `{"list_directory","read_file","stat_file","search_files","web_search","read_page"}`. Any intent NOT in the allowlist → strip the tag, log a warning, ship the reply unchanged (do NOT execute). This is the safety boundary — `http_fetch` and all writes are excluded by construction. Document WHY in a comment: destructive intents require consensus, consensus cannot resolve in a single synchronous turn, so the inline path is structurally read-only.
3. **New pipeline step `step_4e_mesh_read_parse`**, registered BEFORE `step_4f_extract_artifacts` (so a read result is part of the reply body that artifacts/episodic see). On a parsed allowlisted tag:
   - Resolve ONE capable agent for the intent (capability/pool lookup via `capability_registry` or the registry pool for that intent; reuse the resolution style of `_resolve_specialist_agent_id`). No capable agent → strip tag, append a brief honest note (`"(couldn't reach a <intent> handler)"`), ship reply.
   - `result = await intent_bus.send(IntentMessage(target_agent_id=<resolved>, intent=<intent>, params=<parsed params>, ttl_seconds=5))`. Use `IntentBus.send` (single targeted handler), NOT `broadcast`.
   - On `result.success`: replace the tag span with a compact rendering of `result` (truncate large payloads — reuse an existing truncation helper if present; cap at a sane line/char ceiling). On failure/timeout/None: strip tag, append a brief honest note, ship reply.
   - Hard ~5s ceiling via `ttl_seconds=5` (the latency ceiling that enforces the safety ceiling). Hold no fire-and-forget task — this is a direct `await`.
   - Tier-2 honest-degrade throughout: missing sanity gate, missing intent_bus, no resolved agent, send raise → strip tag, ship reply, NEVER raise.

**Acceptance criteria.**
- `tests/test_ad869_mesh_read_inline.py` (≥7, **real** `AgentRegistry` + a real or concrete-stub read agent registered on the bus — NO MagicMock at the substrate boundary per the Phantom-via-MagicMock rule; only the LLM may be a `_Fake*`): (a) allowlisted `[MESH list_directory path=...]` → `IntentBus.send` called once, result rendered inline, tag stripped; (b) non-allowlist intent (e.g. `http_fetch`, `write_file`) → NOT executed, tag stripped, reply otherwise unchanged; (c) no-tag reply → no `send`, text byte-unchanged; (d) `intent_bus=None` → honest-degrade, reply intact, no exception; (e) no capable agent resolved → honest note, no send; (f) `send` returns failure/None → honest note, tag stripped; (g) timeout (handler exceeds ttl) → honest-degrade, no raise.
- `extract_mesh_read`/`strip_mesh_read` unit-tested for well-formed + malformed + multi-param parsing.
- Tag text and all rendered notes must NOT contain decomposer `_CAPABILITY_GAP_RE` tokens (gap-regex-safe, BF-599 lesson) — assert in a test.
- No new `httpx`/`requests` import in Yeo or the pipeline (mesh-delegated only, Principle #10) — assert via source-scan.
- Verify compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Do NOT build:** any write/mutate intent in the inline path; `http_fetch` inline; a decomposer intent; changes to `IntentBus`/`WorkItemRouter`; AD-870's instructions (separate AD); kanban/UI changes; multi-intent batching in one tag (single read per tag).

---

## AD-870 — Yeo delegation-threshold instructions (teach the 4-tier judgment)

**Problem.** Once AD-869 lands, Yeo has three execution seams (`[MESH]` read, `[CREATE_TASK]` task, `specialist=@`) but no guidance on *which* to use. Per Design Principle #6, the choice must be LLM judgment driven by instructions, NOT a hardcoded keyword table in `decide()`.

**Approach (instructions-first, extend the existing Yeo hook):**
- Extend `YeomanAgent._conversational_task_protocol` (already appended in the `is_conversation` branch — the BF-599/AD-845 seam) to teach the threshold rule and the tier choice in plain language:
  - **Quick reversible lookup you can finish now** (list a dir, read a file, search files, a single web search / page read) → emit a single `[MESH <intent> ...]` and answer inline.
  - **Real work that takes time or produces an artifact / report** → `[CREATE_TASK ...]` (existing AD-845 protocol), confirm you've opened it and will report back.
  - **Work clearly owned by a department specialist** → `[CREATE_TASK ... specialist=@callsign]`, preferring a trusted specialist (DELEGATION_MAP departments).
  - **A plain question** → just answer.
  - The governing line, in Yeo's voice: *"If I can get the answer in the time it takes to reply and it doesn't change anything, I do it. Otherwise I write it down."*
- Keep it honest-degrade: when `runtime` / `intent_bus` / `work_item_store` is absent, the corresponding tier guidance is omitted (don't teach a seam that isn't wired). Reuse the existing live-registry gating style from `_conversational_capability_block`.
- The instruction text must contain NONE of the decomposer `_CAPABILITY_GAP_RE` tokens (asserted).

**Acceptance criteria.**
- `tests/test_ad870_yeo_delegation_threshold.py` (≥5, real `AgentRegistry`): (a) protocol text includes the `[MESH]`, `[CREATE_TASK]`, and `specialist=@` guidance when all seams are wired; (b) `[MESH]` guidance omitted when `intent_bus` is None; (c) `[CREATE_TASK]` guidance omitted when `work_item_store` is None; (d) gap-regex-safe; (e) base-class `_conversational_task_protocol` (non-Yeo agent) still returns `""` (Open/Closed — other agents byte-unaffected).
- `tests/test_yeoman_agent.py` + `test_cognitive_agent*.py` + `test_bf599*` + `test_ad845*` stay green.
- Verify Engineering-Principles compliance.

**Do NOT build:** a hardcoded tier-decision table or any logic in `decide()`/`act()`/`perceive()`; trust-weighted specialist selection (forward marker AD-871); changes to the AD-869 parser.

---

## AD-846 — Task completion → proactive Yeo DM to the Captain (reserved; build now)

*(Scope unchanged from `prompts/ad-845-yeo-async-task-workflow.md`. Reaffirmed here so the wave builds to completion.)*

**Approach.** Subscribe a listener (wired in `runtime.py` startup, alongside existing event wiring) to `WORK_ITEM_STATUS_CHANGED`. Filter: new status `WorkItemStatus.DONE` (and `FAILED`, distinct message) AND `metadata.get("dispatchable")` AND `tags` contains `"yeo-delegated"` (so ONLY Yeo-originated tasks notify — no spam for system work items). On match, Yeo delivers the DM via the AD-485 pattern (find/create `dm-captain-{yeo.id[:8]}` → `ward_room.create_thread(...)`) with the task title + a short result summary (from the work item's result/`metadata`/last step). Lands in both the 1:1 Yeo chat and the Ward Room DM inbox (same channel). Hold the task reference (no fire-and-forget). Honest-degrade if `ward_room` is None.

**Acceptance criteria.** `tests/test_ad846_completion_dm.py` (≥4): DONE → DM created in dm-captain channel; FAILED → distinct message; non-`yeo-delegated` item → no DM; `ward_room=None` → log-and-degrade, no crash. Verify Engineering-Principles compliance.

**Do NOT build:** desktop notification (AD-847); kanban refresh; AD-869/870 code.

---

## AD-847 — Desktop OS notification on completion, click opens Yeo chat (reserved; build now)

*(Scope unchanged from `prompts/ad-845-yeo-async-task-workflow.md`. Reaffirmed here.)*

**Approach (renderer → preload IPC → main `notify`).** On the AD-846 completion DM event reaching the renderer, call a new preload-exposed bridge `window.probos.notifyTaskDone({ title, body, route })`. Add the `ipcMain.handle`/`ipcMain.on` counterpart in `desktop/src/main/index.ts` that calls `notify({title, body}, { showAndRoute })` with `route` = the Yeo 1:1 chat deep-link (reuse the existing `showAndRoute` activator). Expose `notifyTaskDone` through the existing `preload` contextBridge (follow the `probos:*` IPC channel naming).

**Acceptance criteria.** Desktop/unit test (follow existing desktop test pattern): preload bridge invokes the IPC channel; main handler calls `notify` with the routed activator. Verify Engineering-Principles compliance.

**Do NOT build:** new WebSocket in main (reuse renderer stream + IPC); AD-846 server code; kanban changes.

---

## Suggested sequence & gates (Builder)

1. **AD-869** (mesh-read seam) → focused tests green → full gate → commit → **stop, review**.
2. **AD-870** (threshold instructions) → focused tests green → full gate → commit → **stop, review**.
3. **AD-846** (completion DM) → focused tests green → full gate → commit → **stop, review**.
4. **AD-847** (desktop/UI) → `cd ui && npx vitest run` + desktop build → commit.

After all four: a single push. Each AD updates PROGRESS.md + DECISIONS.md in its own commit (one AD = one commit). Update the BF-599 / AD-845 forward markers (D2 auto-delegation now fully realized as Tier 2 + Tier 3).

**Test invocation (CWD hazard):** `Set-Location -LiteralPath d:\ProbOS` then
`d:/ProbOS/.venv/Scripts/pytest.exe d:/ProbOS/tests/test_ad869_mesh_read_inline.py --rootdir d:/ProbOS -q -n 0 -p no:cacheprovider`.
Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto` (serial `-n 0` triggers environmental runtime-boot timeouts; trust the "passed" count and re-triage xdist worker crashes individually).

## Verify-first reminders for the Architect

- Re-grep every file/line reference above against HEAD before the final approval pass (subagent/spec reports are leads, not ground truth — the AD-858..862 epic returned a NO-GO on every AD for missing connective tissue).
- Confirm `IntentBus.send` returns a single `IntentResult` and that the read agents (FileReaderAgent, DirectoryListAgent, FileSearchAgent, WebSearchAgent, PageReaderAgent) subscribe to the exact intent names in the allowlist.
- Confirm the reply-pipeline step registration order and that a new `step_4e_*` slots cleanly before `step_4f_extract_artifacts`.
- Confirm `capability_registry`/pool resolution from within the pipeline `ctx.runtime`.

## Forward markers (do NOT build now)
- **AD-871:** trust-weighted specialist selection for Tier 4 (Situational-Leadership grounding — high-trust → delegate, probationary → supervise).
- **AD-872:** let Yeo signal which "rung of the ladder" it's on (Intent-Based Leadership "I intend to…").
- **AD-873:** kanban auto-refresh on `WORK_ITEM_STATUS_CHANGED`.
