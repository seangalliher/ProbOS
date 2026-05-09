# Review: RESEARCH — LoCoMo Benchmark Harness Stub
**Verdict:** ⚠️ Conditional
**`EpisodicMemory.store` signature in D2 is wrong; verify-first caveat is present but the example will mislead the Builder.**

## Required (must fix before building)
1. **`EpisodicMemory.store` takes a single `Episode` argument, not kwargs.** Grep evidence:
   ```
   grep -n "async def store" src/probos/cognitive/episodic.py
     1056: async def store(self, episode: Episode) -> None:
   ```
   The D2 harness body calls `await em.store(user_input=turn["text"], dag_summary={}, outcomes=[])` — every kwarg is wrong. The prompt's "Builder verifies the actual signature" caveat covers responsibility but the example code will be copy-pasted. Replace with:
   ```python
   from probos.types import Episode
   ep = Episode(user_input=turn["text"], ...)  # verify-first the required Episode fields
   await em.store(ep)
   ```
   And note the required `Episode` fields explicitly. This is the single biggest defect in the prompt.

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. The harness's scoring loop calls `getattr(r, "episode", r).user_input` — fragile. `recall_weighted` returns `list[RecallScore]` (verified at `episodic.py:2509`); pin the exact `.episode` attribute and drop the `getattr` fallback.
3. `em = EpisodicMemory(persist_directory=str(tmp_path))` — same constructor-signature pre-check as the opencode-magic prompt. Verify-first.
4. The fixture spec says "5 questions total" but "3 sessions × 5+ turns" implies up to 15 turns. Each question's `expected_substring` must verbatim appear in the fixture — call out that the Builder must validate the fixture itself before scoring against it. A test_fixture_self_consistency check inside the harness is cheap.

## Nits
- "We do not download the full LoCoMo dataset" is a good hard-constraint; add the file-size estimate (~multi-GB) to the body too so future readers know why.
- Forward markers (AD-712-1/2/3) are well-scoped; consider AD-712-4: per-recall-method comparison (`recall` vs `recall_weighted` vs `recall_by_anchor`) on the same fixture.

## Verified
- `src/probos/cognitive/episodic.py:1648` `async def recall(query, k)` — confirmed.
- `src/probos/cognitive/episodic.py:2509` `async def recall_weighted` — confirmed.
- `src/probos/cognitive/episodic.py:2747` `async def recall_by_anchor` — confirmed.
- `src/probos/cognitive/episodic.py:1056` `async def store(self, episode: Episode)` — confirmed (used to flag Required #1).
- No `tests/benchmarks/` directory exists — Builder creates with `__init__.py`.
- No `locomo`, `longmemeval`, `benchmark_score` symbols — greenfield claim holds.
- Opt-in via `PROBOS_BENCHMARK_LOCOMO=1` — opt-in discipline correct.
- Hard-constraint list correctly forbids real-dataset download, LLM-judge, default-gate inclusion, network egress, public publishing of the ratio.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Required #1 (Episode constructor) landed inline.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ **Required #1 (Episode signature):** Verified at line 120 — wait em.store(Episode(user_input=turn["text"])). Phantom m.store(user_input=..., dag_summary=..., outcomes=...) kwargs invocation is gone. Inline comment at line 113 documents that `EpisodicMemory.store` takes a single `Episode`.
- ✅ `EpisodicMemory.store(self, episode: Episode)` verified at HEAD (pisodic.py:1056).
- ✅ Working-tree integrity reminder in Acceptance section.
- ✅ No phantom-API regressions.

### Pass-2 outcome
Promoted from ⚠️ to ✅. Cleared for Builder dispatch.
