# Review: AD-454 — EvidenceCollector (v1)

**Prompt:** `prompts/ad-454-evidence-collector-v1.md`
**Pass:** 1
**Date:** 2026-05-08
**Verdict:** ⚠️ **Conditional** — 1 Required, 3 Recommended
**Headline:** Verify-first findings clean, race handling specified, AD-numbering rule wired; one exception-tier flaw in the listener context must be fixed before Builder dispatch.

## Required (must fix before building)

1. **Tier-3 propagation inside an `add_event_listener` handler is silently swallowed.**
   D1 says:
   > Tier-3 propagate ONLY for: programming errors inside `_persist` that indicate a bug (e.g. trial dir doesn't exist after `mkdir(parents=True, exist_ok=True)` — that's filesystem-broken, surface).

   `add_event_listener` dispatches async handlers via `asyncio.create_task(fn(event))` (verified `runtime.py:917`). The created task's reference is **not stored anywhere** by the runtime — any unhandled exception inside `on_ward_room_post` becomes a silent fire-and-forget task error. So a tier-3 `raise` from `_persist` does NOT actually propagate to a visible surface; it disappears into the asyncio garbage-collector warning stream.

   This is precisely the anti-pattern called out in `.github/copilot-instructions.md` ("Async Discipline: fire-and-forget tasks silently swallow exceptions"). For research telemetry that is opt-in and non-critical, the correct policy is **100% tier-2 (log-and-degrade)** at the `on_ward_room_post` boundary. A programming bug should surface via `logger.exception(..., post_id=..., trial_id=...)` and a `return None` — never a `raise` from inside the listener.

   **Fix:** Reword D1's exception-tier paragraph to:
   > **All exception paths inside `on_ward_room_post`, `classify_post`, `_parse_llm_response`, and `_persist` are tier-2 (log-and-degrade).** Use `logger.exception(...)` with full context (post_id, trial_id, error class) for unexpected errors; use `logger.warning(...)` with context for expected failures (LLM timeout, malformed JSON, OSError). Never `raise` out of these methods — `add_event_listener` dispatches via `asyncio.create_task` without storing the task ref, so any propagated exception is silently lost. The listener boundary owns the swallow.

   This is the highest-risk defect in the prompt. Build with the current wording would produce silently-failing observations under any real bug (filesystem, dedup-state corruption, etc.).

## Recommended

1. **`ward_room.get_post` and `get_thread` are async — make awaits explicit.** D1 narrative says "fetches post body via `runtime.ward_room.get_post(post_id)`" without an `await`. Both methods are async (verified `ward_room/messages.py:441`, `ward_room/service.py:406`, `ward_room/threads.py:688`). The class API stub correctly types `classify_post` as async, but the prose and one internal-method stub omit `await`. Add `await` literally in the docstring/prose so the Builder doesn't introduce a sync-call regression that returns an unawaited coroutine.

2. **`runtime.evidence_collector` attribute is created via assignment in finalize.** D3 sets `runtime.evidence_collector = collector` without a class-level declaration on `ProbOSRuntime`. This is consistent with several other peer subsystems (per the comment "Wave 5 convention #1") but the runtime class does not declare or annotate the attribute. Recommend either (a) adding `evidence_collector: Any | None = None` as a class attribute on `ProbOSRuntime` in a follow-up, or (b) explicitly stating in this prompt: *"This AD does NOT add a class-level annotation on `ProbOSRuntime`; the attribute is set by finalize and read defensively via `getattr(runtime, 'evidence_collector', None)` everywhere except inside the collector itself."* Pick (b) for this AD — it's the lowest-touch path.

3. **Test #7 (concurrency) should explicitly call `on_ward_room_post` directly, not exercise `add_event_listener` dispatch.** The current wording says "fire `N=10` post events concurrently (via `asyncio.gather`)". Make explicit: the test invokes `asyncio.gather(*[collector.on_ward_room_post(evt) for evt in events])` to test the lock under concurrent classification, NOT to test the runtime's dispatcher. This avoids a brittle dependency on dispatch ordering and isolates the lock guarantee.

## Nits

- **D1 dedup rule for anti-patterns** ("CASCADE-CONFAB is per-author too") is correct but worth one extra sentence: a true cascade by definition produces multiple per-author OBS files (one per agent in the cascade), each independently classifying the same anti-pattern. That's the intended signal — it's the across-author count that detects the cascade. Already implied by test #4 + #5 but a one-liner in D1 prevents Builder from "fixing" what isn't broken.
- **`_parse_llm_response` returns `tuple[list[BehaviorCode], float, str]`** but `EvidenceObservation.behavior_codes` is `tuple[BehaviorCode, ...]`. The boundary conversion (list → tuple) is implied. No code change needed; nit only.
- **YAML `raw_response` block** uses `|` literal style — fine for typical LLM JSON, but the Builder should verify multi-line responses don't break YAML parse. `yaml.safe_dump(..., sort_keys=False)` will pick the right scalar style automatically. No flag.

## Verified

- **`EventType.WARD_ROOM_POST_CREATED`** — `src/probos/events.py:68`. Confirmed.
- **Payload omits body** — emit site at `src/probos/ward_room/messages.py:238` payload keys are `post_id, thread_id, author_id, parent_id, author_callsign, mentions`. Collector must fetch body via `get_post`. Verify-first finding #2 already addresses this.
- **`runtime.ward_room.get_post(post_id)`** — async at `ward_room/messages.py:441` and `ward_room/service.py:406`. Public API ✅.
- **`runtime.ward_room.get_thread(thread_id, *, post_limit=N)`** — async at `ward_room/threads.py:688`. Signature matches collector spec exactly (keyword-only `post_limit`).
- **`runtime.add_event_listener`** — `runtime.py:791`. Dispatch uses `iscoroutinefunction` (line 916) and `asyncio.create_task` (line 917) — async handler supported.
- **`runtime.emit_event`** — `runtime.py:924`. Public, stable.
- **`LLMRequest(... tier="fast")`** — `types.py:227` class, line 232 `tier: str = "standard"`. String field, "fast" is valid (Wave 5 AD-700c precedent).
- **`pyyaml>=6.0`** — `pyproject.toml:26`. Already a dependency; `yaml.safe_dump` is available.
- **No `tier == "infrastructure"`** on any `BaseAgent` subclass — verified by grep across `src/probos/agents/` and `src/probos/cognitive/`. Canonical passive-observer tier is `"utility"` (precedents: `IntrospectionAgent`, `SystemQAAgent`, `FederationRecallAgent`). Verify-first finding #1 wired correctly into the prompt body and the dataclass declaration.
- **AD-numbering hard rule** — highest live AD = `AD-717` (verified by `Select-String` across `PROGRESS.md`, `DECISIONS.md`, `decisions-era-*.md`, `roadmap.md`). AD-454 has zero collisions in any era or tracker file. Reuse safe. Builder is instructed to re-grep at commit time per Acceptance + Verify-first finding #3.
- **Output sink** — `data/research/emergence-evidence/<trial-id>/OBS-NNNN.yaml`. Wired in D2 (`output_dir` config default) and D1 (`_persist` doc).
- **`asyncio.Lock` + startup directory scan** — `_persist` docstring specifies the lock; D1 says "On startup, the collector scans the trial directory and resumes from `max + 1`". Race specified.
- **Default-False on `enabled`** — `EmergenceCollectorConfig.enabled: bool = False`. Wave 10 convention #14 satisfied.
- **Working-tree integrity pre-flight bullet** present in Acceptance.
- **Listener registration uses `EventType.X.value`** — matches finalize.py:2377 reference pattern.
- **No env-var override on config** — explicit, prevents accidental trial activation.
- **Listener registration owned by finalize, not collector constructor** — clean separation.

---

*Re-review trigger: revision pass that addresses the Required tier-3 fix. The 3 Recommended items can be folded into the same revision or deferred to v2 — no further pass-1 work needed once the listener exception policy is uniform tier-2.*
