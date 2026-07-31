# AD-1145 — Standards adoption: W3C PROV-O provenance projection (OpenTelemetry export DEFERRED)

**Issue: #1070 · Epic #1068 · Nooplex interop track · sibling of AD-1144 (`69908523`, verified ancestor of HEAD).**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1145** (#1070). HEAD at investigation: `b766254e`. AD ceiling: **AD-1151** shipped. BF ceiling: **BF-680** shipped. Next free: **AD-1152 / BF-681**. No new AD, no new BF minted here.**

Ship a pure, dependency-free projection of ProbOS's **existing** execution and records provenance onto the W3C PROV-O vocabulary as JSON-LD. **The OpenTelemetry half of #1070 is deferred** — it does not survive investigation at HEAD. Rationale and the honest re-scope of #1070 are in §Verdict.

---

## Verdict — build one half, defer the other

| Half | Verdict | One-line reason |
|---|---|---|
| **PROV-O projection** | ✅ **BUILD** — but over the surface #1070 did **not** name | `crew_execution` + records frontmatter already carry Agent, Activity, Entity and derivation. Pure read-only mapping, zero new instrumentation, zero dependencies. |
| **OpenTelemetry export** | ❌ **DEFER** | Spans are **not** constructible from the events that exist: parallel tool calls are indistinguishable, there is no run/trace id, and the token metric would present a BF-680 estimate as a measurement. It is not "pure reuse", and there is no collector. |

### Why PROV-O is not a placebo (the AD-1149 test applied)

AD-1149 was deferred because it optimised something nobody could measure. The distinguishing test is **"does it cost anything when unused, and does it assert anything false?"**

- The projection is a **pure function over data already persisted**. Not called ⇒ zero cost, zero risk, byte-identical.
- It asserts nothing new. It re-expresses facts the crew evidence record already commits to.
- It has a **standing interop surface**: `federation/ard/` exists precisely to be consumed by third parties, and `DECISIONS.md` DD-2 already commits the ARD envelope to "mirror the public A2A agent-card / ai-plugin / **JSON-LD** conventions". AD-1144 made ARD signatures verifiable by a stock JOSE library; PROV-O makes the provenance inside readable by stock RDF tooling. Same precedent, same subsystem.
- It follows AD-1144's own **DD-1 vendorable-shared-definition** pattern: in-tree, pure stdlib, so any harness can vendor it.

That is a different shape from an exporter that adds a dependency, runs a background task, and ships to nowhere.

### Why OpenTelemetry does not survive investigation

#1070 asserts: *"Transport — export the existing EventLog to OTel (traces for agentic loop iterations and tool calls…). **Pure reuse.**"* Three verified facts falsify "pure reuse":

1. **Parallel tool calls cannot be paired.** `AGENTIC_TOOL_CALL_STARTED` emits `{agent_id, tool_id, iteration}` (`agentic_loop.py:1190-1197`) and `..._COMPLETED` emits `{agent_id, tool_id, iteration, is_error, duration_ms}` (`:1227-1235`). Neither carries `use.tool_call.id`, which **is** available at the call site and is discarded. Under AD-1147 concurrency (`PARALLEL_TOOL_CALLS_MAX = 16`), N simultaneous calls to the *same* `tool_id` in the *same* `iteration` are indistinguishable. Start↔end correlation — the definition of a span — is impossible.
2. **There is no trace id.** No loop-run identifier exists. `correlation_id` / `parent_event_id` are populated **only** on the intent-broadcast and consensus paths (`runtime.py:3597, 3627, 3634, 3764, 3918, 3927`) — never on the agentic path. Nothing roots the span tree.
3. **The token metric would lie.** `AGENTIC_LOOP_ITERATION` carries `total_tokens` but not `token_source` (`agentic_loop.py:801-807`). Worse, `WorkItemAgenticOutcome.token_source` exists in memory (`agentic_dispatch.py:634`) and is **dropped at the frozen persistence boundary** — `crew_execution` persists `tokens_used` (`crew_executor.py:644`) and the 14-key set has no room for a provenance label. An OTel gauge fed from either surface would publish a BF-680 `estimated` value as a measurement. The stated acceptance criterion forbids exactly this.

Fixing (1)–(3) means **new instrumentation at every call site plus a change to a frozen contract** — both explicitly on this AD's do-not list. And `opentelemetry` appears **zero** times in `d:\ProbOS\src`: there is no collector, no backend, no consumer.

**The OSS seam OTel would need already exists and is already proven.** `runtime.add_event_listener(fn, event_types)` (`runtime.py:1414`) is the AD-254/AD-637d subscription seam, already consumed by the commercial overlay's AD-C-031 Airlock listener. Any exporter — OSS or commercial — attaches there today with **no OSS change**. There is therefore no OSS work to do for transport, and building an exporter now would be dead code against a dependency.

### Where #1070 is wrong at HEAD

| #1070 claim | Verified state |
|---|---|
| "ProbOS has this as an ad-hoc structure — `ProvenanceTag(source_tier, retrieval_timestamp, confidence, content_hash)`… Emitting PROV-O-compatible terms… makes ProbOS provenance machine-readable" | **Wrong surface.** `ProvenanceTag` (`provenance.py:20-27`) has **no agent** and **no activity**. `query_with_provenance()` accepts `agent_id` and **discards it** — `from_oracle_result` (`:82-93`) builds the tag from `result` alone. A PROV-O document projected from it would be *valid but vacuous*: entities with generation times and nothing about who or how — the exact opposite of Nooplex §4.3.4's "who or what created it… through what process, based on what inputs". |
| `content_hash` is usable as an entity identifier | `compute_content_hash` returns `hexdigest()[:8]` (`provenance.py:60`) — **32 bits**. Unusable as a global IRI. |
| "Transport — export the existing EventLog to OTel… **Pure reuse.**" | Falsified. See (1)–(3) above. |
| "ProbOS emits none [of the observability signal]" | Half wrong. The **span-shaped events already exist** (`AGENTIC_LOOP_ITERATION`, `AGENTIC_TOOL_CALL_STARTED/COMPLETED`, `TOOL_INVOKED` with `duration_ms` at `executor.py:158-165`). What is missing is not emission but **correlation**. |
| "Add an optional OTel exporter alongside the EventLog" | The subscription seam already exists (`runtime.py:1414`) and is already used by the commercial overlay. No OSS work. |

### How to re-scope #1070 so the deferred half is tracked honestly

Do **not** silently drop it. On merge:

1. **Retitle #1070** to `AD-1145: Standards adoption — W3C PROV-O provenance projection` and edit the body to remove the OTel section, replacing it with a one-line pointer to the successor issue.
2. **Open a successor issue** under epic #1068, titled `AD-1152: Agentic-loop span correlation (OpenTelemetry prerequisite)`, carrying the three blockers verbatim: (a) put `tool_call.id` and a per-run id into the `AGENTIC_TOOL_CALL_*` payloads; (b) decide where `token_source` lives given the frozen 14-key `crew_execution` set; (c) name a real collector/consumer before any exporter is written. State plainly that **the exporter itself is out of scope for OSS** while the only seam consumer is the commercial overlay.
3. AD-1152 is the next free number and is **not** minted by this AD — the Architect assigns it when the successor issue is opened.

---

## Pinned design decisions

### DD-1 — Project from the surfaces that actually carry PROV-O's triad; do not project `ProvenanceTag`
Two verified sources, both already persisted, both complete:

**A. Crew execution evidence** (`crew_executor.py:634-648`, the frozen 14-key set):

| PROV-O term | ProbOS field |
|---|---|
| `prov:Activity` | `work_item_id` |
| `prov:Agent` (`prov:SoftwareAgent`) | `assigned_to` |
| `prov:wasAssociatedWith` | Activity → Agent |
| `prov:wasInformedBy` | `parent_id` |
| `prov:Entity` + `prov:wasGeneratedBy` | each `artifact_refs` entry |
| `prov:used` | `tool_trace_ref` |
| `prov:startedAtTime` / `prov:endedAtTime` | `started_at` / `finished_at` |

**B. Ship's Records frontmatter** (`records_store.py:238-254`):

| PROV-O term | ProbOS field |
|---|---|
| `prov:Entity` | the record path |
| `prov:wasAttributedTo` | `author` |
| `prov:generatedAtTime` | `created` |
| `prov:wasRevisionOf` | `revision` (n → n−1) |

`ProvenanceTag` is **out of scope**. Say so in the build report. Adding an agent/activity to it is a separate AD, not a projection.

### DD-2 — Read-only projection; zero writes, zero new instrumentation
The module reads dicts it is handed. It does **not** touch `crew_execution` construction, validation, or the 14-key set; does not call the store; does not emit events; does not import from `crew_executor` or `records_store`. Input is a plain `dict`, output is a plain `dict`. This is what makes it byte-identical when unused.

### DD-3 — Pure stdlib, in-tree, zero dependencies — AD-1144 DD-1 precedent
No `rdflib`, no `pyld`, no JSON-LD processor. A PROV-O JSON-LD document is a plain dict with an `@context`; emitting one needs no library. **No `pyproject.toml` change of any kind** — not core, not an extra.

### DD-4 — Honest omission over invention
A term whose source field is absent or empty is **omitted**, never defaulted. Specifically: `assigned_to` is `str | None` in the record — when `None`, emit **no** `prov:wasAssociatedWith` and **no** `prov:Agent` node rather than a placeholder agent. A consumer must be able to distinguish "unattributed" from "attributed to unknown".

### DD-5 — No token count in the projection (BF-680)
`tokens_used` is **excluded** from PROV-O output. PROV-O has no term for it, `crew_execution` carries no `token_source`, and `WorkItemAgenticOutcome.token_source` (`agentic_dispatch.py:634`) is dropped before persistence — so at this surface the value's provenance is **unknowable**. Emitting it would present a possible BF-680 estimate as a fact. A test asserts the string `tokens_used` never appears in projected output.

### DD-6 — IRIs are opaque, deterministic and namespaced
Use `urn:probos:` URNs: `urn:probos:activity:<work_item_id>`, `urn:probos:agent:<assigned_to>`, `urn:probos:entity:<sha256>`. Derive **only** from identifiers already in the record. Do **not** use `compute_content_hash` (32-bit truncation, `provenance.py:60`). No hostname, no filesystem path, no user identity in an IRI.

### DD-7 — Optional exposure through one existing endpoint, default-OFF
`src/probos/routers/records.py` already serves `GET /api/records/documents/{path:path}`. Add an **opt-in query parameter** (recommended `?format=prov-jsonld`) that returns the projection. Absent the parameter the response is **byte-identical** to today. Do not add a route; do not change any default response body; do not touch `/browse`, `/graph`, `/timeline`, or `/backlinks`.

**FLAG AT BUILD:** if the endpoint's existing response model or auth shape makes a query parameter non-additive, ship the module + tests only and state that in the build report. The pure module is the deliverable; the endpoint is convenience. Do **not** invent a new route to create a caller.

### DD-8 — Semantic conventions are documentation, not code
#1070 asks for "cognitive semantic conventions". Those are an **OTel** artifact and belong with the deferred half. This AD documents the **PROV-O mapping table only**, in `docs/`. No attribute registry, no convention constants, no OTel naming.

---

## Build

1. **`src/probos/knowledge/provo.py` (NEW)** — pure-stdlib PROV-O projection. Zero `probos` imports. Public surface:
   - `PROV_CONTEXT: dict` — the JSON-LD `@context` binding the `prov:` prefix to `http://www.w3.org/ns/prov#`.
   - `project_crew_execution(record: dict) -> dict` — DD-1 table A.
   - `project_record_frontmatter(path: str, frontmatter: dict) -> dict` — DD-1 table B.
   - Both return `{"@context": …, "@graph": [...]}`. Both **never raise** on malformed input — a missing/ill-typed field is omitted (DD-4), matching the AD-1095 honest-degrade contract. Full type annotations.
2. **`src/probos/routers/records.py`** — additive, default-OFF query parameter per DD-7.
3. **`docs/development/prov-o-mapping.md` (NEW)** — the two DD-1 tables, the DD-5 exclusion and its reason, and a worked example document.
4. **Tests** — `tests/test_ad1145_provo_projection.py`.

## Acceptance

- **Vocabulary validity:** every emitted predicate is a real PROV-O term (`prov:Entity`, `prov:Activity`, `prov:Agent`, `prov:SoftwareAgent`, `prov:wasGeneratedBy`, `prov:wasAttributedTo`, `prov:wasAssociatedWith`, `prov:wasInformedBy`, `prov:used`, `prov:wasRevisionOf`, `prov:startedAtTime`, `prov:endedAtTime`, `prov:generatedAtTime`). A test asserts the emitted predicate set is a **subset** of an explicit allowlist — no invented `prov:` term can ship.
- **Round-trip without loss:** for a full 14-key `crew_execution` record, every projected field recovers its source value exactly — `work_item_id`, `assigned_to`, `parent_id`, `tool_trace_ref`, each `artifact_refs` entry, `started_at`, `finished_at`. Timestamps round-trip through ISO-8601 to the same float.
- **DD-5 / BF-680:** `"tokens_used"` and `"token_source"` appear **nowhere** in projected output, asserted on the serialized JSON string.
- **DD-4 honest omission:** `assigned_to=None` ⇒ no `prov:Agent` node and no `prov:wasAssociatedWith` edge. Empty `artifact_refs` ⇒ no generated entities. Neither raises.
- **Never raises:** `{}`, `None`-valued fields, wrong types, and an over-long id all return a well-formed document rather than an exception.
- **Purity (AD-1144 DD-5 precedent):** an assertion that `src/probos/knowledge/provo.py` contains **zero** `probos` imports.
- **Default-inert:** `GET /api/records/documents/{path}` with no `format` parameter returns a body **byte-identical** to HEAD. `tests/test_ad562_records_*.py` pass unchanged.
- **No dependency:** `pyproject.toml` unchanged — asserted by the Builder in the build report by diff.
- **No frozen-contract change:** the 14-key `crew_execution` set is untouched; `tests/test_ad1125_room_bound_execution.py` and `tests/test_ad1126_verified_finalization.py` pass unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Validation plan

**The full suite must NOT be run in this AD.** Named files only.

- **Focused coding gate:**
  `tests/test_ad1145_provo_projection.py -n 0`
- **Adjacent regression gate** (verify each path exists at build; skip any that does not):
  `tests/test_records_store.py tests/test_ad562_records_browse_endpoint.py tests/test_ad562_records_graph_endpoint.py tests/test_ad562_records_timeline_endpoint.py tests/test_ad562_records_backlinks_endpoint.py -n 0`
- **Frozen-contract gate:**
  `tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py tests/test_ad1151_durable_tool_outputs.py -n 0`
- **Untouched-surface gate** (proves `ProvenanceTag` was not modified):
  `tests/test_ad677_context_provenance.py -n 0`
- Run with isolated `PROBOS_DATA_DIR` and `PROBOS_EMBEDDINGS=local`.
- No UI change ⇒ no Vitest / Playwright / `npm run build` gate.
- Wave-close and clean-checkout CI gates are the Architect's call after review — **not** the Builder's, and **not** part of this AD.

## Do NOT build here

❌ **Any OpenTelemetry code, dependency, exporter, or semantic convention** — deferred to the successor issue (§Verdict). ❌ A telemetry backend or collector. ❌ Any change to the frozen 14-key `crew_execution` set, `SubtaskResult`, or `description` in the plan-identity hash. ❌ Any change to the AD-1151 tool-trace blob shape. ❌ Any change to `ProvenanceTag`, `ProvenanceEnvelope`, `compute_content_hash`, or `query_with_provenance` — DD-1 puts them out of scope; do not "improve" them. ❌ New instrumentation at any call site — no new event, no new event payload field, no `tool_call.id` plumbing. ❌ Any `pyproject.toml` change, core or extra. ❌ Any third-party JSON-LD / RDF library. ❌ A new API route (DD-7 is a query parameter on an existing endpoint, or nothing). ❌ Commercial features, pricing, or enterprise-tier language in this repo — the overlay seam at `runtime.add_event_listener` already exists and needs no OSS change; do not write about it beyond that fact. ❌ Touching `federation/ard/` or anything AD-1144 shipped. ❌ A new AD or BF number — AD-1152 is reserved for the successor issue and is minted by the Architect, not here.

## Files (verify each at build)

- `src/probos/knowledge/provo.py` (NEW) — PROV-O projection, pure stdlib, zero `probos` imports.
- `src/probos/routers/records.py` — additive default-OFF `format` query parameter (DD-7; droppable per the FLAG).
- `docs/development/prov-o-mapping.md` (NEW) — mapping tables + DD-5 exclusion rationale.
- `tests/test_ad1145_provo_projection.py` (NEW) — vocabulary allowlist, round-trip, DD-4 omission, DD-5 exclusion, never-raises, purity, default-inert endpoint.

## Verified against codebase (2026-07-26, HEAD `b766254e`)

```
git merge-base --is-ancestor 69908523 HEAD   → 0  (AD-1144 is in)

grep -rn "opentelemetry\|OTLP" d:\ProbOS\src
  (no matches — no collector, no backend, no consumer)

src/probos/cognitive/provenance.py
  20: class ProvenanceTag:            # source_tier, retrieval_timestamp, confidence, content_hash, metadata
  60:     return hashlib.sha256(content.encode()).hexdigest()[:8]      # 32 bits
  82:     def from_oracle_result(cls, result)                          # agent_id NOT stored

src/probos/cognitive/crew_executor.py
  634:    record = {  ... "parent_id", "work_item_id", "assigned_to", "tool_trace_ref",
  644:        "tokens_used": actual_tokens,     # no token_source companion
  648:        "blocked_dependency_ids": dependencies }

src/probos/cognitive/agentic_dispatch.py
  634:    token_source: str = "measured"        # in-memory only; dropped before persistence

src/probos/cognitive/swe_harness/agentic_loop.py
  599:  TOKEN_SOURCE_ESTIMATED = "estimated"
  801:  self._fire_event("AGENTIC_LOOP_ITERATION", {agent_id, iteration, tools_used_so_far, total_tokens})
 1190:  self._fire_event("AGENTIC_TOOL_CALL_STARTED", {agent_id, tool_id, iteration})     # no tool_call.id
 1227:  self._fire_event("AGENTIC_TOOL_CALL_COMPLETED", {agent_id, tool_id, iteration, is_error, duration_ms})

src/probos/tools/executor.py
  158:  EventType.TOOL_INVOKED  {agent_id, tool_id, duration_ms, error, timestamp}

src/probos/runtime.py
 1414:  def add_event_listener(self, fn, event_types=None)      # seam already exists (AD-254/637d)
 3597,3627,3634,3764,3918,3927:  correlation_id/parent_event_id  # intent + consensus ONLY

src/probos/knowledge/records_store.py
  238:  "author": author,
  241:  "created": now,
  253:  existing_rev = existing_fm.get("revision", 1)

src/probos/routers/records.py                     → exists
src/probos/extensions/overlay.py:54               → register_finalize_hook
tests/test_records_store.py, tests/test_ad562_records_*.py,
tests/test_ad677_context_provenance.py, tests/test_ad1125_*, tests/test_ad1126_*,
tests/test_ad1151_*                               → all exist
```

## Done-when

All acceptance green; the four named gates green; Architect review findings repaired; `pyproject.toml` diff empty; PROV-O purity asserted; `ProvenanceTag` provably untouched; no `tokens_used` in any projected document; full type annotations on new public functions; #1070 retitled and the OTel successor issue opened per §Verdict before the AD is marked complete; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
