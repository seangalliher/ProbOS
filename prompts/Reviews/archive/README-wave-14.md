# Wave 14 — Review Pass 1 Sweep Summary

**Date:** 2026-05-03
**Reviewer:** Architect (pass 1)
**Tolerance:** relaxed (1 ⚠️ allowed per convention #15)

---

## Verdicts

| AD | Title | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| AD-487 | Self-Distillation v1 — Personal Ontology Map Step | ❌ Not Ready | 4 | 4 | 3 |

**Total:** 4 Required, 4 Recommended, 3 Nits across 1 prompt. **Convergence: 0/1.**

---

## Top Failure Modes

1. **Method-shape phantom (R1).** Prompt asserts `LLMClient.chat()` — actual API is `LLMClient.complete(request: LLMRequest, *, priority=...) -> LLMResponse`. 3rd recurrence of method-shape phantoms across Waves 9-14 (TrustNetwork → Procedure → WorkItemStore.add → LLMClient.chat). AD-685 kwarg pre-check (convention #16) ran clean because it validates symbol existence, not method-call shapes. **Hygiene-AD candidate**: extend `scripts/phantom-api-precheck.ps1` to AST-parse `<obj>.<method>(...)` calls and validate against the live class signature. Already noted as candidate in DECISIONS.md convention #19/#21 — Wave 14 makes it the 3rd time the same blind spot has bitten.
2. **Phantom top-level config class (R2).** Section 4 says `Config.self_distillation`. Actual top-level class is `SystemConfig` (config.py:1805). Same class as finalize.py phase functions consume. Verify-first slip.
3. **Constructor missing the canonical `connection_factory` parameter (R3).** Wave 5 convention #2 (stdlib-only persistence) requires constructor injection. 8 existing peers (`assignment.py`, `trust.py`, `identity.py`, `acm.py`, `counselor.py`, `skill_framework.py`, `persistent_tasks.py`, `clearance_grants.py`) all share the same shape. AD-487's `__init__` omits it AND mistypes `_db: ConnectionFactory` (should be `DatabaseConnection`). Convention drift, not a phantom.
4. **Verify-first deferred to Builder (R4).** Prompt's "Verified Against Codebase" footer says `(Builder verifies ...)` for three of three checks. The standing order makes this the architect's job. Running the three greps at review time produced R1, R2, R3 directly.

---

## Verified-Pass Highlights

- **Pre-deferral honesty:** v1 scope is clean. No Collapse/Reduce/Daydream/DID-portability smuggled in.
- **AD-636/637f orthogonality:** confirmed by reading shipped code (llm_client.py:166, 427-457). LLM concurrency lanes throttle per tier; AD-487 throttles per (agent, domain, 24h). Different layers; no integration needed for v1.
- **Schema isolation:** `agent_probes` table absent in `src/`. Both new EventTypes (`ONTOLOGY_PROBE_RECORDED`, `ONTOLOGY_PROBE_RATE_LIMITED`) collision-free.
- **ConnectionFactory protocol** exists at protocols.py:223 with the async `connect → DatabaseConnection` shape AD-487 needs.
- **15-test plan** covers happy/error/boundary axes per testing discipline.

---

## LLMClient Signature Verification (architect pass)

```text
src/probos/cognitive/llm_client.py:22   class BaseLLMClient(ABC)
src/probos/cognitive/llm_client.py:26     async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse
src/probos/cognitive/llm_client.py:420   class OpenAICompatibleClient.complete(...)
src/probos/cognitive/llm_client.py:1060  class MockLLMClient.complete(...)
```

`LLMRequest` (types.py:227): `prompt, system_prompt, tier, temperature, top_p, max_tokens, id`. `LLMResponse` (types.py:240): `content, model, tier, tokens_used, prompt_tokens, completion_tokens, cached, error, request_id`.

**No `chat()` method exists in any LLM client class.** AD-487 must use `complete()`.

---

## AD-636 / AD-637f Orthogonality Assessment

- **AD-636** (LLM Priority Scheduling): per-priority semaphores limiting concurrent LLM requests by tier. Implementation in `llm_client.py:166-457` and `cognitive/sub_task.py:190-270`. Throttles **request concurrency**.
- **AD-637f** (Priority Model): unified Priority enum (CRITICAL/NORMAL/LOW), referenced at `cognitive_agent.py:1625` and inside `complete()`. Tags **request urgency**.
- **AD-487** rate limit: per-(agent, domain, 24h) probe count, enforced in `_check_rate_limit`. Throttles **probe frequency at the prober layer**.

These are independent throttles at different layers. No integration required for v1; the prober's rate-limit operates above the LLM client and benefits from AD-636 transparently.

**Recommendation:** add a one-line "Why this is orthogonal to AD-636/637f" sentence to the DECISIONS.md entry on revision so the precedent is captured for future LLM-coupled prompts.

---

## ConnectionFactory Protocol Verification

```text
src/probos/protocols.py:186  class DatabaseConnection(Protocol):
                              async def execute(self, sql, parameters=...) -> Any
                              async def executemany(self, sql, parameters) -> Any
                              async def executescript(self, sql_script) -> None
                              async def fetchone() -> Any
                              async def fetchall() -> Any
                              async def commit() -> None
                              async def close() -> None
src/probos/protocols.py:223  class ConnectionFactory(Protocol):
                              async def connect(self, db_path: str) -> DatabaseConnection
src/probos/storage/sqlite_factory.py:10  class SQLiteConnectionFactory  (default impl)
```

**Note:** the `DatabaseConnection` protocol does NOT expose a `.cursor()` method. The Wave 14 dispatch's "cursor pattern" phrasing is loose — the actual idiom is `await conn.execute(sql, params)` followed by `await conn.fetchone() / fetchall()`. AD-487's `_persist` and `_check_rate_limit` bodies (currently unspecified — Rec2) must use `execute → fetchone` directly, not a cursor.

Canonical lifecycle (`assignment.py:96-108`):

```python
async def start(self):
    self._db = await self._connection_factory.connect(self.db_path)
    await self._db.execute("PRAGMA foreign_keys = ON")
    await self._db.executescript(_SCHEMA)
    await self._db.commit()

async def stop(self):
    if self._db:
        await self._db.close()
        self._db = None
```

AD-487 should adopt this verbatim.

---

## Hygiene-AD Candidates Surfaced

1. **Extend `phantom-api-precheck.ps1` to validate method-call shapes.** 3rd recurrence of the same blind-spot class (DECISIONS.md convention #19, #21). The script currently checks `<Class>.<method>` exists by name; it does NOT parse `<instance>.<method>(<kwargs>)` calls and match against the target class's AST. Wave 14's R1 would have been caught at dispatch time if the script did. Recommend filing as `AD-Tooling-NN` after Wave 14 lands.

---

## Next Steps

- Architect (Stage 2 — Revision): apply R1-R4, fold Rec1-Rec4, judgment-call N1-N3, re-run pre-check, append `## Revision (2026-05-03)` to AD-487 prompt body. Single commit `Wave 14 revision: apply review findings to AD-487`. Push.
- Architect (Stage 3 — Review Pass 2): append `## Second-Pass Review (2026-05-03)` to this review file; sweep at `prompts/Reviews/README-wave-14-pass-2.md`. Convergence target: 1 ✅.
