# Review: AD-725 — Targeted sub-intent dispatch on DM one-shot path

**Verdict:** ⚠️ Conditional
**Highest-risk prompt in the wave. The four-contract firewall (one-lookup, read-only, timeout, no-broadcast) is well-articulated. Classifier-as-Protocol is the right shape. One real attribute-name bug + a few hardening recommendations.**

## Required (must fix before building)
1. **`runtime.oracle_service` does not exist as a public attribute.** Live code at `src/probos/runtime.py:1536-1537`:
   ```
   self._oracle_service = cog.oracle_service  # AD-462e (private)
   self.oracle = cog.oracle_service           # AD-686 (public alias)
   ```
   `getattr(runtime, "oracle_service", None)` → `None`. The defensive `hasattr` guard in `_dispatch` prevents a crash, but the **entire oracle branch silently no-ops** — the largest classifier pattern set (`_ORACLE_PATTERNS`: "time", "date", "today", "what time is it") becomes dead. Substitute `runtime.oracle` for `runtime.oracle_service` in Section 2's `_dispatch` AND update the Builder-verification footnote to point at AD-686. The "Builder MUST verify" note does hedge this, but a wrong default that silently degrades a whole branch is worse than a wrong default that crashes — make the prompt ship the right name.

## Recommended
1. **Cache strategy: the prompt does not implement one and the user's review note asked about `(text_hash, agent_id)` invalidation.** Decision needed in the AD: **explicit "no cache in v1"** is defensible because the timeout cap (500ms) + default-OFF gating bound the worst-case latency cost, and the classifier itself is regex (sub-millisecond). Document the no-cache choice in the DECISIONS entry with a forward marker (AD-725-5) for `(text_hash, agent_id) -> TargetedLookupResult` LRU once embedding routing lands.
2. **Section 3 message-text prepend** at `agent_chat` doesn't specify the exact line where `message_text` is finalized into the IntentMessage. Builder is told to "verify the exact location ... insert the prepend BEFORE that finalization." For a hot-path edit, pin the line. From `routers/agents.py:875` (the function start), the IntentMessage construction is downstream — Builder should grep `IntentMessage(intent="direct_message"` within the function body. Worth one explicit anchor line in the prompt.
3. **`_dispatch` defensive `hasattr(em, "recall_for_agent")` etc.** is good Tier-2 hygiene, but silent no-op on a wrong name eats the whole feature. Add an INFO-level log on the no-method path (`logger.info("AD-725: %s lookup unavailable on runtime (no %s.%s)", ...)`) so the operator sees one line at startup-equivalent (first DM that classifies to that lookup) instead of guessing why the feature is dead. Per review-criteria §10 ("guard clause log levels: silent failure of an enabled feature is a diagnostic trap").
4. **Episodic `recall_for_agent` returns `list[Episode]`** (verified at `episodic.py:1900`). `LookupDispatcher._stringify` handles `list/tuple` of dicts and `str` but not domain dataclasses — `Episode` instances would fall through to the `repr()` else branch, dumping `Episode(text='...', score=0.42, agent_id='...', ...)` into the prompt. The Builder should either (a) extend `_stringify` with an explicit `Episode` branch that emits just `f"- {ep.text}"` per row, or (b) the `_dispatch` episodic path should adapt the list to `[ep.text for ep in res]` before returning. Either is fine; pick one.

## Nits
1. The `LookupType = Literal["oracle", "episodic", "codebase", "knowledge", "none"]` discriminator includes `"none"` as a value-typed sentinel — works fine but `lookup_type: LookupType` on `TargetedLookupResult` will never be `"none"` at runtime (the dispatcher returns `None` instead). The Literal is slightly overbroad for the result dataclass; consider a narrower `ActiveLookupType = Literal["oracle", "episodic", "codebase", "knowledge"]` for the result. Cosmetic.
2. `_EPISODIC_PATTERNS` regex `\bdid (we|you|i) (talk|discuss|mention)\b` is solid; consider adding `\bwhen did we\b` for temporal queries. Not blocking.

## Verified
- `agent_chat` at `routers/agents.py:875` — anchor confirmed.
- `_build_user_message` at `cognitive_agent.py:5893` — confirmed.
- `DM_ONESHOT = "dm_oneshot"` at `cognitive_agent.py:80` — confirmed; also referenced in SensoriumPath at line 236.
- `EpisodicMemory.recall_for_agent(self, agent_id: str, query: str, k: int = 5)` at `cognitive/episodic.py:1900` — signature confirmed; prompt's `k=3` call matches. (Architect's earlier phantom-API fix from `limit=` to `k=` did land — no regression.)
- `runtime.episodic_memory: EpisodicMemory | None` at `runtime.py:490` — public attribute, `getattr` is safe (handles None).
- `runtime.codebase_index: CodebaseIndex | None` at `runtime.py:1469` — public attribute.
- `runtime.records_store` property at `runtime.py:1131`; `RecordsStore.search(self, query, scope="ship")` at `records_store.py:819` — confirmed; `await` required (it is `async def`); the `asyncio.iscoroutine(res)` branch in `_dispatch` handles this correctly.
- Four-contract firewall (test #10): test asserts zero side effects on trust / intent_bus / Hebbian / consensus stubs — correctly enforces the read-only contract.
- Hard timeout via `asyncio.wait_for(..., timeout=self._cfg.timeout_ms / 1000.0)` — correct shape; the lookup task is NOT cancelled-and-awaited cleanly if it ignores cancellation, but stdlib `wait_for` raises and the calling code returns `None` — Tier-2 honored.
- Default `enabled=False` — Captain explicitly opts in. Correct per the "MED risk" classification.
- License: stdlib only (`re`, `asyncio`, `dataclasses`, `typing.Protocol`). No new pip / npm.
- No UI changes — AD-738b UI gate not triggered.
- No `asyncio.create_subprocess_*` in this prompt — BF-280 standing rule not at risk.
- AD-731 invariant N/A (no attachment payloads).
- Test plan: 10 boundary tests including the explicit four-contract firewall verification (#10). Comprehensive.

---

**Re-review:** _(blocked on oracle_service → oracle substitution + Episode `_stringify` decision)_

### Re-review (pass-2, 2026-05-14)

**Verdict:** ✅ Approved.

**Required #1 (`runtime.oracle_service` does not exist) — RESOLVED.** Global rename `runtime.oracle_service` → `runtime.oracle` landed throughout the prompt. Live-verified against `src/probos/cognitive/oracle_service.py`:

```
async def query(
    self,
    query_text: str,
    *,
    agent_id: str = "",
    intent_type: str = "",
    k_per_tier: int = 5,
    tiers: list[str] | None = None,
    caller_sovereign_id: str = "",
    access_policy: Any = None,
) -> list[OracleResult]:
```

at line 285. Matches the prompt's Builder-verification footnote at Section 2 line 347 exactly: `runtime.oracle.query(query_text, *, agent_id="", intent_type="", k_per_tier=5, tiers=None, ...) -> list[OracleResult]`. The AD-686 public alias `self.oracle = cog.oracle_service` at `runtime.py:1537` is cited correctly in the verify-first footer. Grep of the prompt file shows zero remaining `runtime.oracle_service` references; every site uses `runtime.oracle` with an AD-686 citation in-line (Solution Overview #4, Files-to-Modify, `_dispatch` source, log message, test plan `_FakeRuntime`, verification footnote).

No new Required findings. Recommended/Nits from pass 1 unchanged.
