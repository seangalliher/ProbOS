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
