# Review: AD-607 v1 — Memory Security write-path scrubber + per-source rate limit
**Verdict:** ✅ Approved
**Narrow scope (write-path only); read-path defenses correctly deferred to AD-693. Two Recommended sharpenings around regex false positives and the cognitive-services init site.**

## Required (must fix before building)
_None._

## Recommended
1. **`r"(?i)\bact\s+as\s+(if\s+you\s+(are|were)|a)\b"` will false-positive on legitimate inputs** like "act as a witness", "act as if you were the user", or any roleplay-style legitimate request. Memory poisoning is the threat; the regex is the gate. Recommend: (a) tighten the pattern to require an injection-style suffix (e.g. `\bact\s+as\s+(an?\s+)?(unrestricted|jailbroken|developer mode)\b`), (b) document the false-positive rate as acceptable since rejection only logs and skips storage (the user's request still executes), or (c) add a Non-Goal acknowledging "v1 patterns are conservative and may reject legitimate-but-novel content; tune via `inject_signature_patterns` config." Pick one — the current spec is silent on the tradeoff.
2. **D5 hand-waves the cognitive-services init site** ("`init_cognitive_services()` (or whichever current site builds `EpisodicMemory` — Builder verifies the canonical site)"). Same architect-responsibility argument as AD-700a Required #1: grep `init_cognitive_services` (or wherever `EpisodicMemory(...)` is constructed today) and cite the file:line in D5. Three minutes of architect grep saves a Builder iteration.

## Nits
1. The `attach_security_config` method is a setter pattern — preferable to constructor injection here since `EpisodicMemory.__init__` already has many parameters and AD-607 is opt-in. Good call.
2. Test #5's "advance monotonic clock past window via `time.monotonic` patch (or `cfg.per_source_window_seconds=0.01` + `await asyncio.sleep(0.02)`)" — the `sleep` form is more deterministic on Windows where `time.monotonic` patching has historically been flaky in this repo. Recommend the prompt pin one form.
2. The `_per_source_rate` dict grows unboundedly in `agent_ids[0]` (one entry per source-id ever seen). For a long-running runtime, this could leak. Bounded LRU or periodic prune would be safer. Defer to AD-693 with a Non-Goal note.
3. `MemorySource` is mentioned in Non-Goals — verify it exists; if not, drop the line.
4. The malformed-pattern test (#8) exercises the `_compile_injection_patterns` warning path — good.

## Verified
- ✅ `EpisodicMemory.store()` at `episodic.py:942`, `_storage_gate` at `:948`, `_is_rate_limited` at `:1382`, BF-039 dedup precedent — all grep-confirmed.
- ✅ `Episode.user_input: str` and `Episode.agent_ids: list[str]` — AD-607 keys on `agent_ids[0]` for source-id, distinct from BF-039's per-agent throttle.
- ✅ `MemorySecurityConfig` is greenfield — no collisions in `config.py`.
- ✅ Two-gate ordering (scrubber before rate limiter, both before BF-039) prevents rate-limit-state pollution from rejected-injection inputs.
- ✅ Tier-2 log-and-degrade in D5 matches the project convention.
- ✅ 8 tests cover boundary cases (clean pass, injection reject, disabled signatures, rate cap, window reset, distinct sources, fully disabled, malformed regex).

## Risk
MEDIUM. Security-tier write-path mod with regex-based gating. The default-True pattern set is the highest risk for false positives — Recommended #1 should be addressed before merging. Otherwise the design is sound and the deferral to AD-693 is correctly scoped.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — init site pinned to `__main__.py:316`; conservative-pattern false-positive Non-Goal added. (Highest-risk prompt; tolerance budget unused.)

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed (option c)**: Conservative-pattern false-positive Non-Goal at line 204 documents `\bact\s+as\s+(if\s+you\s+(are|were)|a)\b` will FP on "act as a witness"; rejection is **non-blocking** (request executes; only episode storage skipped); operators tune via `inject_signature_patterns` config; tightening deferred to AD-693.
- **Recommended #2 landed**: EpisodicMemory construction site pinned to `src/probos/__main__.py:316`. Insertion point exact: after construction block ending `:325`, before `runtime = ProbOSRuntime(...)` at `:328`.
- `MemorySecurityConfig` defaults sensible (boots zero-config); validators enforce `per_source_window_seconds > 0`, `per_source_max_episodes >= 1`.
- D2 `_compile_injection_patterns` is log-and-degrade on malformed regex (tier-2).
- D3 per-source rate limiter uses `time.monotonic()`, sliding window keyed on `episode.agent_ids[0]`. Distinct purpose from BF-039.
- D4 inserts gates BEFORE existing AD-610 `_storage_gate` at `:976`.
- D5 wiring tier-2 (try/except WARNING).
- 8 tests cover injection, clean pass-through, disabled gates, rate cap, window reset, distinct sources, fully-disabled, malformed-pattern resilience.
- Phantom-API sweep: `Episode.user_input`, `EpisodicMemory.store()` confirmed at HEAD.
