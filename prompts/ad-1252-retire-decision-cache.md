# AD-1252: retire the AD-272 decision cache

**Issue:** #1273 (BF-809) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## The decision, made

**Retire it.** The cache is written on every turn and has never been read in production.

This is an engineering call rather than a Captain call, because the thing being removed delivers
**zero measured benefit today** — there is no capability to weigh against the removal. If the
Captain wants conversational caching, that is a *new* design (see "If the Captain wants a cache"
below), not a repair of this one.

## Why option 1 does not survive contact

The issue offered "hash a deliberate semantic projection of the observation". Executed against the
real agent, that turns out to be an open-ended classification problem with a Captain-visible
failure mode.

`_compute_cache_key` hashes the **entire** observation:

```
cognitive_agent.py:11308-11312
    obs_str = json.dumps(observation, sort_keys=True, default=str)
    key_material = f"{self.instructions}|{obs_str}"
    return hashlib.sha256(key_material.encode()).hexdigest()[:16]
```

Two problems, both measured:

**1. Two identity fields differ, not one.** The issue named `correlation_id`. A re-asked question
also mints a fresh `intent_id`, so a fix excluding only the first still never hits for the exact
case the cache exists to serve.

**2. `_execute_cognitive_lifecycle` enriches the observation between `perceive()` and `decide()`,
and every added field is semantic.** `_recall_relevant_memories` (`cognitive_agent.py:9872`) writes
`recent_memories`, `_basic_recall_episodes`, `_source_attribution`, `_source_framing`,
`_oracle_context`, `_transcript_grounding`, `_recall_fok_band`, `_recall_recall_type`,
`_ad604_spreading_activation`; `cognitive_skill_instructions` / `cognitive_skill_name` arrive at
`:6096`; `_sibling_conclusions` at `:6104`; `_spine.drive_cycle(observation)` (AD-1034) may mutate
it further.

Excluding any of those from the key serves a previous turn's answer to a question whose context has
changed. Including them means the key matches only when the entire recall surface is identical —
which, for a conversational agent with growing episodic memory, is close to never. So the choice is
between a stale-answer risk and a near-zero hit rate, and the maintenance burden is the same either
way.

That is the argument for retirement: the current state is the cost of a cache, the risk surface of
a cache, and none of the benefit — and every reachable variant keeps at least two of the three.

## Required change

Delete, from `src/probos/cognitive/cognitive_agent.py`:

| Site | What |
|---|---|
| `:148-149` | `_DECISION_CACHES` module global |
| `:846` | `_cache_ttl_seconds` class attribute |
| `:3320-3353` | the read: `setdefault`, `_compute_cache_key`, hit branch, TTL expiry `del` |
| `:3411`, `:3440`, `:3460` | the three `cache[cache_key] = (...)` writes |
| `:11306-11324` | `_compute_cache_key`, `_get_cache_ttl` |
| `:11326-…` | `evict_cache_for_type` and the classmethod iterating `_DECISION_CACHES` at `:11341` |

One external caller must go with it:

```
startup/finalize.py:5447   _evicted = CognitiveAgent.evict_cache_for_type(agent.agent_type)
```

Enumerated repository-wide — that is the **only** consumer outside the module:

```
rg -n '_DECISION_CACHES|evict_cache_for_type|_cache_ttl_seconds|decision_cache' src/
  cognitive/cognitive_agent.py: 149, 846, 3327, 11317, 11323, 11326, 11328, 11341
  startup/finalize.py:5447
  config.py:1699   llm_classifier_cache_ttl_seconds   <- UNRELATED, do not touch
```

`config.py:1699` is a different cache. Leave it alone.

### The AD-1248 projection goes too

`_cacheable_decision` (`cognitive_agent.py:58`, *"the decision minus per-run provenance, for the
AD-272 cache"*) exists solely to strip provenance before a cache write. With no writes it has no
purpose. **Check for other callers before deleting** — if AD-1248 or anything else calls it for a
non-cache reason, keep it and correct the docstring instead. Do not assume; grep.

## Do not build

- **Do not implement the allowlist key.** `.git/BF809_ATTEMPT.patch` (6,118 bytes) contains it,
  with a fail-safe returning `""` for unruled fields. It is preserved as evidence and must stay
  unapplied. One useful fact from it regardless: the three writes and the read at `:3330` have **no
  guard against a sentinel key**, so any future "do not cache" signal needs four sites, not one.
- **Do not re-site the cache at `perceive()` time.** That is a different design and a separate AD.
- **Do not replace it with a "smaller" cache**, an LRU, or a memoised sub-step. The finding is that
  caching an assembled cognitive context is the wrong shape, not that this cache was too big.
- **Do not touch `LLMClient`'s own caching**, the classifier cache, or `config.py:1699`.

## Tests

1. Delete the AD-272 cache tests rather than porting them. `tests/test_cognitive_agent.py:328-338`
   in particular is the "test double more capable than production" case the issue names — it calls
   `decide()` twice with one handcrafted observation so the key is stable by construction. Deleting
   it is the point; say so inline in the commit message.
2. Two identical `handle_intent()` turns produce **two** LLM calls. This pins the retirement: any
   future reintroduction has to change this assertion and justify it.
3. `evict_cache_for_type` no longer exists on `CognitiveAgent`, and `finalize.py` starts cleanly
   without it.
4. A full agent lifecycle (`perceive` → enrich → `decide` → `act`) is unchanged in output for a
   fixed observation. The retirement must be behaviour-preserving apart from the removed
   memoisation.

## If the Captain wants a cache — state this, do not build it

The honest option-2 shape, for the record and for a future AD: a narrow, deliberately-constructed
**question** key computed at `perceive()` time, *before* enrichment — intent, params, and an
explicit short allowlist of context — never the enriched observation at `decide()` time. Proven by a
hit test through the real `handle_intent()` lifecycle, not a direct `decide()` call. That is a new
feature with a new key, a new site, and a new TTL policy, and it should be costed as one.

## Tracking

- Close **#1273** as built (retired).
- Note on **#1262 (BF-798)** that its stale-`_tool_trace_ref` replay is now structurally
  impossible, and that it was **latent rather than live** for the window between provenance landing
  (2026-08-09) and the AD-1248 projection, because the cache never hit.
- `PROGRESS.md`, `DECISIONS.md` (AD-272 superseded by AD-1252), roadmap.

## Report back

- Confirmation that `_cacheable_decision` had no non-cache caller — or that it did, and was kept.
- Test count before and after.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
