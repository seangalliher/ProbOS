# AD-1151 — Persist tool OUTPUTS in the durable trace (cognitive / swe_harness)

**Issue: #1076 · corrects the false claim in AD-1148 (#1073, DD-2) and AD-1142 (#1063) · pairs with AD-1146 (#1071) / AD-1147 (#1072) / AD-1148 (#1073).**
**Repo: OSS (`d:\ProbOS`). AD ceiling: highest AD in the trackers is AD-1137; AD-1138–1150 are assigned via #1063–#1075. This AD = **AD-1151** (#1076). Highest BF = BF-677. No new BF.**

The durable tool trace records only the *call requests*. Persist the *outputs* alongside them, bounded, content-addressed, without changing the ref contract or the evidence key set.

---

## Why / context

`_persist_tool_trace` (`src/probos/cognitive/agentic_dispatch.py:1027-1080`) serialises exactly one thing:

```python
payload = [
    dataclasses.asdict(tc) for tc in getattr(agentic_result, "tool_calls", [])
]
blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
```

`tool_calls` is a `list[ToolCallRequest]` — `name`, `arguments`, `id`, `timestamp` (`swe_harness/tool_call.py:20-27`). The corresponding `ToolCallResult.output` (`:29-36`) is **never persisted anywhere durable**. What a tool actually returned exists only in the working message history, and is discarded when the run ends.

Two shipped ADs justified themselves against **Nooplex §3.3 Transparency** ("all operations within the NoÖplex produce observable traces — provenance records, reasoning logs, decision histories, and audit trails") on the strength of that guarantee:

- **AD-1148** (#1073) DD-2 asserted "the durable trace keeps the FULL output". It does not. The Builder correctly detected this and substituted an enforceable assertion (bounding does not alter the persisted blob — `tests/test_ad1148_tool_result_bounds.py:396-430`), but the truncated content is genuinely lost.
- **AD-1142** (#1063, Σ epic) carries the same incorrect claim.

Every context-reduction feature widens the gap. This AD closes it.

**The seam is already clean.** In the loop body (`agentic_loop.py:497-511`), `tool_results: list[ToolCallResult]` holds the **full untruncated** outputs in REQUEST order, and `result.tool_calls.append(use.tool_call)` runs in the same block. AD-1148 bounding is applied strictly later and only when building messages (`build_tool_result_messages(...)` at `:519-524`, `self._bound_tool_output(...)` at `:530`). The full output is in scope at the exact point where the trace-bearing list is assembled.

---

## Pinned design decisions

### DD-1 — Capture on an additive `AgenticResult.tool_results` field, at the loop

Add `tool_results: list[ToolCallResult] = field(default_factory=list)` to `AgenticResult` (`agentic_loop.py:287-296`) and extend it at the `:506-511` seam, next to the existing `result.tool_calls.append(...)`.

Safe because: there are exactly **two** construction sites, both zero-argument — `agentic_loop.py:369` (`result = AgenticResult()`) and `tests/test_ad545_agentic_loop.py:75` — and **no** test asserts an exact `AgenticResult` field set (grepped `__dataclass_fields__` / `fields(AgenticResult)` across `tests/`). A defaulted additive field appended after `error: str = ""` keeps dataclass field ordering legal and every existing consumer working.

**Rejected: the existing post-hook seam.** `agentic_dispatch.py:697-704` already attaches `executor.add_post_hook(_record_tool_result)` and could capture every result without touching `AgenticResult`. Rejected on three counts: (a) it puts *capture* in the caller, not the loop — `AgenticLoop` is also constructed by `swe_harness/native_builder.py:99` (`loop.run()` at `:115`), which today persists nothing, and hook-based capture would make the outputs structurally unreachable there forever; capture belongs at the loop, persistence at the caller; (b) the hook receives the AD-423a `ToolResult` plus a context dict — **not** the `ToolCallResult` — so correlating back to `ToolCallRequest.id` needs new plumbing through the executor; (c) `_persist_tool_trace(agentic_result, runtime, agent_id)` receives only the result object, so a hook-captured list would require a second parameter, widening a seam the issue explicitly says not to refactor.

This is **not** a change to `ToolCallResult` and **not** a change to the `Tool` protocol. Both stay frozen and untouched.

### DD-2 — Merged per-entry shape; the blob stays a bare JSON array

Each array element keeps the four legacy `ToolCallRequest` keys **unchanged** and gains result keys:

```json
{
  "name": "run_python", "arguments": {...}, "id": "call-1", "timestamp": 1.0,
  "output": "<full or head+tail-truncated text>",
  "is_error": false,
  "output_chars": 20000,
  "output_truncated": false
}
```

**Superset invariant — this AD never removes information that exists today.** For every entry, the four legacy keys are present and equal to `dataclasses.asdict(request)`. Assert it directly.

Entries are joined by `ToolCallResult.id == ToolCallRequest.id` (exact — `_execute_one_tool` sets `id=use.tool_call.id` at `agentic_loop.py:673/681`), not by list index. A request with no matching result (defence in depth; not reachable today) emits the legacy keys only.

Alternatives rejected:

- **Envelope object** (`{"version": 2, "tool_calls": [...], "tool_results": [...]}`) — breaks the one live bare-array parse, `tests/test_ad1148_tool_result_bounds.py:429` (`json.loads(...)[0]["name"]`), and any external tooling, for no functional gain. Grepped: no production reader parses the blob at all — every `tool_trace_ref` use in `src/` (`crew_executor.py`, `crew_finalizer.py`, `crew_session.py`, `crew_verifier.py`) is ref-string validation or propagation, never a blob read.
- **Second attachment with its own sha** — disqualified by the contract. `WorkItemAgenticOutcome` carries exactly one `tool_trace_ref` (`agentic_dispatch.py:617`) and the 14-key `crew_execution` evidence set (`crew_executor.py:622-636`) may not gain a key, so a second sha has nowhere to live.
- **Parallel top-level key** — impossible; the blob has no top-level object.

Versioning is by **key presence** (feature detection), which is what a bare array admits. Document that in the helper docstring. `tool_trace_ref` remains `sha256(blob).hexdigest()` → still 64-hex → still satisfies `_SHA_RE` in `_normalize_trace_ref` (`crew_executor.py:122-133`).

### DD-3 — `duration_ms` is deliberately NOT persisted

`ToolCallResult.duration_ms` is wall-clock: `(time.perf_counter() - start) * 1000.0` (`agentic_loop.py:672` and `:677`). Persisting it would make the blob differ between two otherwise-identical runs and **break** `tests/test_ad1148_tool_result_bounds.py::test_bounding_does_not_alter_the_persisted_tool_trace`, which asserts `bounded_store.blobs == unbounded_store.blobs` across two separate loop runs.

Excluding it costs nothing in transparency: the loop already emits `duration_ms` on the `AGENTIC_TOOL_CALL_COMPLETED` event (`agentic_loop.py:686-694`), so the timing is already observable. Persisting it a second time would buy a broken adjacent test.

Assert `"duration_ms" not in entry` explicitly, with the reason in the test docstring, so a future Builder does not "helpfully" add it back.

### DD-4 — Two caps on `AgenticLoopConfig`; durable **must** exceed context; enforced at parse time

A durable store is not a licence for unbounded blobs. Two new fields on the existing `AgenticLoopConfig` (`src/probos/config.py:4369`, added by AD-1146 and extended by AD-1147/1148 — follow the same `Field(...)` + long-description style):

| Field | Default | Meaning |
|---|---|---|
| `tool_trace_output_max_chars` | `8192` | Per-output durable ceiling. `0` = do not persist outputs at all ⇒ today's exact blob. |
| `tool_trace_max_bytes` | `262_144` | Whole-blob ceiling in encoded bytes (256 KiB). `0` = no total cap. |

`8192` is deliberately **larger** than AD-1148's default context budget (`tool_result_head_chars=4000` + `tool_result_tail_chars=2000` = 6000). A durable cap at or below the context cap makes this AD pointless — so **encode it**: a `model_validator(mode="after")` on `AgenticLoopConfig` raises when

```
tool_result_max_chars > 0 and tool_trace_output_max_chars > 0
and tool_trace_output_max_chars < tool_result_max_chars
```

Fail fast rather than clamp silently — silent clamping hides operator intent. When `tool_result_max_chars == 0` the working context is unbounded and the comparison is vacuous; the validator must **not** fire. Test both branches.

`262_144` is deliberately conservative. `attachments.max_store_bytes` defaults to 5 GiB (`config.py:2544-2545`), so a worst-case trace is ~0.005% of the store. It is small for a second reason: `AttachmentStore.write` can raise `AttachmentStoreFullError`, and the existing `except Exception` in `_persist_tool_trace` degrades that to `None` — losing the **whole** trace, call records included. A bigger blob makes that failure more likely, so the total cap protects the records this AD is trying not to regress.

### DD-5 — Deterministic call-order allocation; elision is marked, never silent

**Per output:** reuse `truncate_tool_output` (`agentic_loop.py:88-137`) **unchanged**. It already does head+tail with a gap-regex-safe marker. Do not modify it, do not fork it — call it with `max_chars=tool_trace_output_max_chars` and the configured head/tail.

**Whole blob:** serialize, then shrink from the tail. Build every entry with its (per-output-bounded) output, `json.dumps(..., sort_keys=True, default=str).encode("utf-8")`, and while `len(blob) > tool_trace_max_bytes` and an un-elided entry remains, elide the **last** un-elided entry's output whole and re-serialize. Exact on bytes (no encoding-overhead estimation), deterministic, and bounded by the number of tool calls. Earlier calls keep their outputs; the reader can see exactly where the budget ran out.

**Requests are never dropped.** If a fully-elided blob still exceeds `tool_trace_max_bytes`, emit it anyway and log a warning naming the agent and the byte count. Losing call records to save bytes would regress today's guarantee.

**Elision is machine-readable, not a sentinel string.** `output_chars` (the ORIGINAL length, always) plus `output_truncated` (bool) disambiguate all three cases:

| Case | `output` | `output_chars` | `output_truncated` |
|---|---|---|---|
| Tool returned nothing | `""` | `0` | `false` |
| Head+tail truncated | `"<head>…marker…<tail>"` | original `N` | `true` |
| Elided whole by total cap | `""` | original `N` | `true` |

A reader can always tell "elided" from "the tool returned nothing". Assert all three rows.

### DD-6 — Default-**ON**, as an explicit convention-#14 carve-out

Convention #14 (default-OFF on transitional flags) is enforced hard in this repo, with exactly one documented carve-out — `warm_boot.enabled` (`docs/research/warm-boot-fragmentation-design.md:78`), granted because "a boot-time scan that's off-by-default would silently miss the very fragmentation it exists to catch."

The same reasoning applies here, and it is the reason this AD differs from AD-1146/1147/1148. Those three are performance/protocol features where OFF is a neutral starting position. This one **closes a stated Transparency guarantee gap**. AD-1142 and AD-1148 both justified themselves against §3.3 on a claim that was false; shipping the correction OFF leaves the claim false in the shipped default and makes the correction cosmetic. An audit trail that is off by default does not audit.

The cost is bounded and quantified (DD-4): ≤256 KiB per trace against a 5 GiB store. The compatibility risk is structurally absent (DD-2: the array shape and every legacy key are preserved, so existing traces and parsers keep working whether the feature is on or off).

**Builder: state this carve-out in the `tool_trace_output_max_chars` field description**, the way the warm-boot doc does, so a reviewer does not flag a #14 violation — and so nobody copies it as precedent for a non-guarantee feature.

The OFF path (`tool_trace_output_max_chars = 0`) must produce a blob **byte-identical** to today's for the same input. Test it against a literal recomputation of today's expression, not against a golden file.

Config is read defensively, mirroring `resolve_tool_result_bounds` (`agentic_loop.py:139+`): `getattr(getattr(runtime, "config", None), "agentic_loop", None)`, with a missing / non-`int` / negative value degrading to the **module default** (i.e. ON), not to zero. Synthetic and event-neutral runtimes must not silently lose the trace outputs.

### DD-7 — All four honest-degrade paths preserved verbatim

`_persist_tool_trace` returns `None` and logs a warning — never raises — on:

1. `getattr(runtime, "attachment_store", None)` raising (`:1040-1048`);
2. `store is None` (`:1049-1050`, returns `None` silently, no warning — preserve that exactly);
3. serialisation failure inside the `try` (`:1063-1071`);
4. `store.write(...)` failure inside the same `try`, including `AttachmentStoreFullError`.

Paths 3 and 4 share one handler. The new payload-shaping code sits **inside** that `try`, so a malformed result degrades to `None` rather than failing the dispatch (AD-731 / log-and-degrade tier). Test all four.

---

## Build

1. **`AgenticResult.tool_results`** — additive field (DD-1), populated at `agentic_loop.py:506-511` alongside `result.tool_calls.append(...)`. One line of capture; keep the existing DD-2 request-order comment accurate.
2. **Pure payload builder** in `swe_harness/agentic_loop.py`, beside `truncate_tool_output`:
   `build_tool_trace_payload(tool_calls, tool_results, *, output_max_chars, blob_max_bytes) -> tuple[list[dict[str, Any]], bytes]`
   Fully annotated, no I/O, no logging of blob content. Returns the entry list and the final encoded blob so the caller does not re-serialize. Reuses `truncate_tool_output` unchanged.
3. **Config resolver** `resolve_tool_trace_bounds(cfg) -> dict[str, int]` in the same module, mirroring `resolve_tool_result_bounds` exactly (same defensive `type(...) is int` guard that also rejects `bool`).
4. **Config** — two fields + the cross-field `model_validator(mode="after")` on `AgenticLoopConfig` (`config.py:4369`). DD-6 carve-out stated in the field description.
5. **`_persist_tool_trace`** (`agentic_dispatch.py:1027-1080`) — read the config off `runtime` defensively, call the builder, hash and write the returned blob. **Function-local import** from `swe_harness.agentic_loop`, matching the existing pattern at `agentic_dispatch.py:660-664` (that import is function-local, which suggests a module cycle — Builder: confirm before hoisting it to module scope; if there is no cycle, still keep it local for consistency). Signature unchanged: `(agentic_result, runtime, agent_id) -> str | None`. Do not touch its callers.
6. **Tests** — `tests/test_ad1151_durable_tool_outputs.py` (NEW), ≈20 tests.

---

## Acceptance

**Headline (the test that would have failed before this AD):**

- A tool output larger than `tool_result_max_chars` is **truncated in the message history** (elision marker present, content ≤ the context cap) **and retained in full** in the persisted blob (`output_truncated is False`, `len(output) == output_chars == original length`), in a single run with `tool_result_max_chars` small and `tool_trace_output_max_chars` large.

**Durability:**

- A completed agentic run persists both the call requests and their outputs, retrievable by the returned sha.
- **Real-store round trip:** `FilesystemAttachmentStore(tmp_path)` → `_persist_tool_trace` → `await store.read(ref)` → `json.loads` → the full outputs are present, and `hashlib.sha256(blob).hexdigest() == ref`.
- `AgenticResult.tool_results` is populated in request order across multiple iterations, with ids matching `tool_calls` entry-for-entry.
- `AgenticResult()` still constructs with no arguments; `tool_results == []`.

**Shape and contract:**

- **Superset property:** every entry carries all four legacy keys, equal to `dataclasses.asdict(request)`.
- The blob is still a bare JSON **array** (`json.loads(blob)` is a `list`; `[0]["name"]` resolves).
- **DD-3:** `"duration_ms"` is absent from every entry.
- `tool_trace_ref` still satisfies `_SHA_RE` — assert by calling the **real** `_normalize_trace_ref` (imported from `crew_executor`) and requiring it returns the ref unchanged.
- The 14-key `crew_execution` evidence set is unchanged — assert the **exact** key set, gaining and losing nothing.

**Bounds:**

- An output over `tool_trace_output_max_chars` is head+tail truncated, `output_truncated is True`, `output_chars` is the ORIGINAL length, and `len(output) <= tool_trace_output_max_chars`.
- When the total cap is hit, later outputs are elided whole and marked; earlier outputs survive; **every** entry keeps its request keys; the final blob is ≤ `tool_trace_max_bytes`.
- All three DD-5 rows are distinguishable (nothing / truncated / elided).
- Config raises when the durable per-output cap is below a non-zero context cap; does **not** raise when the context cap is `0`.

**Degrade and legacy:**

- Store-unwired, accessor-raises, write-failure and `AttachmentStoreFullError` paths all still return `None` without raising.
- `tool_trace_output_max_chars = 0` ⇒ blob **byte-identical** to `json.dumps([dataclasses.asdict(tc) for tc in tool_calls], sort_keys=True, default=str).encode("utf-8")`.
- `ToolCallResult` and the `Tool` protocol unchanged; `stopped_reason` vocabulary unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Validation plan — targeted only

**The full suite takes ~20 minutes and must NOT be run.**

- **Focused:** `tests/test_ad1151_durable_tool_outputs.py -q -n 0`
- **Adjacent, ONCE, after the focused gate is green:**
  `tests/test_ad1148_tool_result_bounds.py tests/test_ad1147_parallel_tools.py tests/test_ad1146_multiturn_messages.py tests/test_ad545_agentic_loop.py tests/test_ad859a_agentic_executor.py tests/test_ad859_crew_executor.py tests/test_attachment_reaper.py -q -n 0`
- **Evidence-contract guards, ONCE:**
  `tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py -q -n 0`

Why these exactly (grepped, not guessed):

| Suite | What it pins |
|---|---|
| `test_ad1148_tool_result_bounds.py` | `:396-430` calls the real `_persist_tool_trace` and asserts blob equality across two runs **and** `json.loads(blob)[0]["name"]`. DD-2 and DD-3 exist to keep this green **unmodified**. |
| `test_ad859a_agentic_executor.py` | `:267-305` `mime="application/json"`, `origin="crew_trace"`, 64-hex ref; `:310-339` store-unwired ⇒ `None`. |
| `test_ad859_crew_executor.py` | `:236-237` the ref is a ref, not inline bytes. |
| `test_attachment_reaper.py` | `:86-108` `crew_trace` durability; `:113+` LRU order vs `chat_attachment`. |
| `test_ad1125_room_bound_execution.py` | `:61` the 14-key set; `:569` `len(evidence["tool_trace_ref"]) == 64`. |
| `test_ad1126_verified_finalization.py` | `:95` the 14-key set again, on the finalizer path. |
| `test_ad1146/1147/ad545` | The loop paths the capture seam sits in. |

If `test_ad1148_tool_result_bounds.py` goes red, **stop and surface it** — do not edit that file. A red there means DD-2 or DD-3 was violated.

---

## Do NOT build here

❌ Changing `ToolCallResult` or the `Tool` protocol. ❌ Changing the `crew_execution` evidence key set (14 keys, exactly). ❌ Retention / GC policy for the attachment store (the reaper is a separate concern). ❌ Anything in the Σ epic beyond correcting the AD-1142 claim. ❌ Refactoring `_persist_tool_trace`'s callers or its signature. ❌ Touching AD-1148's truncation logic (`truncate_tool_output`, `_bound_tool_output`, `build_tool_result_messages`) — **call** it, do not change it. ❌ Editing `tests/test_ad1148_tool_result_bounds.py`. ❌ Persisting `duration_ms`. ❌ A new attachment origin (`crew_trace` is registered — `attachments/store.py:22`, `filesystem_store.py:95`, `reaper.py:34`). ❌ Serving the blob over the API or surfacing it in the HXI. ❌ A new AD or BF number.

---

## Files (verify each at build)

- `src/probos/cognitive/swe_harness/agentic_loop.py` — `AgenticResult.tool_results`, the `:506-511` capture, `build_tool_trace_payload`, `resolve_tool_trace_bounds`.
- `src/probos/cognitive/agentic_dispatch.py` — `_persist_tool_trace` body only (`:1027-1080`).
- `src/probos/config.py` — extend `AgenticLoopConfig` (`:4369`) + cross-field validator.
- `tests/test_ad1151_durable_tool_outputs.py` (NEW).

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` · `DECISIONS.md` (AD-1151 entry: the corrected claim, the merged-entry shape, the DD-6 carve-out). Note in the AD-1151 entry that AD-1148's DD-2 and AD-1142's spec both carried the superseded claim.

---

## Done-when

Acceptance green; focused + adjacent + evidence-guard gates green; the headline truncation/retention test proven; superset property proven; OFF-path byte-identity proven; all four degrade paths proven; the real-store round trip proven; `test_ad1148_tool_result_bounds.py` green **without modification**; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-25, HEAD `ac7bbf54`)

```
src/probos/cognitive/swe_harness/agentic_loop.py
  288: class AgenticResult:
  291:     final_text: str = ""
  292:     tool_calls: list[ToolCallRequest] = field(default_factory=list)
  295:     stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
  296:     error: str = ""          # <-- SIXTH field; issue #1076 lists only five
  369:         result = AgenticResult()
  497:             tool_results = await self._execute_tool_uses(
  506:             tool_result_blocks = [
  510:                 result.tool_calls.append(use.tool_call)
   88: def truncate_tool_output(
  139: def resolve_tool_result_bounds(cfg: Any) -> dict[str, int]:
  672:             duration_ms = (time.perf_counter() - start) * 1000.0
  677:             duration_ms = (time.perf_counter() - start) * 1000.0
  686-694: _fire_event("AGENTIC_TOOL_CALL_COMPLETED", {... "duration_ms": tcr.duration_ms})

src/probos/cognitive/swe_harness/tool_call.py
   20: class ToolCallRequest:  name / arguments / id / timestamp
   29: class ToolCallResult:   id / output / is_error / duration_ms

src/probos/cognitive/agentic_dispatch.py
  617:     tool_trace_ref: str | None = None
  660-664: function-local import of AgenticLoop, resolve_parallel_tool_settings,
           resolve_tool_result_bounds
  697-704: observed_tool_results + executor.add_post_hook(_record_tool_result)
           (run_python only — the rejected alternative seam, DD-1)
 1027:     async def _persist_tool_trace(self, agentic_result, runtime, agent_id)
 1053:         dataclasses.asdict(tc) for tc in getattr(agentic_result, "tool_calls", [])
 1061:         origin="crew_trace",

src/probos/cognitive/swe_harness/native_builder.py
   99:         loop = AgenticLoop(
  115:         agentic_result: AgenticResult = await loop.run(
       (second AgenticLoop construction site; no _persist_tool_trace, no
        attachment_store — the harness path persists nothing today)

src/probos/cognitive/crew_executor.py
  122: def _normalize_trace_ref(value, child_id) -> str | None   # None or 64-hex only
  622-636: the exact 14-key crew_execution set

src/probos/config.py
 2544-2545: max_store_bytes: int = Field(default=5 * 1024 * 1024 * 1024,
 4369: class AgenticLoopConfig(BaseModel):
       tool_result_max_chars=0 / head=4000 / tail=2000

src/probos/attachments/store.py:22          "crew_trace",  # AD-859a
src/probos/attachments/filesystem_store.py:84  class FilesystemAttachmentStore
                                          :100 def __init__(self, root: Path)
                                          :206 async def write(...)
                                          :274 async def read(self, content_hash) -> bytes
src/probos/attachments/reaper.py:34         "crew_trace",

tests/test_ad1148_tool_result_bounds.py:396  test_bounding_does_not_alter_the_persisted_tool_trace
                                        :419  executor._persist_tool_trace(bounded, ...)
                                        :429  json.loads(...)[0]["name"] == "run_python"
tests/test_ad859a_agentic_executor.py:267/310  trace-ref + store-unwired contracts
tests/test_ad1125_room_bound_execution.py:61/569  14-key set + 64-char ref
tests/test_ad1126_verified_finalization.py:95     14-key set

Negative greps (justify DD-2's "no production reader"):
  grep tool_trace_ref src/**   -> 68 hits across 5 files, ALL ref-string
                                  validation/propagation; zero blob reads.
  grep tool_trace_ref ui/**    -> 0 hits.
  grep 'fields(AgenticResult)|__dataclass_fields__' tests/ -> no AgenticResult
                                  field-set assertion exists.
  grep 'AgenticResult(' -> only agentic_loop.py:369 and
                           tests/test_ad545_agentic_loop.py:75, both zero-arg.
```
