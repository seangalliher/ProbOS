# AD-1121 — Live cascade-confab divergence probe (detection)

**Layer:** COGNITIVE (probe) + router wiring (fan-out seam). **Default-OFF, additive.**
**Epic:** Cascade-Confabulation Prevention (`prompts/cascade-confab-prevention-ADs.md`) · issue **#1024**.
**Depends on:** AD-1119 (referent extraction + `GroundingVerdict`) and AD-1120 (central-referent selection at the fan-out seam). **Both landed.**
**Highest landed AD at drafting:** AD-1120. This is the next sequential top-level AD (**AD-1121**).

---

## Why

The `CASCADE_CONFAB` anti-pattern is coded in `emergence_taxonomy.py` (`BehaviorCode.CASCADE_CONFAB`, `is_anti_pattern=True`) but is only ever classified **post-hoc** — it never fires live. AD-1119 resolves referents against ship ground truth *deterministically*; AD-1120 steers the crew to the "unresolvable" close when a central referent is UNRESOLVED. AD-1121 adds the **detection** half: a SelfCheckGPT-style (arXiv 2303.08896) probabilistic **self-consistency probe** for the exact case the deterministic resolvers cannot settle — an UNRESOLVED central referent — so the crew's live confabulation is *flagged and counted in near-real-time* and the Captain is *notified*.

The load-bearing research property (CoVe arXiv 2309.11495, SelfCheckGPT): the probe must sample the LLM **independently and without the room context**. Independent context-free samples of "does `<X>` exist on this ship?" **converge** for a real referent and **fail to consistently affirm** for a fabricated one (the live `e77acec7` case). Shared poisoned context makes peer "verification" confirmatory (AD-506b can't fire — each message is novel); a context-free probe breaks that dependency.

### STEP-0 empirical finding — transcript persistence is DESCOPED

The epic's AD-1121 sketch bundled "persist room transcripts (verified in-RAM only, 0-byte WAL)." **That forensic claim was about `ward_room.db`, not the group-chat store.** Verified against HEAD:

- Group chat lives in **`ChatThreadStore`** (`src/probos/threads/__init__.py`), wired eagerly at `runtime.py` L461-463 with `db_path = self._data_dir / "chat_threads.db"` (a real on-disk file, **not** `:memory:`).
- `ChatThreadStore._connect()` opens `sqlite3.connect(str(self._db_path), isolation_level=None)` — **autocommit**. `create_thread` and `append_message` (L921) both `INSERT` under this autocommit connection → **every message is durably committed to disk immediately** (no WAL needed for durability; autocommit flushes to the main DB file per statement).
- `ProjectStore` shares the same DB file. The live API `GET /api/threads/{id}/messages` reads it back — the Captain empirically recovered a **2026-06-10** thread from the live store, a month after creation.
- `data/` shows `ward_room.db` + `ward_room.db-wal`/`-shm` (the in-RAM-ish store the forensic note meant); the group-chat DB is written under the running node's data dir.

**Conclusion:** group-chat transcripts are **already durably persisted**. Rebuilding persistence in AD-1121 would duplicate a shipped capability (DRY violation). **Transcript persistence is removed from AD-1121 scope.** AD-1121 = probe + detection only.

---

## Pinned Design Decisions

**DD-1121-1 (scope).** Transcript persistence DESCOPED (STEP-0). AD-1121 ships: (a) a context-free divergence probe, (b) a `CASCADE_CONFAB` count via the existing AD-454 taxonomy pipeline, (c) a Captain notification. Nothing writes or migrates transcripts.

**DD-1121-2 (probe is pure + runtime-free — DIP).** The probe logic lives in a NEW cognitive module `src/probos/cognitive/confab_probe.py`. `probe_referent(llm_client, token, ...)` takes the `llm_client` (injected, DIP — no hard runtime import) and the referent **token string only**. It has **no parameter through which the seed / transcript can reach it** — the context-free guarantee is enforced *by the function signature*, not by discipline. Mirrors the AD-1119 `referent_gate.py` pattern (pure cognitive module + thin router wiring).

**DD-1121-3 (context-free N-sample probe).** Module constants (zero-config, like `_FANOUT_HISTORY_LIMIT`): `_CONFAB_PROBE_SAMPLES = 3`, `_CONFAB_PROBE_TIER = "fast"`, `_CONFAB_PROBE_TEMPERATURE = 1.0` (high temp = genuinely independent draws — load-bearing for divergence), `_CONFAB_PROBE_MAX_TOKENS = 160`. Issue the N `complete()` calls concurrently via `asyncio.gather(*[...], return_exceptions=True)`. Each request's `prompt` contains **only the token** and a fixed instruction; `system_prompt` is a fixed minimal string. The seed text is **never** passed in.

**DD-1121-4 (divergence measure = existence-affirmation consistency).** Black-box (no logprobs). For each usable sample, `_classify_existence(text) -> "AFFIRM" | "NOT_AFFIRM"` via a fixed denial/uncertainty marker regex (`_CONFAB_DENIAL_RE`: `no record`, `does not exist`, `no such`, `not aware`, `cannot find`, `no ... named`, `not a real`, `fictional`, `unknown`, `no information`, `i (?:have|find) no`, `unable to (?:find|locate)`, `not (?:a )?(?:standard|known|valid)`). A sample **AFFIRMs** iff it has substantive content **and** does NOT match the denial regex. **Flag CASCADE_CONFAB iff** `affirm_rate < _CONFAB_AFFIRM_THRESHOLD` (`= 0.5`) **AND** `usable >= _CONFAB_MIN_USABLE_SAMPLES` (`= 2`). Rationale: a fabricated referent yields *either* consistent denials (affirm_rate → 0) *or* wildly divergent hallucinations that mostly fail to affirm a single real entity — both caught by low affirm-rate. A real referent yields consistent affirmations (affirm_rate → 1). *Pure token-overlap alone is wrong here: consistent denials have HIGH overlap → it would miss the dominant fabrication case.*

**DD-1121-5 (precision guard = the AD-1119 UNRESOLVED gate).** The probe runs **only** on a central referent AD-1119's ground-truth resolvers (git / agent / ward-room — which DO have ship state) already marked **UNRESOLVED**. A real referent the resolvers know → RESOLVED → never central → never probed. This bounds false positives; the residual risk (a real referent the resolvers miss *and* the base LLM doesn't know) is handled by DD-1121-7 — the output is a **Captain notification for human adjudication, never an auto-action**.

**DD-1121-6 (reuse the single AD-1119 verdict; central token computed once).** Extract a token-selector `_select_central_referent(verdict, seed_text) -> str | None` from the existing `_select_central_cue` (the async git-HEAD availability probe stays inside it, run **once**). `_observe_referent_grounding` computes `central_token` once and uses it for BOTH the AD-1121 probe AND the AD-1120 cue return. No second gate build, no second git-HEAD probe.

**DD-1121-7 (surface, don't act; best-effort, non-blocking).** On a divergence flag the probe (a) records a `CASCADE_CONFAB` observation via the AD-454 taxonomy pipeline (DD-1121-8) and (b) posts a Captain notification via `runtime.notification_queue.notify(..., notification_type="action_required", suggested_action=None)` — **no auto-terminate button, no room close**. The probe is scheduled as a **best-effort background task** (non-blocking) so it never delays the crew reply; the crew reply proceeds while the probe runs.

**DD-1121-8 (count via the existing taxonomy pipeline).** Add an additive public `EvidenceCollector.record_observation(...)` that builds an `EvidenceObservation(behavior_codes=(BehaviorCode.CASCADE_CONFAB,), ...)` and reuses the existing `_is_duplicate`/`_persist`/`_record_dedup` path (OBS-NNNN.yaml numbering + `(author_id, code)` dedup). `author_id = thread_id` → one CASCADE_CONFAB OBS per room per dedup window. Honest-degrade: `runtime.evidence_collector is None` (collector disabled — its default) → skip the OBS record; the notification still fires. This method is CALLED ONLY by AD-1121, so AD-454 stays byte-identical.

**DD-1121-9 (default-OFF byte-identical).** New third flag `config.grounding.confab_probe_enabled: bool = False`. When off: `_observe_referent_grounding` short-circuits before any probe work (and does not call `_select_central_referent` unless AD-1120's flag is on), no task is scheduled, `record_observation` is never called → the fan-out and AD-454 are byte-identical to HEAD.

**DD-1121-10 (honest-degrade → no false flag).** Every probe boundary is Tier-2 (log-and-degrade): an LLM exception per sample drops that sample; `< _CONFAB_MIN_USABLE_SAMPLES` usable → **abstain (no flag)**; a bad response, an empty batch, or any raise → no flag, no notification. A probe failure NEVER produces a false `CASCADE_CONFAB`.

---

## Build

### Section 1 — `src/probos/config.py` (GroundingConfig: add the third flag)

Anchor: `GroundingConfig` (~L6035), after `ground_before_collaborate_enabled` (the AD-1120 field). Add:

```python
    confab_probe_enabled: bool = Field(
        default=False,
        description=(
            "AD-1121: when True (and referent_gate_enabled is also True), run a "
            "context-free self-consistency divergence probe on an UNRESOLVED central "
            "room referent; on a divergence verdict, record a CASCADE_CONFAB "
            "observation and notify the Captain. Best-effort + non-blocking. Default "
            "OFF (byte-identical when off; no effect unless referent_gate_enabled is on)."
        ),
    )
```

Update the `GroundingConfig` class docstring with one AD-1121 sentence (mirror the AD-1120 sentence already there). No `SystemConfig` mount change (the `grounding` mount at ~L6082 already exists).

### Section 2 — NEW `src/probos/cognitive/confab_probe.py` (pure probe, runtime-free — DIP)

Module docstring: layer COGNITIVE, runtime-free (llm_client injected), context-free by construction, honest-degrade contract. Provide:

- Module constants: `_CONFAB_PROBE_SAMPLES = 3`, `_CONFAB_PROBE_TIER = "fast"`, `_CONFAB_PROBE_TEMPERATURE = 1.0`, `_CONFAB_PROBE_MAX_TOKENS = 160`, `_CONFAB_AFFIRM_THRESHOLD = 0.5`, `_CONFAB_MIN_USABLE_SAMPLES = 2`, `_CONFAB_DENIAL_RE` (compiled, `re.IGNORECASE`, the DD-1121-4 marker set), `_CONFAB_PROBE_SYSTEM_PROMPT` (fixed minimal string, Ship's-Computer voiced, **no** transcript slot).
- `@dataclass(frozen=True) class ProbeResult`: `token: str`, `usable: int`, `affirm: int`, `is_divergent: bool`, `samples: tuple[str, ...]` (the raw sample texts, for the OBS reasoning digest — bounded), plus an `affirm_rate` property. A non-divergent / abstained result has `is_divergent=False`.
- `def _classify_existence(text: str) -> str` — pure. `""`/whitespace → `"NOT_AFFIRM"`; matches `_CONFAB_DENIAL_RE` → `"NOT_AFFIRM"`; else `"AFFIRM"`. Full type annotations; no I/O.
- `async def probe_referent(llm_client: Any, token: str, *, samples: int = _CONFAB_PROBE_SAMPLES, tier: str = _CONFAB_PROBE_TIER, temperature: float = _CONFAB_PROBE_TEMPERATURE) -> ProbeResult`:
  - Build `prompt = f"Does an entity, component, service, or identifier named '{token}' exist on this ship? If it does, state briefly what it is. If you have no record of it, say so plainly."` — **token only, never a seed**.
  - `req = LLMRequest(prompt=prompt, system_prompt=_CONFAB_PROBE_SYSTEM_PROMPT, tier=tier, temperature=temperature, max_tokens=_CONFAB_PROBE_MAX_TOKENS)` (reuse the SAME `req` for all N draws — high temperature makes them independent).
  - `results = await asyncio.gather(*[llm_client.complete(req) for _ in range(samples)], return_exceptions=True)`.
  - For each result: skip exceptions (log debug) and empty `getattr(r, "content", None)`; collect usable texts.
  - `usable = len(texts)`; `affirm = sum(1 for t in texts if _classify_existence(t) == "AFFIRM")`.
  - `is_divergent = usable >= _CONFAB_MIN_USABLE_SAMPLES and (affirm / usable) < _CONFAB_AFFIRM_THRESHOLD`.
  - Wrap the whole body Tier-2: `llm_client is None`, any unexpected raise → return a non-divergent `ProbeResult` (logged). **Never raises, never a false divergent.**

### Section 3 — `src/probos/cognitive/evidence_collector.py` (additive public record method)

Add a public method on `EvidenceCollector` (place after `classify_post`, before the internal helpers). It reuses the existing dedup + `_persist` tail (DRY):

```python
async def record_observation(
    self,
    *,
    behavior_code: BehaviorCode,
    thread_id: str,
    author_id: str,
    author_callsign: str = "",
    reasoning: str = "",
    confidence: float = 1.0,
) -> EvidenceObservation | None:
    """AD-1121: persist a PRE-CLASSIFIED observation (bypasses the LLM classifier).

    For detectors that already know the code (e.g. the AD-1121 divergence probe).
    Reuses the dedup window + gapless OBS-NNNN numbering. Tier-2: returns None on
    dedup / persist failure; never raises.
    """
```

Body: `now = time.time()`; dedup via `self._is_duplicate(author_id=author_id, codes=(behavior_code,), now=now)` → None if dup; clamp/truncate `reasoning` to `self._max_reasoning_chars`; build `EvidenceObservation(obs_id="OBS-PENDING", timestamp=now, trial_id=self._trial_id, post_id=f"{thread_id}:{behavior_code.value}", thread_id=thread_id, author_id=author_id, author_callsign=author_callsign, behavior_codes=(behavior_code,), confidence=<clamped 0..1>, reasoning=reasoning, raw_response="")`; `persisted = await self._persist(obs)`; on success `self._record_dedup(author_id=author_id, codes=(behavior_code,), ts=now)`; return `persisted`. Wrap Tier-2.

### Section 4 — `src/probos/runtime.py` (best-effort task registry)

Add near the `_nats_publish_tasks` registry (~L1058, mirror the existing per-event-task set convention):

```python
        # AD-1121: best-effort background tasks for the cascade-confab divergence
        # probe (per-event, non-blocking; NOT _background_tasks — those are
        # runtime-lifetime loops). Public so the fan-out seam can register without
        # reaching into a private attr.
        self.confab_probe_tasks: set[asyncio.Task] = set()
```

### Section 5 — `src/probos/routers/thread_fanout.py` (seam wiring)

**5a. Imports (L37-42).** Add to the `from probos.cognitive.confab_probe import (...)` a NEW import line: `probe_referent`. Add `from probos.cognitive.emergence_taxonomy import BehaviorCode`. (`asyncio` already imported L19.)

**5b. Extract `_select_central_referent` from `_select_central_cue` (L1027).** New helper returns the **token** (not the cue):

```python
async def _select_central_referent(verdict: Any, seed_text: str) -> str | None:
    """AD-1120/AD-1121: the CENTRAL unresolved referent TOKEN, or None.

    The token-selection half of _select_central_cue (kind/stop-word filter +
    the ONE git-HEAD availability probe for hex). AD-1120 maps it to the cue;
    AD-1121 feeds it to the divergence probe. Tier-2 honest-degrade → None.
    """
```
Body = the current `_select_central_cue` body **but** the final loop `return verdict.cues.get(t)` becomes `return t`. Then either delete `_select_central_cue` and map token→cue at the call site, or keep `_select_central_cue` as a thin `token = await _select_central_referent(...); return verdict.cues.get(token) if token is not None else None`. **Recommended:** delete `_select_central_cue`; do the cue mapping inline in `_observe_referent_grounding` (5d) so the token is computed exactly once.

**5c. NEW wiring helper `_probe_cascade_confab`.**

```python
async def _probe_cascade_confab(runtime: Any, thread: Any, token: str) -> None:
    """AD-1121: context-free divergence probe on an UNRESOLVED central referent.

    Best-effort. On a divergence verdict: record a CASCADE_CONFAB observation
    (via the AD-454 collector, if wired) and notify the Captain (always). NEVER
    raises out (scheduled fire-and-forget); NEVER auto-acts on the room.
    """
```
Body (all Tier-2): `llm = getattr(runtime, "llm_client", None)`; if None → return. `result = await probe_referent(llm, token)`; if `not result.is_divergent` → return. Build a bounded `reasoning` digest (token, affirm/usable, a truncated join of `result.samples`). **Record:** `collector = getattr(runtime, "evidence_collector", None)`; if collector is not None → `await collector.record_observation(behavior_code=BehaviorCode.CASCADE_CONFAB, thread_id=getattr(thread,"id",""), author_id=getattr(thread,"id",""), author_callsign="confab-probe", reasoning=reasoning, confidence=round(1.0 - result.affirm_rate, 3))` (guarded). **Notify (always):** `nq = getattr(runtime, "notification_queue", None)`; if nq is not None → `nq.notify(agent_id="confab-probe", agent_type="utility", department="science", title=f"Possible confabulation cascade: '{token}'", detail=<Ship's-Computer-voiced review recommendation naming the room title + unresolved token + affirm/usable>, notification_type="action_required")` (guarded). Emit one structured INFO log.

**5d. Restructure the tail of `_observe_referent_grounding` (L1019-1024, just before the `_select_central_cue` def at L1027).** Keep the AD-1119 first-line early-return + observe loop VERBATIM. Replace the AD-1120 tail (`if not ground_before_collaborate_enabled: return None` / `return await _select_central_cue(...)`) with:

```python
    probe_on = getattr(cfg, "confab_probe_enabled", False)
    b2_on = getattr(cfg, "ground_before_collaborate_enabled", False)
    if not (probe_on or b2_on):
        return None  # G1-only: byte-identical to AD-1119/AD-1120 observe-only
    central_token = await _select_central_referent(verdict, seed_text or "")
    if probe_on and central_token is not None:
        try:
            task = asyncio.create_task(
                _probe_cascade_confab(runtime, thread, central_token)
            )
            runtime.confab_probe_tasks.add(task)
            task.add_done_callback(runtime.confab_probe_tasks.discard)
        except Exception:
            logger.warning(
                "AD-1121: failed to schedule confab probe for thread=%s token=%r; "
                "skipping (fan-out result unaffected)",
                getattr(thread, "id", "?"), central_token, exc_info=True,
            )
    if not b2_on:
        return None
    return verdict.cues.get(central_token) if central_token is not None else None
```

This preserves: AD-1119 (only `referent_gate_enabled` on → `not (probe_on or b2_on)` True → `return None`, no `_select_central_referent` call → the 3 landed AD-1119 call-site tests stay green + no extra git-HEAD probe); AD-1120 B2-on path (`_select_central_referent` + `verdict.cues.get(token)` == old `_select_central_cue` output).

### Section 6 — `tests/test_ad1121_confab_probe.py` (NEW)

Use **real fixtures** (BF-287): real `SystemConfig()`, real `NotificationQueue`, real `EvidenceCollector` (tmp `output_dir`), a **scripted-LLM stub** class (NOT MagicMock) — a small `_ScriptedLLM` with `async def complete(self, request, *, priority=...)` that pops queued `LLMResponse`-shaped objects and **records every `request`** it receives. Mirror the AD-1120 `_observe_referent_grounding` fixture shape (a light real-attr holder for `runtime` exposing `config`, `llm_client`, `notification_queue`, `evidence_collector`, `confab_probe_tasks`, `registry`, `callsign_registry`, `ward_room`).

Required cases:

1. **`test_probe_divergent_samples_flag_and_notify`** — `probe_referent` fed 3 denial samples ("No record of X on this ship." ×3) → `is_divergent True`, `affirm==0`. Through the seam (both flags on): after awaiting the scheduled task, a `CASCADE_CONFAB` OBS file exists in the collector dir AND the notification queue has one `action_required` notification naming the token.
2. **`test_probe_consistent_affirm_no_flag`** — 3 affirmative samples ("X is the ship's telemetry service." ×3) → `is_divergent False`; no OBS file, no notification.
3. **`test_probe_context_free_assertion`** — drive the probe with a distinctive seed (e.g. `"Investigate e77acec7; the SECRET_CANARY_TOKEN context must not leak."`); assert `"SECRET_CANARY_TOKEN"` (and the full seed) is **NOT** a substring of ANY prompt/`system_prompt` the `_ScriptedLLM` recorded. The context-free guarantee.
4. **`test_probe_failure_no_false_flag`** — `_ScriptedLLM.complete` raises for every sample (or `llm_client=None`) → `probe_referent` returns `is_divergent False`; no OBS, no notification. Also assert `< 2` usable samples → abstain (1 usable, 2 exceptions → no flag).
5. **`test_classify_existence`** — unit: denial strings → `NOT_AFFIRM`; affirmative descriptions → `AFFIRM`; `""`/whitespace → `NOT_AFFIRM`.
6. **`test_default_off_byte_identical`** — GOLDEN: `confab_probe_enabled=False` (and `ground_before_collaborate_enabled=False`) with `referent_gate_enabled=True` → `_observe_referent_grounding` returns `None`, schedules **zero** tasks (`runtime.confab_probe_tasks` empty), and the `_ScriptedLLM` received **zero** probe requests. Prove no probe work when off.
7. **`test_evidence_record_observation_dedup`** — two `record_observation(CASCADE_CONFAB, thread_id=T, author_id=T)` calls within the dedup window → exactly ONE OBS file (dedup reused). Real `EvidenceCollector`, tmp dir.
8. **`test_seam_non_blocking`** — with both flags on and a slow `_ScriptedLLM` (a sample that awaits an event), `_observe_referent_grounding` **returns the cue immediately** without awaiting the probe (assert a scheduled task is still pending, then release + await it).

Git-exercising selection paths (`_select_central_referent` for a `hex` token) reuse the AD-1120 hermeticity pattern (monkeypatch resolvers to a tmp git repo; `@_requires_git` where a real `git` is needed; or use an `entity`-kind central referent to avoid git entirely for the pure-probe tests).

### Section 7 — Trackers (additive; append-only)

- `PROGRESS.md`: prepend an AD-1121 block (mirror the AD-1120 top block shape) — the STEP-0 descope finding, the 3 default-OFF flags relationship, the probe design, the record + notify wiring, byte-identity guarantee.
- `DECISIONS.md`: new `### AD-1121: Live cascade-confab divergence probe (detection) (#1024)` entry (mirror the AD-1120 header format) — Context / Decision / Tests, and the explicit STEP-0 descope rationale.

---

## Acceptance

- `tests/test_ad1121_confab_probe.py` — all 8 cases pass (`-q -n 0`).
- Regression: the landed **AD-1119 (15)** and **AD-1120 (11)** suites stay green **unchanged** (this AD must not alter their outputs).
- Blast: the `thread_fanout` group-chat test files + `test_config.py` + `test_ad454_evidence_collector.py` — zero regressions.
- `get_errors` clean on every created/modified file.
- Default-OFF byte-identity proven by `test_default_off_byte_identical` (zero tasks scheduled, zero probe requests).
- Context-free property proven by `test_probe_context_free_assertion`.
- Honest-degrade proven by `test_probe_failure_no_false_flag`.
- Full type annotations on every new public symbol; structured logging with context at each Tier-2 boundary; boundary tests (happy + divergent + consistent + failure/abstain + empty).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- **No transcript persistence** — STEP-0 proved `ChatThreadStore` already persists durably (DRY). Do not touch `threads/__init__.py`, add a WAL, or migrate transcripts.
- **No room auto-termination / auto-close / archive-on-flag** — surface to the Captain ONLY (`notification_type="action_required"`, `suggested_action=None`). The divergence verdict is a *signal for human adjudication*, not a gate.
- **No notification re-architecture** — reuse `runtime.notification_queue.notify(...)` as-is. Do not add a new queue, event type, or the AD-1053 accept-intent path.
- **No new LLM tier** — reuse `tier="fast"`. Do not add to `_LLM_TIERS`.
- **No consensus / trust / Hebbian writes** — the probe records an OBS + a notification; it does not vote, score trust, or touch routing.
- **Do not wire the AD-567f `CASCADE_CONFABULATION_DETECTED` event or the counselor** — that is a separate subsystem (therapeutic DMs). AD-1121 counts via the AD-454 taxonomy pipeline only.
- **Do not touch `EmergentDetector`, `referent_gate.py`, or `emergence_taxonomy.py`** (consume `BehaviorCode.CASCADE_CONFAB`; do not edit it).
- **Do not change** `_observe_referent_grounding`'s AD-1119 first-line early-return or observe loop, or the AD-1120 B2 cue output.
- **Do not run the probe inline (blocking)** — schedule it as a best-effort background task (DD-1121-7).
- **Do not build AD-1122+ / anything beyond #1024.** Leave the work UNCOMMITTED for the Captain to review.

---

## Files

| File | Change |
|---|---|
| `src/probos/config.py` | `GroundingConfig.confab_probe_enabled: bool = False` (+ docstring line) |
| `src/probos/cognitive/confab_probe.py` | **NEW** — pure probe (`ProbeResult`, `_classify_existence`, `probe_referent`), runtime-free (DIP) |
| `src/probos/cognitive/evidence_collector.py` | additive public `record_observation(...)` (reuses dedup + `_persist`) |
| `src/probos/runtime.py` | `self.confab_probe_tasks: set[asyncio.Task] = set()` in `__init__` |
| `src/probos/routers/thread_fanout.py` | imports; extract `_select_central_referent`; NEW `_probe_cascade_confab`; restructure `_observe_referent_grounding` tail |
| `tests/test_ad1121_confab_probe.py` | **NEW** — 8 cases |
| `PROGRESS.md`, `DECISIONS.md` | additive AD-1121 blocks |

---

## Done when

- 8 new tests green; AD-1119 (15) + AD-1120 (11) green unchanged; blast zero regressions; `get_errors` clean.
- `confab_probe_enabled=False` (default) → fan-out + AD-454 byte-identical to HEAD (golden proven).
- A divergent probe → one `CASCADE_CONFAB` OBS (when the collector is wired) + one Captain `action_required` notification; a consistent probe → neither; a probe failure → neither.
- The probe never receives the seed/transcript (context-free test) and never blocks the crew reply (non-blocking test).
- Trackers updated additively (append-only; no deletions). Work left UNCOMMITTED.

---

## Verified Against Codebase (2026-07-09)

```
# STEP-0: chat_threads.db is durably persisted (autocommit, on-disk)
src/probos/threads/__init__.py:  _connect -> sqlite3.connect(str(self._db_path), isolation_level=None)  # autocommit
src/probos/threads/__init__.py:921  def append_message(...)  ->  INSERT INTO chat_thread_messages ... (under autocommit)
src/probos/runtime.py:462  self.chat_thread_store = ChatThreadStore(db_path=self._data_dir / "chat_threads.db")  # real file
data/ listing: ward_room.db(+wal/shm) present  ->  the "in-RAM/0-byte-WAL" forensic note was ward_room, NOT chat_threads

# Fan-out seam (AD-1119/AD-1120)
src/probos/routers/thread_fanout.py:964   async def _observe_referent_grounding(runtime, thread, seed_text) -> str | None
src/probos/routers/thread_fanout.py:1027  async def _select_central_cue(verdict, seed_text) -> str | None   # async git-HEAD probe inside
src/probos/routers/thread_fanout.py:1119  grounding_cue = await _observe_referent_grounding(runtime, thread, captain_body)  # ONE caller
src/probos/routers/thread_fanout.py:37-42 from probos.cognitive.referent_gate import (GitObjectResolver, ReferentGroundingGate, build_default_resolvers, extract_referents)
src/probos/routers/thread_fanout.py:87  _GROUNDING_INJECT_KINDS = frozenset({"hex", "entity"})
tests/test_ad1120_ground_before_collaborate.py: calls ONLY _observe_referent_grounding (not _select_central_cue)  -> safe to extract token-selector

# LLM client + request
src/probos/cognitive/llm_client.py:551  async def complete(self, request: LLMRequest, *, priority=Priority.NORMAL) -> LLMResponse
src/probos/cognitive/llm_client.py:33   _LLM_TIERS = ("fast", "standard", "deep", "vision", ...)   # "fast" valid
src/probos/types.py:233  class LLMRequest: prompt / system_prompt="" / tier="standard" / temperature=0.0 / max_tokens=2048
src/probos/cognitive/evidence_collector.py:318  content = getattr(response, "content", None)  # response shape

# Taxonomy count + collector
src/probos/cognitive/emergence_taxonomy.py:  BehaviorCode.CASCADE_CONFAB = "CASCADE-CONFAB" (is_anti_pattern=True); public: get_entry/all_codes/anti_pattern_codes/as_classifier_prompt (NO counter)
src/probos/cognitive/evidence_collector.py:455  async def _persist(obs) -> EvidenceObservation | None  # OBS-NNNN numbering under lock
src/probos/cognitive/evidence_collector.py:397/413  _is_duplicate / _record_dedup keyed (author_id, code)
src/probos/startup/finalize.py:640  runtime.evidence_collector = collector  # default-disabled; needs ward_room + llm_client

# Notification + task registry
src/probos/notifications.py:69  def notify(agent_id, agent_type, department, title, detail="", notification_type="info", action_url="", suggested_action=None) -> AgentNotification  # SYNC
src/probos/runtime.py:1049  self.notification_queue = NotificationQueue(on_event=self._emit_event)
src/probos/runtime.py:1058  # _nats_publish_tasks per-event registry (create_task + set.add + add_done_callback(discard)) — the pattern to mirror
src/probos/runtime.py:2624  _spawn_background_task -> "Use ONLY for loops that live for the runtime's lifetime" (NOT for per-event probe)

# Config + numbering
src/probos/config.py:6035  class GroundingConfig  (referent_gate_enabled, ground_before_collaborate_enabled)
src/probos/config.py:6082  grounding: GroundingConfig = Field(default_factory=GroundingConfig)  # mount exists
DECISIONS.md:13  ### AD-1120: ... (#1023)   |  PROGRESS.md line 3: "AD-1120 shipped"   -> highest landed AD-1120; AD-1121 next; #1024 OPEN (pre-assigned)
```
