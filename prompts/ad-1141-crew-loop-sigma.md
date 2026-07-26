# AD-1141 — Crew loop wired to Σ: consult before, publish after (cognitive / crew)

**Issue: #1062 · Epic #1057 (Σ) · depends on AD-1139 (#1060) and AD-1140 (#1061), both in-tree at HEAD `9e8b8264`.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1141** (#1062). AD ceiling: AD-1151 shipped. BF ceiling: BF-679. Next free: AD-1152 / BF-680. No new AD, no new BF.**

This is the keystone of the epic. AD-1138 made records discoverable, AD-1139 gave agents a read verb, AD-1140 gave them a write verb — and **nothing calls any of it**. Crew children at HEAD are pure isolates: `task_text = active_child.description or active_child.title or ""` (`crew_executor.py:890`), run under `asyncio.Semaphore(self._max_parallel)` (`:482`), with the finalizer as the sole convergence point. AD-1141 is what makes the crew actually use the commons.

Default-OFF. **Read the next section before anything else.**

---

## ⛔ CRITERION #1 — DO NOT DESTROY THE §8.3 CONTROL ARM

**Today's isolated-children behaviour IS the ablation's baseline, and the live Σ-off baseline has NOT been captured.** AD-1143 shipped the harness with a structural capture only. If AD-1141 changes crew behaviour when the flags are off, the control arm is gone, the ablation can never be run, and the epic loses its only empirical claim. There is no recovery — you cannot re-derive a baseline from a modified runtime.

Therefore:

1. Every behaviour this AD adds is **strictly default-OFF**.
2. Setting the `tests/ablation/sigma_flags.py` `SIGMA_OFF` set produces **byte-identical** pre-AD-1141 crew behaviour. Not "equivalent" — **byte-identical, proven by test**: same `task_text` string, same `extra_context` dict, same `tool_ids` list, same persisted evidence, same plan-identity hash.
3. Any new **boolean** flag goes in **both** `sigma_flags.py` dicts. The existing guards (`set(SIGMA_ON) == set(SIGMA_OFF)`, and every dotted path resolving on a live `SystemConfig()` to a `bool`) must stay green.

**Default-OFF byte-identity is precisely what decouples this merge from the baseline capture.** Issue #1062 says the baseline must be captured before this merges; that is true only if byte-identity is not provable. Prove it and the merge is safe in either order. Do not treat criterion #1 as boilerplate — it is the load-bearing property of the whole AD.

---

## ⛔ CORRECTION TO ISSUE #1062 — `extra_context` DOES NOT REACH THE PROMPT

**Issue #1062's stated mechanism is wrong at HEAD and must not be built as written.** The issue says:

> Σ context therefore enters via the existing `extra_context={...}` seam (`crew_executor.py:898`), threaded into the loop context by `WorkItemAgenticExecutor`.

It is not threaded into the prompt. Traced end to end:

| Step | Code | Effect |
|---|---|---|
| 1 | `crew_executor.py:898-901` | `extra_context={"_crew_session_id": …, "_crew_work_item_id": …}` |
| 2 | `agentic_dispatch.py:676-686` | Validated against `_AGENTIC_EXTRA_CONTEXT_KEYS` (7 keys, `:59-69`) **plus a length check**; any unknown key ⇒ `ValueError("agentic_context_invalid")`. Becomes `_context`. |
| 3 | `agentic_dispatch.py:1013-1020` | `_context.update({agent_id, department, rank, thread_id})` |
| 4 | `agentic_dispatch.py:1021-1026` | `loop.run(system_prompt=instructions, user_message=task_text, tools=tools, context=_context)` |
| 5 | `agentic_loop.py:622-624` | `messages = [{"role":"system","content":system_prompt},{"role":"user","content":user_message}]` — **`context` is absent** |
| 6 | `agentic_loop.py:626` | `agent_id = str(context.get("agent_id", "<unknown>"))` — logging/events only |
| 7 | `agentic_loop.py:753`, `:820` | `context=context` handed to tool execution |

`context` is the **tool-invocation context**. It is what `Tool.invoke(context=…)` receives. It never enters `messages`. Σ payload placed there would be visible to tools and invisible to the LLM — the exact opposite of the intent. Widening `_AGENTIC_EXTRA_CONTEXT_KEYS` would not fix this; it would only make the payload legal to pass and still not delivered.

**The correct seam is `task_text`.** `task_text` is a plain local computed at `crew_executor.py:890` and consumed once at `:895`. It becomes `user_message`. It is **never persisted** — the persisted value is `active_child.description`, which this AD does not touch. So `task_text` satisfies the epic's actual constraint (*"runtime injection, never persisted spec/evidence/result state"*) while actually reaching the producer.

**This is the single most important thing to get right in this AD.** Build against `task_text`. Leave `extra_context` byte-identical.

---

## Three crew contracts that MUST NOT change

All three verified at HEAD. Each is load-bearing for AD-1127 recovery.

1. **`crew_execution` evidence is an EXACT 14-key set.** `crew_executor.py:622-639` reads `metadata.get("crew_execution")` and raises `ValueError("crew_execution_evidence_invalid")` when `set(execution) != {version, parent_id, work_item_id, thread_id, assigned_to, status, stopped_reason, output_summary, tool_trace_ref, artifact_refs, tokens_used, started_at, finished_at, blocked_dependency_ids}`. **One extra key breaks recovery on every restart.**
2. **`SubtaskResult`'s field set is frozen.** `crew_finalizer.py:1909-1915` does an exact 12-key check (`work_item_id, spec_id, agent_id, output, status, tool_trace_ref, started_at, finished_at, stopped_reason, actual_tokens, artifact_refs, blocked_dependency_ids`) then `SubtaskResult(**result_values)`. **Do not add a field.**
3. **`description` is INSIDE the plan-identity hash.** The plan projection includes `"description": description` (`crew_session.py:1009`), `plan_seed_hash = hashlib.sha256(projection_bytes).hexdigest()` (`:1174`), re-verified on recovery (`:1574`), and `task_text = active_child.description or active_child.title` (`crew_executor.py:890`). **Enriching the persisted description changes plan identity and breaks AD-1127 recovery for every in-flight session.**

Consequence: Σ context is a **runtime prompt injection into `task_text`**, never persisted spec/evidence/result state. Publications go to Ship's Records through AD-1140's tool, never into crew evidence.

---

## Pinned design decisions

### DD-1 — Injection point: `task_text`, composed in the executor, one place

Compose the child's user message at `crew_executor.py:890` from a pure function:

```
_compose_child_task_text(base_task_text, *, commons_block, expected_output, publish_nudge) -> str
```

Flag OFF ⇒ every optional argument is empty ⇒ the function returns `base_task_text` **unchanged, by identity**. Test that: `_compose_child_task_text(t) is t` (or `== t` with an explicit identity assertion), so the OFF path is provably a no-op rather than a re-render that happens to match.

Order: `base_task_text`, then the expected-output block, then the commons block, then the publish nudge. Rationale — the task comes first so a long commons block cannot push the actual instruction out of the model's attention; the nudge comes last because it is about what to do *after* the work.

Rejected: composing inside `WorkItemAgenticExecutor.run`. It serves the AD-839 conversational path too; injecting there would change non-crew behaviour and blow criterion #1.

### DD-2 — Consult: ONE query per child, executor-side, before execution

**Not per turn.** A per-turn consult would need `AgenticLoop` changes (out of scope, and it serves every caller) and its cost is unbounded in the loop's iteration count.

**Not the parent.** The parent's job is decomposition; planning runs through `crew_session` / synth, a different code path this AD does not touch. Wiring the planner is a separate decision with its own failure mode (a commons entry steering the *plan* is far higher-consequence than one steering a subtask).

**Children only, once each, before `self._executor.run(...)`.**

Query text: `f"{active_child.title}\n{active_child.description}"`, trimmed, bounded at `_MAX_CONSULT_QUERY_CHARS = 512` (matching `oracle_query_tool._MAX_QUERY_CHARS`). Surface: `OracleService.query(...)` (`oracle_service.py:467`) with `tiers=SIGMA_TIERS` imported from `probos.tools.oracle_query_tool` — **reuse the constant, do not re-type the tier list.** `SIGMA_TIERS` is a module constant on purpose ("a safety property of the tool, not a knob an operator should be able to widen", `oracle_query_tool.py:53-54`) and `episodic` must never appear.

Do **not** use `query_formatted` (`:620`): it renders `=== ORACLE QUERY RESULTS ===` with no framing and no score floor, and it is a Captain-era rendering. Render the block here, framed, per DD-4.

`oracle_query` (AD-1139) stays offered as a tool — the injected block is the *unrequested* first look; the tool remains the agent's way to look again.

### DD-3 — The gate: a score floor with a ZERO-COST empty path (LOAD-BEARING)

**This is the DD that decides whether AD-1141 is useful or is just tokens and latency.** Most crew subtasks are mechanical. A commons lookup on *"write the tests for the new module"* returns whatever is topically adjacent, not something that changes the output — and injected context that goes unused still consumes attention and can pull a child off-task.

Three gates, cheapest first:

| Gate | Rule | Cost when it fires |
|---|---|---|
| **Query floor** | Composed query text shorter than `_MIN_CONSULT_QUERY_CHARS = 24` after strip ⇒ skip the consult entirely | zero — no Oracle call |
| **Score floor** | Drop every result with `score < crew_sigma_min_score` (default `0.35`) | one local Oracle call, **zero prompt characters** |
| **Entry cap** | Keep at most `crew_sigma_max_entries` (default `4`), highest score first | bounded |

**When nothing clears the floor, inject NOTHING.** Not an empty-body note, not a header — **zero added characters**. This is the whole point: AD-1139's `_EMPTY_BODY` exists because an agent that *asked* deserves an answer, but a child that never asked must not be told the commons was silent. That would be pure overhead on the majority path.

Net effect: a pointless consult costs **one local Oracle call and zero context**. The injection only ever adds tokens when it found something that cleared a floor. That converts *"always adds tokens and latency"* into *"adds tokens only when it has a reason to."*

`0.35` is a starting value, not a derived one — say so in the config docstring. It is the first knob to tune if AD-1143's ON arm shows a null effect.

### DD-4 — Framing travels inline; nothing reaches a child unframed

The Captain's standing constraint: **no Σ content reaches an agent unframed.** The live finding was that Oracle content surfacing unframed felt alien — *"it just appeared."* `AgenticLoop` renders bare content and has no consumer-side wrapper (`agentic_loop.py:622-624`), so framing must be carried **inline**, in the parenthetical shape AD-1139 and AD-1140 both use (`oracle_query_tool.py:89`, `perception/working_memory.py:28`).

**Gap-regex constraint.** No authored string may match `_CAPABILITY_GAP_RE` (`decomposer.py:33-40`, `re.IGNORECASE`). The forbidden set, read off the live pattern:

`don't have` · `can't` · `cannot` · `unable to` · `no {capability|ability|support|way|mechanism|tool}` (also with `built-in ` / `native ` between) · `not {available|supported|possible}` · **`lack` / `lacks` / `lacking`** · `doesn't {have|support}` · `beyond {my|current} {capabilities|abilities}` · `outside {my|the} {scope|capabilities}`

**`lack` is a bare substring.** `black hole`, `slack`, `blackhole`, `lackluster` all trip it — AD-1140 hit this for real. **Assert every module-level string constant against the real imported regex**, not a re-typed copy.

Reference shapes below. **All eight were run against the live `_CAPABILITY_GAP_RE` at HEAD `9e8b8264` and are clean.** The Builder may improve the wording; the constraints are not negotiable. **If you reword any of them, re-run the check.**

- header — `"## What the ship already knows about this"`
- disposition — `"(These entries come from the ship's shared knowledge stores — work other crew recorded in earlier sessions. Treat them as reference material rather than as something you lived through. Each entry carries its source tier, a confidence score and an age, so weigh a low-confidence or STALE entry lightly. Build on an entry and cite it; otherwise do not narrate this consultation.)"`
- expected-output header — `"## What this subtask will be judged against"`
- expected-output disposition — `"(This is the acceptance criterion the verifier applies to your output. Meet it directly.)"`
- publish nudge — `"(If this subtask produces a durable finding that a different crew member would want in a later session, record it with the publish_finding tool before you finish. Publish a conclusion with its basis, not a status update.)"`
- budget note — `"(Some commons entries were held back to stay inside this subtask's context budget.)"`
- ship-budget refusal (DD-6) — `"(The ship has reached its publication budget for the current hour. Keep the finding in your output; record it in a later session if it still matters.)"`
- empty-consult note — **exists as a constant but is NEVER emitted in this AD** (DD-3). Keep it defined and assert it clean, so a later AD that wants it does not re-derive the wording.

Each entry carries its provenance marker in the AD-1139 shape — source tier, confidence, age — so a STALE or low-confidence entry is visibly weightable.

### DD-5 — Publish: the CHILD decides, through AD-1140's tool. The executor writes nothing.

Rejected alternatives, in order of how tempting they are:

- **Executor auto-publishes `outcome.final_text` after each child.** This is the noise failure mode in its purest form: every child output becomes a durable record. It also makes the publish path a new write surface owned by the executor, with its own failure isolation, its own budget, and its own duplicate story. **No.**
- **Finalizer publishes the accepted synthesis.** One record per session is a defensible volume, but it publishes the *parent's* synthesis, not the child's finding — and the room already holds it (`_append_crew_session_child_result`). It also touches the finalizer convergence path, which #1062 explicitly forbids. **No.**
- **A heuristic over `final_text`** ("does it look like a finding?"). A bad classifier, run on every child, whose false positives pollute the commons and whose false negatives are invisible. **No.**

**Decision: the child calls `publish_finding` itself.** AD-1140 already ships the verb; the offer block already exists (`agentic_dispatch.py:929-938`); it is already department + rank gated, already per-author rate-limited, already deduped. AD-1141's entire contribution to the write half is **the nudge string plus the ship-wide budget**.

Consequences, all good:
- **Zero new write path.** No new failure isolation to design — a tool failure inside the loop is already isolated by `DispatchToolExecutor`.
- **The criterion lives in the nudge**, in the agent's own language: *a durable finding another crew member would want later; a conclusion with its basis, not a status update.*
- **The child is the only party that knows** whether it learned something. The finalizer sees outputs, not process.

**Who decides is therefore: the child.** State it that way in the DECISIONS entry — it is a real design commitment, not a punt.

### DD-6 — Ship-wide publish budget (the AD-1140 review's open flag, closed here)

The Architect review of AD-1140 flagged that per-agent rate limiting (12/hr) **does not bound ship-wide write volume at all**, and that near-duplicate suppression scans only `max_scan_entries = 20` recent entries (`records_store.py:521`, `:641`) — so with N crew agents publishing, duplicates slip past around N≈2 sustained. **AD-1141 is where the ship-wide budget belongs, because AD-1141 is what creates N.**

**Design:** a second `deque[float]` on the same `PublishFindingTool` instance. The registry holds exactly one instance (same registration shape as AD-1139/AD-1140), so instance state *is* ship state.

| Bound | Value | Where |
|---|---|---|
| Ship-wide publishes/hour | `publish_finding_max_per_hour_ship = 40` | `AgenticToolsConfig`, `Field(default=40, ge=1, le=500)` |

**Checked BEFORE the per-author limiter.** Otherwise a single author consuming the ship budget would be told it hit its *personal* limit, which is false and would send it into exactly the retry loop the limiter exists to absorb.

Over-budget ⇒ framed `output=` with `metadata={"published": False, "reason": "ship_rate_limited"}`, **no write**, and **not** an `error=` — same reasoning as AD-1140's per-author refusal.

**Why 40:** `max_parallel_subtasks` defaults to 3 (`config.py:6277`), so at most 3 children publish concurrently. 40/hr is roughly three sessions of a twelve-child plan each publishing once — above realistic legitimate volume, below the point where a single hour's writes dominate the store.

**State the limit of this bound honestly, in the docstring and the DECISIONS entry.** 40/hr against a 72-hour staleness window is up to 2 880 entries inside the dedup window, far past Layer 3's 20-entry cap. **The ship budget bounds the RATE, not the WINDOW POPULATION.** It does not make Layer 3 sound. Do not claim dedup correctness this design does not deliver — that is the AD-1151 lesson (a shipped AD justified on a guarantee that did not hold, and the correction cost a whole AD).

### DD-7 — AD-554 convergence: **NOT wired.** Here is the arithmetic.

The AD-1140 prompt deferred this decision to AD-1141 and warned that *"defaulting to 'yes, it seems useful' is the failure mode."* Decision: **no**, and here is why, measured rather than asserted.

**Cost per call.** `check_cross_agent_convergence` (`records_store.py:662`) runs two passes:

- **First pass, UNCAPPED** (`:719-736`): `for md_file in agent_dir.glob("*.md")` — full `read_text` + `_parse_document` on **every** `.md` in **every** agent directory, *before* the staleness filter at `:730`.
- **Second pass, capped** (`:740`): `entries[:max_scan_per_agent]` with `max_scan_per_agent = 5` (`:672`).

So the per-publish cost is **O(total notebook files on the ship)** — uncapped, and growing monotonically with exactly the volume AD-1141 exists to increase. Each report is itself a record the next scan reads.

**Alert volume.** It fires when `similarity >= convergence_threshold` (`0.5`, `:669`) **and** `dept != anchor_department`, requiring `min_convergence_agents = 2` and `min_convergence_departments = 2` (`:673-674`). Crew children of one parent goal are **assigned across departments by design** and produce topically-adjacent findings. That is precisely the shape that trips it. Wiring it means a normal multi-department crew session emits convergence alerts as its **expected** output — bridge alert fatigue on day one.

Both the cost and the alert volume scale with the thing this AD increases. **Not wired.** If the Captain wants it, it needs its own flag *and* a cap on the first pass — a separate AD. Note it in the build report; the next free BF is **BF-680** if the uncapped first pass is to be filed as a defect.

### DD-8 — Failure isolation: log-and-degrade, never propagate

A Σ consult that fails must not fail the child's task. **Degrade tier: log-and-degrade** (`except Exception: logger.warning(...); commons_block = ""`).

This is not optional politeness. `crew_executor.py:903-921` catches exceptions from `self._executor.run(...)` and persists `stopped_reason="execution_exception"`. If a consult raised into that path, a commons outage — an unreachable ChromaDB, a corrupt record — would **fail every child of every session**. The consult must be wrapped tightly enough that no exception from Oracle, the records store, or the semantic layer reaches the executor's `try`.

Wrap the consult in its own `try/except Exception` **outside** the executor's `try`. Warning message per the standard: what failed, why it matters, what happens next — e.g. *"AD-1141: commons consult failed for crew child %s; continuing with the unaugmented task text"*.

Publish failures need no new handling — they are tool calls inside the loop, already isolated.

### DD-9 — `expected_output` reaches the producer

The one part of #1062 that is straightforwardly right. `expected_output` is already persisted into child metadata (`crew_session.py:1196`: `metadata["expected_output"] = projection["expected_output"]`, carried into `WorkItemPlanInsert(metadata=metadata)` at `:1225`) and already read by the verifier (`crew_verifier.py`), but **the producer never sees the criterion it will be judged against.**

Read `active_child.metadata.get("expected_output")` — free, additive, no schema change, no hash impact. Bound at `_MAX_EXPECTED_OUTPUT_CHARS = 1000`. Inject under its own framed header (DD-4).

**But it goes through `task_text`, not `extra_context`** — same correction as everything else in this AD.

Gate it on the **same** flag as the commons block. A separate flag would create a third arm the ablation does not model, and `sigma_flags.py`'s guard would then be describing a config surface the harness cannot toggle coherently.

### DD-10 — Budget: 2 000 chars, hard

`SensoriumConfig.warning_chars = 10000` (`config.py:3738`). The whole injected block is bounded at `crew_sigma_max_chars = 2000` (default), with `_MAX_ENTRY_CHARS = 400` per entry and `crew_sigma_max_entries = 4`.

Why smaller than `oracle_query`'s `_MAX_OUTPUT_CHARS = 6000`: that budget is for a lookup the agent **asked for**. An **unrequested** injection into every child must be materially smaller, because it is paid on every child whether or not it helps.

Truncation is visible — when entries are dropped for budget, emit the budget note (DD-4). **Count the injected characters** and record the count so the ablation can attribute context growth. Recording it as a logged/emitted metric is fine; recording it in `crew_execution` evidence is **forbidden** (14-key contract).

### DD-11 — Default-OFF, and exactly ONE new path in `sigma_flags.py`

New fields on `AgenticToolsConfig` (`config.py:6036`, beside the AD-1139/AD-1140 fields at `:6067-6070`):

| Field | Default | Notes |
|---|---|---|
| `crew_sigma_context_enabled` | `False` | **bool** — the single ablation gate |
| `crew_sigma_max_chars` | `Field(default=2000, ge=200, le=8000)` | int |
| `crew_sigma_max_entries` | `Field(default=4, ge=1, le=12)` | int |
| `crew_sigma_min_score` | `Field(default=0.35, ge=0.0, le=1.0)` | float |
| `publish_finding_max_per_hour_ship` | `Field(default=40, ge=1, le=500)` | int (DD-6) |

**Only `crew_sigma_context_enabled` goes into `sigma_flags.py`** — both dicts, plus the verified-line comment block at `sigma_flags.py:27-33`. The other four are ints/floats and **`apply_flags` requires every path to resolve to a `bool`** (`sigma_flags.py`, `apply_flags`); adding an int path turns the structural guard red. That is the guard working correctly — do not "fix" it by loosening `apply_flags`.

`SIGMA_OFF["agentic_tools.crew_sigma_context_enabled"] = False`, `SIGMA_ON[...] = True`.

**Missing the flag turns the ablation's treatment arm into a second control arm** — a silent measurement failure, not a loud one.

### DD-12 — The ablation rig has two gaps this AD must close

Both verified. Without these, `SIGMA_ON` silently degrades and the ablation measures nothing.

1. **`sigma_rig.py` never registers `publish_finding`.** It wires `_register_oracle_query_tool` (`sigma_rig.py:336`, `:347-350`) and stops. So `agentic_tools.publish_finding_enabled=True` in `SIGMA_ON` registers **nothing** in the rig, and no child can publish in the treatment arm. Add `_register_publish_finding_tool` alongside it, mirroring the existing block.
2. **`sigma_reachability_problems` does not check crew Σ** (`sigma_rig.py:363-378`). It checks `oracle_query_enabled` ⇒ oracle present + tool registered, and `records.semantic_index_enabled` ⇒ records store present. Extend it: when `crew_sigma_context_enabled` is on, an absent `runtime.oracle` ⇒ `"crew_sigma_oracle_unavailable"`; when `publish_finding_enabled` is on, an unregistered tool ⇒ `"publish_finding_tool_not_registered"`.

Its docstring already states the rule: *"Live mode must refuse rather than score a treatment arm that silently degraded into a second control arm — that failure mode is invisible in the numbers and would be read as 'Σ had no effect'."* Honour it.

`CrewTaskExecutor` has exactly **one** construction site in production (`startup/finalize.py:1874`) plus the rig's (`sigma_rig.py:439`). Constructor-inject the Oracle and config bounds (DIP); do **not** reach `getattr(self._runtime, "oracle", None)` inside the hot path.

---

## Build

1. **`src/probos/cognitive/crew_executor.py`** —
   - Module-level framing constants (DD-4) and bounds (`_MIN_CONSULT_QUERY_CHARS`, `_MAX_CONSULT_QUERY_CHARS`, `_MAX_ENTRY_CHARS`, `_MAX_EXPECTED_OUTPUT_CHARS`).
   - Pure `_compose_child_task_text(...)` (DD-1) and a pure `_render_commons_block(results, *, max_chars, max_entries, min_score) -> str` returning `""` when nothing clears the floor (DD-3).
   - `async def _consult_commons(...)` — bounded query, `tiers=SIGMA_TIERS`, own `try/except Exception` (DD-8).
   - `__init__` gains keyword-only `oracle: Any = None` and the four bounds (defaults matching config), so the OFF path and existing constructions are unchanged.
   - At `:890`: compute `task_text` exactly as today, then pass it through `_compose_child_task_text`. **`extra_context` at `:898-901` is untouched.**
2. **`src/probos/startup/finalize.py`** — pass `oracle=` and the four bounds into `CrewTaskExecutor(...)` (`:1874`), read off `config.agentic_tools`.
3. **`src/probos/tools/publish_finding_tool.py`** — ship-wide deque + `max_per_hour_ship` constructor param, checked before the per-author limiter (DD-6).
4. **`src/probos/startup/communication.py`** — pass `max_per_hour_ship` into `PublishFindingTool` at `_register_publish_finding_tool`.
5. **`src/probos/config.py`** — five `AgenticToolsConfig` fields (DD-11); extend the class docstring the way AD-1139/AD-1140 did.
6. **`tests/ablation/sigma_flags.py`** — the one bool path in both dicts + the verified-line comment.
7. **`tests/ablation/sigma_rig.py`** — register `publish_finding`; extend `sigma_reachability_problems`; pass the new `CrewTaskExecutor` kwargs.
8. **`tests/test_ad1141_crew_loop_sigma.py`** (NEW) — ≈30 tests.

---

## Acceptance

### 1. Byte-identity with the flags OFF — **CRITERION #1**

- `_compose_child_task_text(base)` with every optional argument empty returns `base` **unchanged**; assert identity, not just equality.
- With `crew_sigma_context_enabled=False`, the `task_text` passed to `WorkItemAgenticExecutor.run` equals `active_child.description or active_child.title or ""` **exactly** — capture it with a recording double and compare against a literal recomputation, not a golden file.
- With the flag off, the `extra_context` dict passed to `run` is exactly `{"_crew_session_id": …, "_crew_work_item_id": …}` — the same two keys, no more.
- With the flag off, **`OracleService.query` is called zero times** against a recording double.
- With the flag off, `WorkItemAgenticExecutor.run`'s `tool_ids` is byte-identical to today.
- Persisted `crew_execution` evidence with the flag ON is **key-for-key identical** to the flag-OFF case.

### 2. Crew contracts untouched

- Assert the **exact 14-key** `crew_execution` set as a literal in the test, and that a real run produces exactly it.
- Assert the **frozen 12-field** `SubtaskResult` set as a literal, and that `set(dataclasses.fields(SubtaskResult))` names match.
- **Plan-identity hash stability:** build a plan, record `plan_seed_hash`, run children with the flag ON, rebuild the projection, and assert the hash is unchanged. Then run AD-1127 recovery over it and assert green.
- Assert `active_child.description` is **not** mutated by the run.

### 3. Consult

- A child whose commons holds a relevant record receives it in `task_text`, with the disposition framing and a provenance marker, and **`active_child.description` is unchanged**.
- **Zero-cost empty path:** when every result scores below `crew_sigma_min_score`, the composed `task_text` is **byte-identical to the base** — no header, no note, no whitespace delta.
- Query floor: a child whose title+description is under 24 chars ⇒ `OracleService.query` called **zero** times.
- Entry cap and char budget both enforced; the budget note appears only when entries were actually dropped.
- `episodic` never appears in the tiers passed to `query` — assert against the recorded call, and assert `SIGMA_TIERS` is the imported constant.
- Consult raising ⇒ the child still runs, `task_text` is the base, a contextual warning is logged, and the persisted result is `done` (DD-8).

### 4. Publish — headline round trip

> A crew child in session **A** (department *science*) publishes a finding through `publish_finding`. A **new** `OracleService` is constructed over the same on-disk paths — standing in for a later session. A **different** agent (department *engineering*, different callsign) invokes `oracle_query` and receives the claim text with its provenance marker.

- The publish nudge is present in `task_text` when the flag is on and `publish_finding` is registered; absent when the tool is not registered (do not nudge toward a verb the agent does not have).
- **Ship-wide budget:** the 41st publish in an hour is refused with `metadata["reason"] == "ship_rate_limited"` and **no write**, even when every author is under its own 12/hr limit. Prove it with two authors so the ship bound is provably not the per-author one.
- Ship budget is checked **before** the per-author limiter: an author at 12/12 with the ship at 40/40 reports `ship_rate_limited`, not `rate_limited`.
- The ship deque does not grow without bound under a burst.

### 5. `expected_output`

- Present in `task_text` under its framed header when the flag is on and the metadata key is populated.
- Absent (and no header emitted) when the key is missing or empty.
- Bounded at 1000 chars.

### 6. Framing

- **Every** module-level authored string constant, and **every** composed `task_text` across the success / empty / truncated / no-tool paths, is clean under the **real imported** `_CAPABILITY_GAP_RE` — import it, do not re-type it.
- The empty-consult constant exists, is clean, and is asserted **never emitted** in this AD.

### 7. Ablation surface

- `set(SIGMA_ON) == set(SIGMA_OFF)` and every path resolves on a live `SystemConfig()` to a `bool` (existing guards — run them).
- `"agentic_tools.crew_sigma_context_enabled"` is present in both dicts.
- The rig registers `publish_finding` when the flag is on.
- `sigma_reachability_problems` returns a named problem when `crew_sigma_context_enabled` is on and `runtime.oracle` is `None`, and when `publish_finding_enabled` is on and the tool is unregistered.

### 8. Sovereignty

- A full crew run with the flag ON produces **zero** `EpisodicMemory` calls from the consult path against a recording double.

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Validation plan — targeted only

**The full suite takes ~21 minutes and must NOT be run.**

- **Focused:** `tests/test_ad1141_crew_loop_sigma.py -q -n 0`
- **Crew contracts, ONCE, after the focused gate is green:**
  `tests/test_ad859_crew_executor.py tests/test_ad859a_agentic_executor.py tests/test_ad1124_crew_session_contract.py tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad1130_outcome_only_room_trust.py tests/test_ad867_crew_orchestrator.py tests/test_ad860_crew_verifier.py -q -n 0`
- **Σ surface, ONCE:** `tests/test_ad1139_oracle_query_tool.py tests/test_ad1140_publish_finding.py -q -n 0`
- **Ablation guard, ONCE:** `tests/ablation/test_sigma_harness_structural.py -q -n 0`

Every path above was listed from `tests/` and exists.

| Suite | What it pins |
|---|---|
| `test_ad859_crew_executor.py` | The executor path this AD modifies at `:890`. |
| `test_ad859a_agentic_executor.py` | `extra_context` validation and the `tool_ids` assembly, both of which must stay byte-identical. |
| `test_ad1124_crew_session_contract.py` | The plan projection and `plan_seed_hash`. |
| `test_ad1125_room_bound_execution.py` | Room-bound execution + artifact evidence. |
| `test_ad1126_verified_finalization.py` | The frozen `SubtaskResult` shape through finalization. |
| `test_ad1127_crew_session_lifecycle_recovery.py` | **The recovery path all three contracts protect.** |
| `test_ad1128_crew_session_ingress_dedup.py` | Ingress dedup over the same session state. |
| `test_ad1130_outcome_only_room_trust.py` | The room-append path publications must stay out of. |
| `test_ad867_crew_orchestrator.py` | The orchestrator that drives `CrewTaskExecutor.run`. |
| `test_ad860_crew_verifier.py` | The verifier that consumes `expected_output`. |
| `test_ad1139` / `test_ad1140` | The read and write halves being wired. |
| `ablation/test_sigma_harness_structural.py` | The two `sigma_flags.py` guards. |

**If `test_ad1127_crew_session_lifecycle_recovery.py` or `test_ad1124_crew_session_contract.py` goes red, STOP and surface it immediately.** Red there means a crew contract moved, which criterion #1 and the three-contract section both forbid. Do not attempt a fix — surface it.

---

## Do NOT build here

❌ **Building the injection through `extra_context`** — it does not reach the prompt (see the correction section). ❌ Crew-child compaction (AD-1142, #1063). ❌ Any change to the 14-key `crew_execution` evidence set, the 12-field `SubtaskResult`, or the persisted `description` / plan projection. ❌ Widening `_AGENTIC_EXTRA_CONTEXT_KEYS`. ❌ Wiring AD-554 `check_cross_agent_convergence` into the publish path (DD-7 — the arithmetic says no). ❌ Capping AD-554's uncapped first pass (note it; BF-680 if filed). ❌ The ablation harness itself (AD-1143 — **shipped**; only `sigma_flags.py` and `sigma_rig.py` are touched, per DD-11/DD-12). ❌ Federation transport, routing, or any import from `src/probos/federation/`. ❌ Anything touching the episodic shard, `MemoryAccessPolicy`, or `OWN_SHARD_PLUS_PUBLIC`. ❌ Parent/planner consultation of the commons (DD-2 — children only). ❌ Per-turn consultation inside `AgenticLoop`. ❌ Executor-side or finalizer-side auto-publish (DD-5). ❌ Changes to the finalizer convergence path. ❌ Asynchronous child spawning, sibling-to-sibling messaging, adaptive re-planning, mid-flight Captain steering. ❌ Changing `SIGMA_TIERS`, `_CLASSIFICATION_LEVELS`, or `_RECORDS_QUERY_SCOPE`. ❌ Loosening `apply_flags`'s bool requirement to admit the int/float knobs. ❌ Editing `config/system.yaml` (skip-worktree `S`, Captain-local). ❌ A new AD or BF number.

---

## Files (verify each at build)

- `src/probos/cognitive/crew_executor.py` — framing constants, the two pure composers, `_consult_commons`, `__init__` kwargs, the `:890` call site.
- `src/probos/startup/finalize.py` — `CrewTaskExecutor(...)` at `:1874`.
- `src/probos/tools/publish_finding_tool.py` — ship-wide deque.
- `src/probos/startup/communication.py` — `_register_publish_finding_tool` passes `max_per_hour_ship`.
- `src/probos/config.py` — five `AgenticToolsConfig` fields.
- `tests/ablation/sigma_flags.py` — one bool path in both dicts + comment block.
- `tests/ablation/sigma_rig.py` — publish registration + reachability check + executor kwargs.
- `tests/test_ad1141_crew_loop_sigma.py` (NEW).

---

## Builder checks (unverifiable from the spec — confirm before relying on them)

1. **`OracleService.query`'s return shape.** The renderer needs `.content`, `.score`, `.provenance`, and `.metadata` (`query_formatted` at `oracle_service.py:644-661` reads exactly those). Confirm the dataclass/field names at HEAD before writing `_render_commons_block`; do not assume `oracle_query_tool`'s internal rendering helpers are reusable — they are private to that module.
2. **Is `score` comparable across tiers?** `query` merges six tiers. If per-tier scores are not on a common scale, a single `crew_sigma_min_score` floor is biased toward whichever tier scores highest. Check how `query` normalizes before trusting the floor; if it does not normalize, say so in the config docstring and in the build report rather than pretending the floor is principled.
3. **Does `startup/finalize.py:1874` run after the Oracle exists?** `runtime.oracle` is assigned at `runtime.py:2526`, and Tier 5/6 are attached later (`:2743`, `:2862`). Confirm ordering at the `CrewTaskExecutor(...)` construction; if the Oracle is not yet available there, inject a zero-argument provider callable rather than reaching `getattr(runtime, "oracle", None)` in the hot path.
4. **`_register_publish_finding_tool`'s current signature.** DD-6 adds a `max_per_hour_ship` parameter; confirm the AD-1140 registration function's shape and whether `init_communication` already threads the AD-1140 bounds, so the new bound follows the same route rather than inventing a second one.
5. **Recording-double shape for `WorkItemAgenticExecutor`.** Criterion #1's byte-identity tests need the exact `task_text` and `extra_context` as passed. Check what `tests/test_ad859_crew_executor.py` already uses and follow it (BF-287: real fixtures at the registry/permission boundary; a recording double is fine for the *executor* seam because it is the thing under observation).
6. **Does `active_child.metadata` survive the store round trip with `expected_output` intact?** It is written at `crew_session.py:1196` into `WorkItemPlanInsert(metadata=…)` (`:1225`); confirm `WorkItemStore` persists and returns it unmodified before relying on `metadata.get("expected_output")`.

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` · `DECISIONS.md`.

The AD-1141 entry must record: that **`extra_context` does not reach the prompt** and the injection is into `task_text` (correcting issue #1062); that the consult uses a **score floor with a zero-character empty path** so a pointless consult costs zero context; that **the child decides** what to publish, through AD-1140's tool, with no executor-side write; the **ship-wide 40/hr budget** and the honest statement that it bounds rate but **not** the dedup window population; that **AD-554 convergence is deliberately NOT wired**, with the O(total notebook files) first-pass cost and the cross-department alert-volume reasoning; and that `crew_sigma_min_score = 0.35` is a **starting value, not a derived one**.

---

## Done-when

Criterion #1 proven — flags off ⇒ byte-identical `task_text`, `extra_context`, `tool_ids`, persisted evidence, and plan-identity hash, with zero Oracle calls; the exact 14-key evidence set and frozen 12-field `SubtaskResult` asserted as literals and unchanged; AD-1127 recovery green; a child consulting the commons receives framed, provenance-marked, budget-bounded context and its `description` is unmutated; the empty-consult path adds **zero** characters; `expected_output` reaches the producer; the headline round trip green across a freshly constructed `OracleService` with a different agent in a different department; the ship-wide budget enforced ahead of the per-author limiter and proven with two authors; every authored string clean under the real `_CAPABILITY_GAP_RE`; `sigma_flags.py` carrying exactly one new bool path with both structural guards green; `sigma_rig.py` registering `publish_finding` and refusing an unreachable treatment arm; focused + crew-contract + Σ + ablation gates green; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-25, HEAD `9e8b8264`)

```
src/probos/cognitive/crew_executor.py
  335: class CrewTaskExecutor:
  338:     def __init__(                                    # 8 kwargs; oracle/bounds to be added
  353:         self._runtime = runtime
  482:         sem = asyncio.Semaphore(self._max_parallel)
  622:         execution = metadata.get("crew_execution")
  623:         if type(execution) is not dict or set(execution) != {   # <-- EXACT 14-key set
  624-637:            version parent_id work_item_id thread_id assigned_to status
                      stopped_reason output_summary tool_trace_ref artifact_refs
                      tokens_used started_at finished_at blocked_dependency_ids
  639:             raise ValueError("crew_execution_evidence_invalid")
  890:         task_text = active_child.description or active_child.title or ""   # THE SEAM
  892:             outcome = await self._executor.run(
  895:                 task_text=task_text,
  898:                 extra_context={                       # tool-context only; NOT the prompt
  903:         except Exception:                             # consult must stay OUTSIDE this

src/probos/cognitive/crew_finalizer.py
 1909:         if set(result_values) != {                    # <-- frozen 12-field SubtaskResult
 1910-1912:            work_item_id spec_id agent_id output status tool_trace_ref
                       started_at finished_at stopped_reason actual_tokens
                       artifact_refs blocked_dependency_ids
 1915:         result = SubtaskResult(**result_values)

src/probos/cognitive/crew_session.py
 1006:     projection = {
 1009:         "description": description,                   # <-- INSIDE the plan identity
 1015:         "expected_output": _plan_optional_text(
 1174:     plan_seed_hash = hashlib.sha256(projection_bytes).hexdigest()
 1196:             "expected_output": projection["expected_output"],   # -> child metadata
 1225:             metadata=metadata,
 1574:         if hashlib.sha256(projection_bytes).hexdigest() != candidate.plan_seed_hash:

src/probos/cognitive/agentic_dispatch.py
   59: _AGENTIC_EXTRA_CONTEXT_KEYS = frozenset(              # 7 keys; strict + length-checked
   61-67:    agent_id department rank thread_id _delegation_depth
             _crew_session_id _crew_work_item_id
   79: _GATED_TOOL_IDS = frozenset({"event_log_query","oracle_query","publish_finding"})
  639:     async def run(
  676:         if extra_context is None:
  677-682:        type/len/key validation -> ValueError("agentic_context_invalid")
  929:         publish_ids: list[str] = []                   # AD-1140 offer block, already live
  940:         tool_ids = list(
 1013:         _context.update({agent_id, department, rank, thread_id})
 1021:         agentic_result = await loop.run(
 1022:             system_prompt=instructions or "",
 1023:             user_message=task_text,                    # <-- the ONLY prompt seam
 1025:             context=_context,                          # <-- tool context, not prompt

src/probos/cognitive/swe_harness/agentic_loop.py
  600:     async def run(
  622:         messages: list[dict] = [
  623:             {"role": "system", "content": system_prompt},
  624:             {"role": "user", "content": user_message},   # context is ABSENT from messages
  626:         agent_id = str(context.get("agent_id", "<unknown>"))   # logging only
  753:                 context=context,                          # tool execution only
  820:             use, agent_id=agent_id, iteration=iteration, context=context

src/probos/cognitive/oracle_service.py
   67: _RECORDS_QUERY_SCOPE = "ship"
   83: def make_reader_identity_resolver(                     # BF-679
  467:     async def query(                                   # the consult surface
  620:     async def query_formatted(                          # unframed; NOT used here
  644-661:    reads r.provenance / r.score / r.metadata / r.content

src/probos/tools/oracle_query_tool.py
   55: SIGMA_TIERS: tuple[str, ...] = (records semantic graph archive operational health)
   65: SOVEREIGN_TIER = "episodic"
   72: _MAX_OUTPUT_CHARS = 6000                              # requested lookup; ours is 2000
   75: _MAX_QUERY_CHARS = 512
   89: _ORACLE_DISPOSITION: str = "(These entries come from ..."   # the framing shape

src/probos/knowledge/records_store.py
  513:     async def check_notebook_similarity(
  521:         max_scan_entries: int = 20,
  641:             for _, md_file in entries[:max_scan_entries]:
  662:     async def check_cross_agent_convergence(            # AD-554 — NOT wired (DD-7)
  669:         convergence_threshold: float = 0.5,
  672:         max_scan_per_agent: int = 5,                    # caps only the SECOND pass
  673:         min_convergence_agents: int = 2,
  674:         min_convergence_departments: int = 2,
  710:             for agent_dir in sorted(notebooks_dir.iterdir()):
  719:                 for md_file in agent_dir.glob("*.md"):  # <-- UNCAPPED first pass
  721:                     raw = md_file.read_text(encoding="utf-8")
  730:                         if entry_ts <= staleness_cutoff:   # filter AFTER the read
  740:                 for _, md_file, topic, dept in entries[:max_scan_per_agent]:

src/probos/cognitive/decomposer.py
   33: _CAPABILITY_GAP_RE = re.compile(
   36:     ... |lack(?:s|ing)?| ...                            # bare substring: "black hole" trips
   39:     re.IGNORECASE,

src/probos/config.py
 3734: class SensoriumConfig(BaseModel):
 3738:     warning_chars: int = Field(                         # 10_000
 6036: class AgenticToolsConfig(BaseModel):  # AD-1072
 6067:     oracle_query_enabled: bool = False  # AD-1139
 6068:     publish_finding_enabled: bool = False  # AD-1140
 6069:     publish_finding_max_per_hour: int = Field(default=12, ge=1, le=100)
 6070:     publish_finding_max_content_chars: int = Field(default=4000, ge=200, le=20000)
 6277:     max_parallel_subtasks: int = Field(default=3, ge=1, le=64)   # AgenticDispatchConfig

src/probos/workforce.py
  619: class WorkItem:
  627:     description: str = ""
  643:     metadata: dict[str, Any] = field(default_factory=dict)   # carries expected_output

src/probos/startup/finalize.py
 1874:     crew_executor = CrewTaskExecutor(                   # the ONE production construction

src/probos/runtime.py
 2526:         self.oracle = cog.oracle_service                # public alias
 2782:             oracle=self.oracle,                         # AD-1139
 2783:             records_store=self._records_store,          # AD-1140

tests/ablation/sigma_flags.py
   34: SIGMA_OFF: dict[str, Any] = {                          # 3 paths today
   40: SIGMA_ON: dict[str, Any] = {
       apply_flags(...) raises TypeError unless every path resolves to bool

tests/ablation/sigma_rig.py
  336:         from probos.startup.communication import _register_oracle_query_tool
  347:         _register_oracle_query_tool(                    # publish_finding: ABSENT (DD-12)
  363: def sigma_reachability_problems(rig: CrewRig) -> tuple[str, ...]:
  371:     if rig.config.agentic_tools.oracle_query_enabled:   # no crew-Σ check (DD-12)
  439:     crew_executor = CrewTaskExecutor(

Framing strings (DD-4): all 8 candidates run against the live imported
_CAPABILITY_GAP_RE at HEAD 9e8b8264 -> clean.
```
