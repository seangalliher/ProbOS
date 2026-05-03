# Review: AD-487 — Self-Distillation v1 (Personal Ontology Map Step)

**Verdict:** ❌ Not Ready
**Pass:** 1
**Date:** 2026-05-03
**Headline:** Phantom LLMClient API (`chat()` doesn't exist) + phantom top-level config class (`Config` should be `SystemConfig`) + missing `connection_factory` parameter break Wave 5 conventions #1/#2 and AD-685 verify-first; v1 scope split is otherwise clean.

---

## Required (must fix before building)

### R1 — Phantom API: `LLMClient.chat()` does not exist (Hard-stop #2)

The prompt asserts an LLMClient method that is not in the live tree.

Live signature (verified):

```text
grep -n "^class\|async def" src/probos/cognitive/llm_client.py
  22:  class BaseLLMClient(ABC)
  26:    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse
 420:    async def complete(...)   # OpenAICompatibleClient
1060:   async def complete(...)   # MockLLMClient
```

Real shape: `await llm_client.complete(LLMRequest(prompt=..., system_prompt=..., tier=..., temperature=..., max_tokens=...))` returns `LLMResponse(content=..., model=..., tier=..., tokens_used=..., error=...)`.

Affected sites in the prompt:

- Dependencies section: `runtime.llm_client — read-only consumer (calls chat() with structured prompt)` → must say `complete()`.
- Solution Overview: `Calls LLM with structured self-query template` → fine prose, but tighten to reference `complete()`.
- Section 3 `PROBE_TEMPLATE` is a string — fine. But `probe_domain` body (when written) must build `LLMRequest(prompt=PROBE_TEMPLATE.format(domain=...), tier="standard"|"fast")` and call `await self._runtime.llm_client.complete(request)`, then read `response.content`.
- Test #6 (`test_probe_domain_calls_llm_with_template`): mock target is `llm_client.complete`, not `chat`.
- Hard-Stops footer: rename "LLMClient.chat signature differs" → "LLMClient.complete signature differs".
- Verified-Against-Codebase footer: replace `(Builder verifies LLMClient.chat signature at build time)` with the actual grep evidence above (see R4).

**This is the recurring "method-shape phantom" class flagged in DECISIONS.md convention #18-adjacent (3rd recurrence after TrustNetwork → Procedure → WorkItemStore.add).**

---

### R2 — Phantom class: `Config.self_distillation` (top-level config class is `SystemConfig`)

Section 4 says "Wire into `Config.self_distillation` field." There is no `Config` class in `src/probos/config.py`.

```text
grep -n "^class SystemConfig\|^class Config" src/probos/config.py
1805: class SystemConfig(BaseModel):
```

All sibling top-level wiring (AnomalyWindow, KnowledgeLoading, TaskContext, etc. — see `startup/finalize.py`) reads `config: SystemConfig`. Update Section 4 to: "Wire `self_distillation: SelfDistillationConfig = Field(default_factory=SelfDistillationConfig)` into `SystemConfig`."

---

### R3 — `__init__` is missing the `connection_factory` parameter (Wave 5 convention #2 violation; Hard-stop #4-adjacent)

Wave 5 convention #2 (stdlib-only persistence) and the canonical ConnectionFactory pattern require constructor injection of the factory. Every existing peer follows the same shape:

```text
grep -n "connection_factory: ConnectionFactory" src/probos/
  assignment.py:84
  clearance_grants.py:51
  consensus/trust.py:119
  identity.py:377
  acm.py:97
  cognitive/counselor.py:317
  skill_framework.py:358, 477
  persistent_tasks.py:110
```

Canonical body (assignment.py:84-93):

```python
def __init__(
    self,
    db_path: str | None = None,
    ...
    connection_factory: ConnectionFactory | None = None,
):
    self.db_path = db_path
    self._db: DatabaseConnection | None = None        # NOT ConnectionFactory
    self._connection_factory = connection_factory
    if self._connection_factory is None:
        from probos.storage.sqlite_factory import default_factory
        self._connection_factory = default_factory
```

Prompt Section 3 currently has:

```python
def __init__(self, runtime: Any, config: SelfDistillationConfig) -> None:
    ...
    self._db: ConnectionFactory | None = None    # WRONG — type is DatabaseConnection
```

Two defects:

1. No `connection_factory: ConnectionFactory | None = None` parameter.
2. `_db` is annotated as `ConnectionFactory` — it should be `DatabaseConnection` (see protocols.py:186 vs 223 — they are distinct types; factory creates connections, connection executes SQL).

Fix: align the constructor with the canonical pattern. Add a `start()` / `stop()` lifecycle (which subsumes `_ensure_schema`; see R5 below).

---

### R4 — Verify-first deferral to Builder (review-time discipline violation)

The prompt's "Verified Against Codebase" footer says:

```
grep -n "class LLMClient\|async def chat\|def chat" src/probos/cognitive/llm_client.py
  (Builder verifies LLMClient.chat signature at build time)

grep -n "ConnectionFactory\|connection_factory" src/probos/protocols.py
  (Builder verifies SQLite ConnectionFactory protocol — Wave 5 convention #2 stdlib-only persistence)

grep -n "class Config\b" src/probos/config.py
  (Builder verifies adding self_distillation: SelfDistillationConfig field)
```

This is exactly the verify-first slip the standing order forbids. R1, R2, R3 above all fall out of running these greps at architect time — which is the architect's job, not the Builder's. Replace with concrete grep hits and line numbers (use the evidence in R1-R3 above).

DECISIONS.md convention #16 (dispatch-time phantom-API scripted pre-check) caught zero phantoms here precisely because the prompt deferred verification — the pre-check can't validate kwargs against signatures that the prompt itself doesn't pin down. This is also the convention #19 / Wave 9-13 retrospective lesson.

---

## Recommended

### Rec1 — Replace private `_ensure_schema()` with `async start() / async stop()` lifecycle

Section 5 calls `await runtime.personal_ontology_prober._ensure_schema()` from `finalize.py`. Calling a `_private` method across module boundaries is a Demeter / Wave 5 convention #1 nit (the convention says public attributes; the implicit corollary is public methods for cross-module calls).

Canonical lifecycle (assignment.py:96-108): `async def start()` opens the connection, runs the schema, commits; `async def stop()` closes. Use that. Drop `_ensure_schema()` as a separate concept — it's part of `start()`. This also gives the runtime a clean shutdown path for the SQLite handle, which the current spec lacks.

### Rec2 — Method bodies for `probe_domain` / `_check_rate_limit` / `_persist` are unspecified (spec-gap)

Section 3 declares the surface but no bodies. Pattern from Wave 9B/10 retrospective (DECISIONS.md convention #19): drafts that omit bodies for non-trivial methods reproduce structural defects (async/sync mismatch, wrong row shape, malformed JSON path). Sketch each body:

- `probe_domain`: rate-limit check → build `LLMRequest` → `await llm_client.complete(...)` → `try: parsed = json.loads(response.content); except json.JSONDecodeError: parsed = {"sub_topics": [], "confidence": []}` → construct `ProbeResult` (raw_text always preserved per test #12) → `await self._persist(result)` → return.
- `_check_rate_limit`: `await self._db.execute("SELECT probed_at FROM agent_probes WHERE agent_id = ? AND domain = ? ORDER BY probed_at DESC LIMIT 1", (agent_id, domain))` → `row = await self._db.fetchone()` → if row and `(now - parsed_iso) < timedelta(hours=self._config.rate_limit_hours)`: emit `ONTOLOGY_PROBE_RATE_LIMITED`, return False; else True.
- `_persist`: `INSERT` with `json.dumps(sub_topics)` / `json.dumps(confidence_scores)` / ISO 8601 `probed_at`; `await self._db.commit()`; emit `ONTOLOGY_PROBE_RECORDED`.

Note: the `DatabaseConnection` protocol (protocols.py:186-216) does NOT expose `.cursor()` — use `execute / fetchone / fetchall` directly. The dispatch's "cursor pattern" shorthand is misleading.

### Rec3 — Section 5 wiring should follow the established phase-function shape

`finalize.py` phase functions have signature `def _wire_X(*, runtime: Any, config: "SystemConfig") -> int|bool`. Current snippet uses `getattr(runtime.config, "self_distillation", None)` then mutates `runtime`. Rewrite as:

```python
def _wire_self_distillation(*, runtime: Any, config: "SystemConfig") -> bool:
    if not config.self_distillation.enabled:
        return False
    from probos.cognitive.self_distillation.prober import PersonalOntologyProber
    prober = PersonalOntologyProber(runtime=runtime, config=config.self_distillation)
    runtime.personal_ontology_prober = prober
    return True
```

Then the phase entrypoint in `finalize.py` calls `await runtime.personal_ontology_prober.start()` after construction (per Rec1). The existing lifecycle uses `runtime.add_startup_hook` or a direct `await` in the phase entrypoint — grep `_wire_anomaly_window` callers in finalize.py for the live pattern; mirror it.

### Rec4 — `ProbeLLMError` and `ProbeRateLimitedError` are referenced in docstrings but not declared

Section 3's `Raises:` block names two exception classes that have no `class` declaration in the prompt. Add them to Section 1 (or Section 2 alongside `ProbeResult`). Test #10 will fail to import otherwise.

---

## Nits

### N1 — `PROBE_TEMPLATE` mixes f-string-style placeholder and JSON braces

Current template:

```python
PROBE_TEMPLATE = (
    "You are introspecting on your own knowledge. "
    "Answer in JSON: {{\"sub_topics\": [...up to 5...], \"confidence\": [0.0-1.0 each]}}\n\n"
    "What do you know about {domain}?"
)
```

Doubled `{{ }}` works only if the template is consumed via `.format(domain=...)`. State that explicitly in the docstring (`# Use .format(domain=domain), NOT f-string`), or pre-render with `% domain`. As written, an f-string interpolation `f"{PROBE_TEMPLATE}"` would `KeyError`. Low risk because Section 3 doesn't show the call site, but worth pinning down so Builder doesn't pick the wrong rendering style.

### N2 — `max_sub_topics` config field is dead

`SelfDistillationConfig.max_sub_topics: int = 5` is declared but the template hardcodes "up to 5". Either thread the value into the template (`f"... [...up to {max} ...]"` rendered at construction) or drop the config field for v1.

### N3 — `ProbeResult.probed_at: datetime` round-trip not pinned

Stored as ISO 8601 TEXT, parsed back in `get_recent_probes`. Spec should say `datetime.fromisoformat(row[6])` (or whichever index) and `value.replace(tzinfo=timezone.utc)` if naive. Tests #11 / #13 implicitly require correct round-trip.

---

## Verified

- **v1 scope is clean.** No Collapse / Reduce / PersonalOntology data structure / Daydream / DID-portability functionality smuggled into v1. `probe_domain` + `get_recent_probes` + persistence + 1 SQLite table + 2 EventTypes + 1 Pydantic config — exactly the Map step. Pre-deferral honesty PASSES.
- **AD-636 / AD-637f orthogonality.** AD-636 (priority lane semaphores) and AD-637f (priority classification) live INSIDE `LLMClient.complete` (llm_client.py:166, 427-457). They throttle LLM requests by tier and per-minute caps. AD-487's rate limit is per-(agent, domain, 24h) at the prober layer — about how often an agent introspects on a domain, not LLM token throughput. Orthogonal; no integration needed. Note this in the DECISIONS.md entry as an explicit non-conflict.
- **`agent_probes` table is absent in `src/`** (grep returned 0 hits). Schema isolation confirmed.
- **EventType collision check.** No `ONTOLOGY_*` or `PROBE_*` symbols in `src/probos/events.py`. Both new event types are collision-free.
- **ConnectionFactory protocol exists** (`src/probos/protocols.py:223`). DatabaseConnection (line 186) exposes the async `execute / executemany / executescript / fetchone / fetchall / commit / close` surface. Sufficient for AD-487's needs once R3 + Rec1 + Rec2 are applied.
- **Public attribute naming.** `runtime.personal_ontology_prober` (no underscore) follows Wave 5 convention #1 ✅.
- **15-test plan** covers happy path / error / boundary axes per the test discipline standing rule.
- **AD-685 kwarg pre-check.** Pre-check ran clean (0 phantoms per dispatch). Confirms convention #16 — but this review surfaces the kwarg-blind-spot from convention #19 (pre-check validates symbol existence, not kwarg shapes; that's why `chat()` slipped past it). Add a bug-fix-AD candidate: extend `phantom-api-precheck.ps1` to flag `<runtime_attr>.<unknown_method>(...)` calls when the method name doesn't appear in the target class's AST. (Already noted as a hygiene-AD candidate in DECISIONS.md convention #21.)

---

## Convention Sweep (23 standing conventions)

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ |
| 2 | stdlib-only persistence | ⚠️ ConnectionFactory protocol used, but constructor missing the parameter (R3) |
| 3 | RedTeam v1 health-monitor pattern | n/a |
| 4 | Onboarding-hook superset filter | n/a |
| 5 | `init_communication` `emit_event_fn` not `runtime.emit_event` | n/a (prober is post-init, has runtime) |
| 6 | PowerShell `\b` rename idiom | n/a |
| 7 | No-theater discipline | ✅ |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | n/a (no cross-layer hint needed) |
| 9 | ASCII-only source comments | ✅ |
| 10 | `work_item_store` vs `workforce` | n/a |
| 11 | `__new__`-bypass `getattr` | n/a |
| 12 | Solution Overview drift after revision | watch on revision pass |
| 13 | Pool template name collision | n/a |
| 14 | Aggressive pre-deferral | ✅ (1 of 4 capabilities) |
| 15 | Tolerance: 1 ⚠️ allowed | ❌ exceeded — 4 Required findings |
| 16 | Phantom-API pre-check | ✅ ran (0 phantoms by symbol-existence) but blind to method-shape (R1) |
| 17 | Mutable client state in `__init__` | n/a (no class-scope mutables proposed) |
| 18 | Mock both `.json()` and `.headers` | n/a (LLM mock target needs adjustment per R1) |
| 19 | Method-kwarg phantom blind spot | ⚠️ R1 is a recurrence; banked as Wave 14 retrospective candidate |
| 20 | Cross-wave dependency reads SHIPPED CODE | ✅ AD-636/637f read at code level, not at prompt |
| 21 | Structural-defect propagation | ⚠️ method-bodies-omitted pattern (Rec2) reproduced |
| 22 | v1 isolation | ✅ |
| 23 | Solution Overview drift closing self-check | watch on revision |

Convention #15 tolerance = 1 ⚠️. Actual = 4 Required + 3 ⚠️ → **❌ Not Ready**.

---

## Action Summary for Revision Pass

Apply R1, R2, R3, R4. Fold Rec1, Rec2, Rec3, Rec4. Judgment-call N1-N3. Re-run `scripts/phantom-api-precheck.ps1`. Append `## Revision (2026-05-03)` to the prompt body. Commit `Wave 14 revision: apply review findings to AD-487`.

Total findings: **4 Required, 4 Recommended, 3 Nits.**

---

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**Pass:** 2
**Reviewing:** revision commit `a22c1ed` against pass-1 at `34ae9ea`.
**Headline:** All 4 Required + 4 Recommended + 3 Nits resolved cleanly. Pre-check 0 phantoms. Verify-first restored with real grep evidence at HEAD. Ready for Builder dispatch.

### Resolution Audit

| Pass-1 Required | Status | Evidence |
|---|---|---|
| R1 (LLMClient.chat → complete) | ✅ | Solution Overview line 14 says `runtime.llm_client.complete(request)`; Dependencies line 26 says `complete(LLMRequest)`; Section 3 body sketch (probe_domain step 4) calls `await self._runtime.llm_client.complete(request, priority=Priority.NORMAL)` and reads `response.content`/`response.error`; Test #6 renamed to `test_probe_domain_calls_llm_client_complete_with_llm_request`; Hard-Stop #1 says "LLMClient.complete signature differs"; footer grep shows `BaseLLMClient.complete` at `llm_client.py:26`. Case-sensitive grep `\.chat\(|llm_client\.chat` against the prompt → 0 hits in shipping content. |
| R2 (Config → SystemConfig) | ✅ | Section 4 line 290 wires `self_distillation: SelfDistillationConfig = SelfDistillationConfig()` onto `class SystemConfig(BaseModel)`; explicit "verified at config.py:1805" annotation; Section 5 phase function signature is `(*, runtime: Any, config: "SystemConfig") -> bool` matching peer phase functions; DECISIONS.md draft says `SystemConfig.self_distillation`. Case-sensitive grep `(?<!System)Config\.self_distillation` → 0 hits in shipping content (residual matches are revision-prose changelog only). |
| R3 (connection_factory injection) | ✅ | Section 3 constructor at line 119: `__init__(self, runtime, config, *, connection_factory: ConnectionFactory | None = None)` matches the canonical 8-peer shape verbatim; default-factory fallback `from probos.storage.sqlite_factory import default_factory` (line 124); `_db: DatabaseConnection | None` (line 120) — correct type, distinct from `_connection_factory: ConnectionFactory`; body sketches use `await self._db.execute(...)` / `fetchone()` / `commit()` directly per protocol surface. Footer evidence enumerates all 9 peer call sites. |
| R4 (verify-first placeholders) | ✅ | All three `(Builder verifies ...)` placeholders gone from shipping content. Footer (lines 425-465) shows actual grep output with line numbers: `BaseLLMClient.complete:26`, `OpenAICompatibleClient.complete:420`, `MockLLMClient.complete:1060`, `LLMRequest:227`, `LLMResponse:240`, `DatabaseConnection:186`, `ConnectionFactory:223`, `SystemConfig:1805`, `default_factory:28`, all 9 `connection_factory: ConnectionFactory` peer sites, 0-hit collision check for `ONTOLOGY_PROBE`/`agent_probes`, 3 `_wire_*` phase function signatures. Architect re-ran every grep against HEAD as part of pass-2 verification (see "Architect Re-Verification" below) — all line numbers match exactly. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| Rec1 (start/stop lifecycle) | ✅ | Section 3 lines 130-141: `async def start()` opens connection, runs `_SCHEMA`, commits; `async def stop()` closes handle. No `_ensure_schema()` cross-module call remains. Section 5 calls `await prober.start()` after construction. Test #5 renamed to `test_start_creates_table_and_index`. |
| Rec2 (body sketches) | ✅ | All four methods have numbered body sketches in their docstrings: `probe_domain` (steps 1-8 with explicit `LLMRequest` construction, `try/except` for parse, `ProbeRateLimitedError` raise, `raw_text` always preserved per Test #12), `get_recent_probes` (SQL placeholder positions + `datetime.fromisoformat` round-trip), `_check_rate_limit` (event emission on rejection, return semantics), `_persist` (JSON encoding boundaries, ISO 8601 storage, event emission). Explicit note that `DatabaseConnection` lacks `.cursor()` — bodies use `execute/fetchone/fetchall/commit`. |
| Rec3 (Section 5 `_wire_` pattern) | ✅ | Section 5 rewritten as `async def _wire_self_distillation(*, runtime: Any, config: "SystemConfig") -> bool` with guard on `config.self_distillation.enabled`, explicit `runtime.personal_ontology_prober = prober` public-attribute assignment, `await prober.start()` async lifecycle. Call site colocated with `_wire_anomaly_window` near finalize.py:218. Async-vs-sync rationale documented inline. |
| Rec4 (typed exceptions) | ✅ | Section 2 lines 73-78 declare `ProbeLLMError(RuntimeError)` and `ProbeRateLimitedError(RuntimeError)` with one-line docstrings. Section 1 `__init__.py` exports both. Test #10 references `ProbeRateLimitedError` and will import cleanly. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| N1 (PROBE_TEMPLATE rendering) | ✅ | Comment above the constant says "Use `.format(domain=domain, max_sub_topics=N)` — NOT f-string. The doubled braces around the example JSON are literal output the model should emit." Body sketch step 2 uses `.format(...)`. |
| N2 (max_sub_topics threading) | ✅ | Template now interpolates `{max_sub_topics}` (line 110); body sketch passes `max_sub_topics=self._config.max_sub_topics` to `.format()`. Config field is no longer dead. |
| N3 (probed_at ISO 8601 round-trip) | ✅ | Schema column comment "ISO 8601 UTC, tz-aware"; `_persist` body sketch uses `result.probed_at.isoformat()`; `get_recent_probes` and `_check_rate_limit` body sketches use `datetime.fromisoformat(row[...])`; `probed_at=datetime.now(timezone.utc)` enforces tz-awareness on creation. Tests #11 and #13 acceptance criteria explicit. |

### Architect Re-Verification (HEAD = `a22c1ed`)

```text
src/probos/cognitive/llm_client.py
  26:   async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
  420:  async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
  1060: async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:

src/probos/types.py
  227: class LLMRequest:
  240: class LLMResponse:

src/probos/protocols.py
  186: class DatabaseConnection(Protocol):
  223: class ConnectionFactory(Protocol):

src/probos/config.py
  1805: class SystemConfig(BaseModel):

src/probos/storage/sqlite_factory.py
  28: default_factory = SQLiteConnectionFactory()

src/probos/startup/finalize.py
  25:  def _wire_anomaly_window(*, runtime: Any, config: "SystemConfig") -> bool:
  80:  def _wire_tiered_knowledge_loader(*, runtime: Any, config: "SystemConfig") -> int:
  107: def _wire_task_context(*, runtime: Any, config: "SystemConfig") -> int:
```

All evidence in the prompt's "Verified Against Codebase" footer matches HEAD exactly. No drift.

### Phantom-API Pre-Check

```text
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-487-self-distillation-v1.md
=== prompts/ad-487-self-distillation-v1.md ===
  Clean — no phantom symbols detected.

=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0
```

Symbol-existence pre-check stayed clean (as it did at pass-1). Method-shape blind spot from convention #19 — the pre-check still cannot validate that `runtime.llm_client.complete(request, priority=...)` matches `BaseLLMClient.complete`'s actual signature. The architect-time grep sweep above is the compensating control; AD-685b kwarg-shape extension remains the durable fix.

### New Findings

None.

### Convention #15 Tolerance Check

Pass-1 burned the wave's tolerance reservation (4 Required > 1 ⚠️ allowed). Pass-2 finds **0 Required, 0 ⚠️, 0 nits** — clean approval. No tolerance budget consumed at pass-2.

### Method-Shape Phantom Recurrence Counter

Wave 14 R1 (`LLMClient.chat` → `complete`) is the **4th recurrence** of the method-shape phantom pattern across Waves 9-14:

1. **Wave 9:** TrustNetwork phantom method
2. **Wave 10:** Procedure phantom method (and earlier in same wave: WorkItemStore.add)
3. **Wave 13:** WorkItemStore.add (additional reference site)
4. **Wave 14:** LLMClient.chat → complete

Convention #19 (method-kwarg phantom blind spot) and convention #16 (phantom-API pre-check) interact: pre-check validates symbol existence by name; it cannot validate that an asserted method actually exists on a class, nor that kwargs match the signature. AD-685b — extend `phantom-api-precheck.ps1` to AST-parse `<obj>.<method>(...)` calls and validate against the live class signature — has now been the architect's recommended hygiene-AD across 4 waves. **Strong forcing function**: AD-685b should be the next dispatched bug-fix-AD (or the head of Wave 15) — at 4 recurrences, the "watch and wait" posture has expired.

### Re-Review Verdict

**✅ Approved.** Single-commit Builder dispatch recommended.
