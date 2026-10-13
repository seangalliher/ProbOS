# AD-1327 -- Crew verifier names its own model and reports when it judges itself (#1511)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 -- hidden pins found by execution (orchestrator's diagnostic full suite on the applied Sections 1-11: four more pins, now Sections 11i-11l; Section 6 docstrings reworded).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 -- review round 1 repairs (Diff Reviewer round 1 NOT READY, `logs/architect/review-ad1327-r1.md`; findings reproduced by `logs/architect/probe_ad1327_r1_findings.py`): D8 verifier credential isolation (Section 2g), D9 the provider's model id (Sections 2f, 2h, 5, 6, 8), D10 the answering tier (Sections 2f, 2i, 2j, 5, 6, 8), hidden pin 11m, tests 42-48, mutation rows 26-36; sync of post-install edits (tests 19, 20, 23, 35, 36; Section 2a, 6 and 10 comments).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 -- review round 2 repairs (Diff Reviewer round 2 NOT READY, `logs/architect/review-ad1327-r2.md`; findings reproduced by `logs/architect/probe_ad1327_r2_findings.py`, `.out`): F4 D8 amended, a verifier shares a pool only when every other tier on it has the verifier's key (Section 2g); F5 strict UTF-8 encodability joins the judge model bound (D9 amended; Sections 5, 6); explicit file paths on labels 2g-2j; tests 20, 23, 44, 47 lists, new tests 49-51, test-23 comment wording; mutation rows 37-42; trackers, Acceptance Criteria and evidence sections updated.

**Status:** Ready for Builder (split workflow). **Base:** `origin/main` `692e1df6eb29dd424a4a610b776c829ea65ee8f4`.
**Number:** AD-1327 already allocated to #1511 (`scripts/ad_ceiling.py` 2026-10-13: CEILING AD-1327 from GitHub issue titles; no new number).
**Dependencies:** none. #1510 (AD-1326) will reuse the tier later; do not build it.
**Estimated tests:** about 71 new (two new files; 7 added by review round 1, 3 by review round 2, plus new cases in tests 20, 23, 31, 33, 44, 47) plus 18 pinned lines updated in 10 existing test files and 1 test fixture (Sections 11a-11l), and one projection in `tests/test_ad1325_boundaries.py` (11m).
**No new EventType** (no Section 0).

One line: add a `verifier` LLM tier the crew verifier requests when `cognitive.llm_model_verifier` is set (unset = the exact pre-AD-1327 `standard` request), record on every answered verdict which model judged it and whether that model is the crew's own model, family, unknown or independent, and report it at startup and in `probos doctor`.

---

## Problem

- `SubtaskVerifier.verify` and `verify_for_session` hard-code the judge tier: `src/probos/cognitive/crew_verifier.py:1421` and `:1848` (`tier="standard",`). No config field selects the judge model.
- Crew workers run on the text tiers (`TEXT_TIERS = _TIER_ORDER = ("fast", "standard", "deep")`, `llm_client.py:48-51`). AD-1324's tier choice ranks only `TEXT_TIERS` (`tier_policy.py:26`, `:429-432`). When every text tier maps to one model, worker and judge are the same model, and nothing says so: no verdict, log line or doctor check records the judge's model.
- MASS finding 3 (`docs/research/mass-self-supervision-absorption.md:32`) names AD-1327 as the owner.

## Solution (decisions; ranked options in "Design decisions" below)

1. **Tier.** `VERIFIER_TIER = "verifier"` joins `_LLM_TIERS` (per-tier state, probes, own endpoint) and stays **outside** `_TIER_ORDER`. Five config fields follow the AD-732 pattern. A request for `verifier` falls back to `standard, fast, deep`; an **unconfigured** verifier tier is skipped in that chain.
2. **Unset is today.** The crew verifier asks a `VerifierJudgePolicy` which tier to request: `standard` when `llm_model_verifier` is unset (byte-identical `LLMRequest`, pinned by a golden), `verifier` when set.
3. **Routing keeps the cost ceiling.** When set, the verifier model is registered in the model router under its own tier (`routed_tiers`), verifier attempts are routed `exact_tier=True` (served by the verifier model or skipped, never by a substituted crew model), the router's any-tier fallback never picks a non-text tier's model for a crew request, and the verifier's connectivity probe obeys the ceiling (BF-886 A-1).
4. **Sameness.** Normalised model id (case-folded, after the last `/`) against the fast/standard/deep models; family from a new `model_registry.model_family` (catalog provider, else a ten-marker table; no match or two families = unknown). Outcomes: `same_model`, `same_family`, `unknown`, `independent`. Only `independent` is not degraded; `unknown` is never reported as `independent`.
5. **Verdict record.** `judge: JudgeProvenance | None = None` (tier, model, independence, fallback) appended to `VerificationVerdict` and `SessionVerificationPass`, persisted everywhere `criteria` is persisted and, exactly like `criteria` (AD-1244), **omitted when absent**, so rows written before AD-1327 keep their bytes and trust-evidence hashes. A fallback verdict never records `independent` (enforced in the policy and by the model validator). The record's `model` is the model id the **provider's reply** named (`LLMResponse.answered_model`, D9), never the id the client sent; `fallback` is True unless the **requested tier's attempt** answered (`LLMResponse.answered_tier`, D10), never inferred from model ids.
6. **Reports.** Startup banner line (`__main__._create_llm_client`), a runtime log line where the verifier is wired, and a new `verifier_independence` doctor check. All report only while `agentic_dispatch.orchestrator_enabled` (the verifier's only consumer, `startup/finalize.py:2112-2114`, `:2235`); otherwise the doctor check is OK and says the verifier is not in use. WARN, never FAIL.
7. **Its own credential (D8).** A configured verifier tier shares an httpx pool only when every other tier on that `base_url|api_format` has the verifier's API key; otherwise it gets its own pool, so its requests, its connectivity probe and every rebuild of its pool carry its own key (any tier on a shared pool can rebuild it with its own key, BF-612). Every other tier's pooling is unchanged.

---

## Design decisions (ranked; chosen = first)

Criteria: correctness, safety, compatibility, architectural fit, reversibility, validation cost.

**D1 -- where the tier lives.**
1. *Chosen:* `verifier` in `_LLM_TIERS`, outside `_TIER_ORDER`, falling back into the standard chain. Every per-tier dict (`llm_client.py:290`, `:296`, `:324`, `:329`, `:348`, `:352`, `:381`, `:427`, `:1139`, `:2434`, `:2472`, `:213`) iterates `_LLM_TIERS`, so the tier must be a member or `_wait_for_rate_limit` (`:1077` indexes `self._request_timestamps[tier]`) raises `KeyError`. Outside `_TIER_ORDER` keeps it out of AD-1324 tier choice, the stakes floor (`config_models/agentic.py:383`), the model router's `_tier_rank` (`model_router.py:84-91`), setup's text tiers and doctor's required tiers.
2. Inside `_TIER_ORDER`: rejected; agents could choose it and the floor would rank it.
3. A second client instance for the verifier: rejected; duplicates pools, health and rate state (DRY) and still needs a router answer.

**D2 -- unset behaviour.**
1. *Chosen:* the verifier sends `tier="standard"` when unset (policy decides). The request is byte-identical (golden), and the client never sees `verifier`.
2. Always send `tier="verifier"` and let the client alias it: rejected for the unset case; rate bucket (`llm_client.py:1467-1472` has no `verifier` key, default 60), cache key (`_cache_key`, `:1059-1065`) and `LLMResponse.tier` would differ from today. (Kept only as defence: an unset `verifier` request is skipped to the standard chain.)

**D3 -- router.** `build_model_routing` seeds only `TEXT_TIERS` (`model_router.py:451-455`); `_decide` with an unregistered tier falls through to "pick any available model" (`model_router.py:284-294`), which would POST a crew model to the verifier endpoint (the BF-273 shape, `llm_client.py:961-971`).
1. *Chosen:* register the verifier model under tier `verifier` when set, route verifier attempts `exact_tier=True`, and stop the any-tier fallback from picking a non-text tier's model. The cost ceiling governs verifier calls and probes.
2. Bypass the router for `verifier` as vision does (`llm_client.py:972-978`): rejected; verifier calls would escape the operator's cost ceiling (weakens a governance control).

**D4 -- "same model".**
1. *Chosen:* normalised model id, not endpoint; compared with the configured fast/standard/deep models. One model behind two endpoints is one model.
2. Endpoint + id: rejected; a proxy and a direct API serving one model would read as independent.

**D5 -- family.**
1. *Chosen:* new public `model_registry.model_family` (catalog `provider` for the three exact catalog names, `model_registry.py:51-87`; else ten substring markers on the normalised id; zero or two families = `None`).
2. Reuse `copilot_adapter._classify_provider` (`copilot_adapter.py:107-118`): rejected; private, a display label, and it buckets qwen and deepseek as one "Local/OSS" provider.

**D6 -- verdict record.**
1. *Chosen:* one nested `judge` record (pydantic, strict, frozen) beside `criteria`, omitted when `None` (the AD-1244 `_VerdictRecord._serialize` precedent, `crew_finalizer.py:248-254`: "Absence is part of historical checkpoint bytes and trust identity").
2. Three flat fields: rejected; three omissions to keep in step at five sites.
3. Always write `"judge": null`: rejected; changes bytes and `evidence_sha256` (`crew_trust.py:202-208`) of verdicts that have no judge.
Compatibility path: old rows (no `judge`) read unchanged (tested). A rollback to a pre-AD-1327 build refuses rows that carry `judge` (`extra="forbid"`), exactly as it refuses AD-1244 `criteria` (`test_ad1244_verdict_criteria.py:385-393`); that refusal fails closed (unverified), never accepts.

**D7 -- report gating.** `tests/test_ad1137_quickstart_chain.py:275-276` pins "All checks passed." for a fresh single-model install.
1. *Chosen:* WARN only while `agentic_dispatch.orchestrator_enabled` (default False, `tests/test_ad1125_room_bound_execution.py:3752`); OK "not in use" otherwise. The risk is reported where it exists.
2. WARN always, update the quickstart pin: rejected; every fresh install would warn about a component that never runs.
3. WARN only when `llm_model_verifier` is set: rejected; hides the reference-vessel case the issue names.

**Review round 1 (2026-10-13).** Diff Reviewer round 1 (GPT-6.1 Sol) found three defects, and the orchestrator reproduced each with a real `OpenAICompatibleClient` against a loopback server (`logs/architect/probe_ad1327_r1_findings.py`, `.out`). F1: on a shared URL the verifier request carried the shared key. F2: the judge record named the model sent (`claude-sonnet-4-6`, `independent`) when the provider answered as `gpt-5.1`; the same happened for an echo of null, an integer, NUL text, 257 characters or no field. F3: the dedicated endpoint answered 503, standard answered with the same model id, and the record said `fallback=False`. The 82 tests could not see any of this: `_FakeJudgeLLM` returns no provenance, and `_FakeEndpoints` drops the Authorization header and omits `model` from the reply.

**D8 -- verifier credential isolation (F1).** Facts: `_client_key` is `base_url|api_format` (`llm_client.py:435-438`). `__init__` builds one pool per key from the first tier in `_LLM_TIERS` order (`:301-308`), and `_build_client` bakes that tier's key into the pool's headers (`:822-826`). `VERIFIER_TIER` is last, so it always joins a pool another tier built. The probe (`_check_endpoint`), `_client_lease`, `_refresh_client`, the BF-654 semaphores (`:384-389`), the BF-674 failure states (`:404-406`) and the `checked_endpoints` probe reuse (`:1166-1168`) all key on `_client_key`.
1. *Chosen:* a new module function `_client_pool_key` returns `base_url|api_format|verifier` for a **configured** verifier tier when **any** other tier with the same `base_url|api_format` has a different key (review round 2: was "the first other tier"; see "Review round 2" below). Otherwise it returns the base key, so an unset verifier, a verifier whose key every sibling shares and every other tier keep the pool they have today. The suffix is a constant: no key, and nothing derived from one, appears in a pool name, which is logged (`:1643`). Because every per-endpoint structure keys on `_client_key`, the verifier then gets its own pool, refresh generation, in-flight semaphore, breaker and probe, all with its own key, and no shared header is ever mutated. Trade-offs: one host can see two in-flight caps (the verifier's traffic only), and a standard outage on that host does not pre-open the verifier's breaker; the verifier attempt fails once and falls back to standard.
2. A per-request `Authorization` header on verifier requests and probes: rejected. It touches both transports and the probe, and leaves the verifier on the shared pool's failure state and on the `checked_endpoints` reuse, so the verifier's key is never probed and its 401s count as failures of the shared endpoint.
3. Credential-aware pooling for every tier: rejected. Out of scope (it changes existing tiers' pooling and the pool counts BF-654/BF-674 tests pin) and needs a key-derived identity in pool names. The existing tiers' same limitation predates AD-1327 and is reported separately.
4. Refuse the configuration, or WARN in doctor: rejected. It leaves the advertised `llm_api_key_verifier` broken and refuses a valid configuration.

**D9 -- the provider's model id (F2).** Facts: `_call_openai` and `_call_ollama_native` build `LLMResponse(model=model)` from the id they sent (`llm_client.py:2375-2377`, `:2436-2438`) and never read the body's `model`. The chat-completion object's `model` is "the model used for the chat completion" (OpenAI API reference), and Ollama's `/api/chat` reply carries `model`.
1. *Chosen:* an additive `LLMResponse.answered_model: str | None = None`. Both transports set it from the reply body with one helper, `_echoed_model`: the body's `model` string, verbatim, or `""` when the field is absent or not a string. `model` keeps its meaning (the id sent), so token accounting (`cognitive_agent.py:4463`, `agentic_dispatch.py:3790`), logs and the cache do not change. `None` means the response did not come from a provider transport: a test double, `MockLLMClient` or an error result. The judge record's `model`, and the independence it is classified by, are `answered_model` after the policy bounds it. `None`, `""`, a non-string, NUL, more than `MAX_JUDGE_MODEL_CHARS` or text that is not strict UTF-8 (a lone surrogate; review round 2) all give `""` with `unknown`. **An absent echo is treated like an unusable one:** both reference APIs return the field, and recording the id we *asked for* would claim an identity nobody confirmed. The cost is that a provider which never echoes gets `unknown` (degraded, which is honest).
2. Make `LLMResponse.model` the echo: rejected. It changes every consumer of `model`, and a dated snapshot id in the reply would alter token records and logs.
3. Fall back to the sent id when the echo is absent: rejected. That is the F2 absent-field case, an unconfirmed identity that can be classified as `independent`.
4. Record the echo but classify the sent id: rejected. Independence would rest on a value the provider contradicted.

**D10 -- the answering tier (F3).** Facts: `LLMResponse.tier` is the *requested* tier (`llm_client.py:2378`). The router's served tier `_served` is `None` on non-exact attempts whenever a router is wired (`:1571`). The attempt loop always knows `attempt_tier`, and both cache replays (`:1487-1490`, `:1958-1965`) rebuild the response from its fields.
1. *Chosen:* an additive `LLMResponse.answered_tier: str | None = None`. On the success path the attempt loop sets it to `attempt_tier` (`dataclasses.replace`) **before** `_cache_put`, so the returned response and the cached entry both carry it. Both cache replays copy `answered_tier` and `answered_model`, so a replay still says who produced the content. For both policies, `fallback = not (answered_tier is a str equal to the requested tier)`. An absent `answered_tier` (a double, `MockLLMClient`) counts as fallback: the requested tier is not shown to have answered, so the record is degraded and never `independent`. A dedicated-tier answer whose model id equals a crew model's records `fallback=False` and `same_model`. The `verifier` tier answered, with a model the crew also runs, which is exactly what the operator configured.
2. Use the router's `_served`: rejected; it is `None` on every routed non-exact attempt.
3. Infer fallback from model ids (as built): rejected; that is F3, and a dated snapshot id would read as a fallback.
4. Out-of-band provenance ("last answered tier" on the client, or a context variable): rejected; it is shared mutable state across concurrent requests.

**Review round 2 (2026-10-13).** Diff Reviewer round 2 (GPT-6.1 Sol) confirmed F1-F3 repaired and found two defects, both reproduced by the orchestrator with a real client and a loopback server (`logs/architect/probe_ad1327_r2_findings.py`, `.out`). F4: fast/shared key A, standard key B, verifier key A on one URL; the verifier shared the pool (one pool key), its control request carried A, and after standard's ordinary empty-content recovery (BF-612; 2 standard requests) the verifier request carried B. F5: a reply `model` of `"gpt-\ud800-5"` (a JSON `\ud800` escape decodes to a lone surrogate) reached `answered_model` over the wire, passed the policy and `JudgeProvenance`, and `crew_finalizer._compact_bytes` refused the judge record, so the verdict checkpoint was not written (`crew_finalization_checkpoint_too_large`). ASCII and non-ASCII scalar controls encoded.

**D8 amendment (F4).** Facts (on the candidate tree): only two code paths put a pool in `self._clients`: `__init__` (`llm_client.py:346`, first tier in `_LLM_TIERS` order) and `_refresh_client` (`:923`; `:929` restores the old one on failure), which rebuilds with `_build_client(tier)` (`:908`) for the **refreshing** tier, so its header is that tier's key. The only production caller is the attempt loop's BF-612 recovery (`:1745`, `attempt_tier`); `_close_owned_clients` only pops (`:2627`). `_tier_configs` is written once, in `__init__`. So the header of a shared pool is the key of whichever tier last built it.
1. *Chosen:* (a) a configured verifier shares a pool only when **every** other tier on that `base_url|api_format` has the verifier's key; otherwise `|verifier`. Invariant: on a shared pool every tier that can build it (any sibling, or the verifier) bakes the verifier's key, so every generation carries it; on `|verifier` only the verifier builds it (test 43). Tier configs never change after `__init__`, so the invariant holds for the client's life. The common single-key configuration keeps one pool, one probe and one breaker; non-verifier pool keys and an unset verifier are byte-identical to base; test 42's controls are unchanged. Every other tier counts, even one with no model that never refreshes: at worst one extra pool in a mixed-key configuration, never a wrong header.
2. (d) Count only tiers that can call `_refresh_client` (those with a model on the attempt path): rejected; it couples pool identity to the attempt loop's tier selection for at most one saved pool in rare configurations.
3. (b) Always isolate a configured verifier: rejected; the single-key configuration would get a second pool, a second probe (a generation request, BF-886 A-1) and a split breaker, and test 42's same-key control would change, for no correctness gain over (a).
4. (c) Rebuild with the pool's original key in `_refresh_client`: rejected; it changes BF-612/BF-665 refresh for every existing tier and freezes the existing tiers' first-tier-key limitation (pre-existing, reported separately) instead of fixing it.

**D9 amendment (F5): the usability bound includes strict UTF-8 encodability.** One predicate, `crew_verdict.is_persistable_judge_model` (type `str`, no NUL, at most `MAX_JUDGE_MODEL_CHARS`, `value.encode("utf-8")` does not raise), owned by the record's module and used by both `JudgeProvenance._validate_model` (refuses a persisted record) and `VerifierJudgePolicy.provenance` (degrades to `""` / `unknown`). DRY: the two bounds can no longer drift. Rejected: bounding in the transport (`_echoed_model`; only the persisted record needs it, and the transport stays verbatim, test 44); `errors="replace"` or `surrogatepass` re-encoding (records a model id the provider did not send). Encoders a judge record passes through, and what a lone surrogate does there today:

| Encoder | Site | Lone surrogate today | After the bound |
|---|---|---|---|
| finalizer `_compact_bytes` (`ensure_ascii=False`, strict UTF-8) | `crew_finalizer.py:131-144`; `_write_json_checkpoint` `:2347-2356`; provenance `:2264`, `:3688` | refused (`UnicodeEncodeError` -> `ValueError(error)`): checkpoint not written | never reaches it (`""`) |
| owned steps `owned_json_bytes` | `work_item_steps.py:83-88`; owned legacy review payload `crew_orchestrator.py:3985`; legacy episode effect intent `crew_synth.py:430` -> `:598`; finalizer `:1836`, `:1904` | refused (`owned_steps_format_invalid`) | never reaches it |
| trust evidence `_exact_json_bytes` (strict) | `crew_trust.py:29` (encode `:56-64`), used at `:207-212` | refused (`crew_trust_evidence_invalid`) | never reaches it; a persisted surrogate is refused earlier by `parse_judge` (`:191`) |
| synth parent provenance `json.dumps(..., default=str)` (ASCII escapes) | `crew_synth.py:1087` | accepted (written as a `\ud800` escape) | never reaches it |
| episodic `json.dumps(ep.outcomes)` and content hash (ASCII escapes) | `episodic.py:3556`, `:1046` | accepted (escaped) | never reaches it |

*Separate observation, not fixed here:* a verdict's `critique` comes from the judge's content and is bounded for NUL only (`crew_verifier.py:2507`); a lone surrogate in a provider's content would meet the same strict encoders. It predates AD-1327 (as does `content` in general) and is reported separately.

---

## Implementation

Apply each SEARCH/REPLACE exactly; every SEARCH is unique in its file at base `692e1df6`. Stage explicit paths only. **Never stage `config/system.yaml`** (the reference vessel's local file; the issue forbids changing it).

### Section 1 -- `src/probos/config.py`: verifier tier fields and `tier_config`

1a. Fields after the image_gen block.

SEARCH:
```python
    llm_base_url_image_gen: str | None = None
    llm_api_key_image_gen: str | None = None
    llm_model_image_gen: str | None = None
    llm_timeout_image_gen: float | None = None
    llm_api_format_image_gen: str | None = None  # "openai" (only supported shape)
```
REPLACE:
```python
    llm_base_url_image_gen: str | None = None
    llm_api_key_image_gen: str | None = None
    llm_model_image_gen: str | None = None
    llm_timeout_image_gen: float | None = None
    llm_api_format_image_gen: str | None = None  # "openai" (only supported shape)

    # AD-1327: verifier tier -- the model the crew verifier judges crew work with.
    llm_base_url_verifier: str | None = Field(
        default=None,
        description=(
            "AD-1327: base URL of the crew verifier's judge model. None uses the shared "
            "llm_base_url, as the text tiers do."
        ),
    )
    llm_api_key_verifier: str | None = Field(
        default=None,
        description="AD-1327: API key for the verifier tier. None uses the shared llm_api_key.",
    )
    llm_model_verifier: str | None = Field(
        default=None,
        description=(
            "AD-1327: model the crew verifier judges crew work with. Unset or blank: the "
            "verifier requests the standard tier, as before AD-1327. Set: it requests the "
            "verifier tier, which falls back to standard, fast and deep, and each verdict "
            "records its judge model and whether that is a crew tier's model or family."
        ),
    )
    llm_timeout_verifier: float | None = Field(
        default=None,
        description="AD-1327: verifier tier timeout in seconds. None uses llm_timeout_seconds.",
    )
    llm_api_format_verifier: str | None = Field(
        default=None,
        description='AD-1327: "openai" or "ollama" for the verifier tier. None uses "openai".',
    )

    @field_validator("llm_model_verifier", mode="before")
    @classmethod
    def _blank_verifier_model_is_unset(cls, value: object) -> object:
        # AD-1327: a blank model name leaves the verifier tier unset, never a model named "".
        return None if isinstance(value, str) and not value.strip() else value
```

1b-1f. One entry per resolved map (temperature, top_p, max_tokens and suffix maps stay without an entry; `.get` yields `None`, `config.py:677-680`).

SEARCH:
```python
            "image_gen": self.llm_model_image_gen,
        }
        url_map = {
```
REPLACE:
```python
            "image_gen": self.llm_model_image_gen,
            "verifier": self.llm_model_verifier,
        }
        url_map = {
```
SEARCH:
```python
            "image_gen": self.llm_base_url_image_gen,
        }
        key_map = {
```
REPLACE:
```python
            "image_gen": self.llm_base_url_image_gen,
            "verifier": self.llm_base_url_verifier,
        }
        key_map = {
```
SEARCH:
```python
            "image_gen": self.llm_api_key_image_gen,
        }
        timeout_map = {
```
REPLACE:
```python
            "image_gen": self.llm_api_key_image_gen,
            "verifier": self.llm_api_key_verifier,
        }
        timeout_map = {
```
SEARCH:
```python
            "image_gen": self.llm_timeout_image_gen,
        }
        format_map = {
```
REPLACE:
```python
            "image_gen": self.llm_timeout_image_gen,
            "verifier": self.llm_timeout_verifier,
        }
        format_map = {
```
SEARCH:
```python
            "image_gen": self.llm_api_format_image_gen,
        }
        temp_map = {
```
REPLACE:
```python
            "image_gen": self.llm_api_format_image_gen,
            "verifier": self.llm_api_format_verifier,
        }
        temp_map = {
```

Result: unset, `tier_config("verifier")["model"]` is `None` (as vision's is) and its URL/key are the shared ones (`config.py:672-673`), **not** standard's per-tier overrides. That is deliberate: a model-less optional tier must not count as "using the shared URL" in setup (`provider_setup.py:814-820`).

### Section 2 -- `src/probos/cognitive/llm_client.py`

2a. Constant and tier set.

SEARCH:
```python
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")
```
REPLACE:
```python
# AD-1327: the crew verifier's judge tier. A peer in ``_LLM_TIERS`` (per-tier state,
# probes, its own endpoint) but outside ``_TIER_ORDER``: AD-1324's tier choice and
# stakes floor rank ``TEXT_TIERS`` only, so neither can select it. A request for
# it falls back to standard, fast, deep (``_complete_inner``).
VERIFIER_TIER: str = "verifier"
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", VERIFIER_TIER)
```

2b. Fallback chain (insert a branch; the vision lines that `tests/test_ad742a_vision_fast_tier.py:130-139` scans for stay).

SEARCH:
```python
            fallback_tiers = ["vision_fast", "vision"]
        elif exact:
            fallback_tiers = [tier]
```
REPLACE:
```python
            fallback_tiers = ["vision_fast", "vision"]
        elif tier == VERIFIER_TIER:
            # AD-1327: the verifier tier falls back to the chain the crew verifier used
            # before it existed: standard, then fast and deep. An unconfigured verifier
            # tier (no model) is skipped, so its request goes down the standard chain.
            verifier_first = [tier] if self._tier_configs[tier].get("model") else []
            fallback_tiers = [*verifier_first, "standard", *(t for t in _TIER_ORDER if t != "standard")]
        elif exact:
            fallback_tiers = [tier]
```

2c. Route verifier attempts exact.

SEARCH:
```python
                if exact:
                    _override, _served = self._resolve_route_for_tier(
                        attempt_tier, min_tier=floor, correlation=correlation, exact_tier=True,
                    )
                elif floor is None and correlation is None:
```
REPLACE:
```python
                if exact:
                    _override, _served = self._resolve_route_for_tier(
                        attempt_tier, min_tier=floor, correlation=correlation, exact_tier=True,
                    )
                elif attempt_tier == VERIFIER_TIER:
                    # AD-1327: the verifier attempt is served by the verifier model or refused
                    # (TierExactExclusion skips it); the router never substitutes a crew tier's
                    # model on the verifier endpoint, and the cost ceiling still applies.
                    _override, _served = self._resolve_route_for_tier(attempt_tier, exact_tier=True)
                elif floor is None and correlation is None:
```

2d. Do not probe an unconfigured verifier tier.

SEARCH:
```python
            if tier in ("vision", "vision_fast") and not tc.get("model"):
                results[tier] = False
```
REPLACE:
```python
            # AD-1327: an unconfigured verifier tier is not probed either; its requests
            # go down the standard chain.
            if tier in ("vision", "vision_fast", VERIFIER_TIER) and not tc.get("model"):
                results[tier] = False
```

2e. The verifier probe obeys the cost ceiling.

SEARCH:
```python
        A probe is a generation request, so for a text tier it obeys the wired
        router's cost ceiling as a completion does: it sends the model the
        router would choose, previewed without logging or events. Other tiers,
        no router, or a router without ``preview`` keep the configured model.
```
REPLACE:
```python
        A probe is a generation request, so for a text tier, and for the verifier
        tier (AD-1327, previewed ``exact_tier``), it obeys the wired router's cost
        ceiling as a completion does: it sends the model the router would choose,
        previewed without logging or events. Other tiers, no router, or a router
        without ``preview`` keep the configured model.
```
SEARCH:
```python
        configured = self._tier_configs[tier]["model"]
        if tier not in TEXT_TIERS:
            return configured
        preview = getattr(getattr(self, "model_router", None), "preview", None)
        if preview is None:
            return configured
        refusal = ""
        try:
            decision = preview(tier=tier)
```
REPLACE:
```python
        configured = self._tier_configs[tier]["model"]
        if tier not in TEXT_TIERS and tier != VERIFIER_TIER:
            return configured
        preview = getattr(getattr(self, "model_router", None), "preview", None)
        if preview is None:
            return configured
        refusal = ""
        try:
            decision = preview(tier=tier) if tier in TEXT_TIERS else preview(tier=tier, exact_tier=True)
```

Known, accepted: with `llm_rate` configured, verifier requests use the default 60 rpm bucket (`rpm_limits.get(tier, 60)`, `llm_client.py:1073`); there is no `rpm_verifier` field (considered, deferred).

Review round 1 subsections 2f-2j (D8-D10; Milestone 1). Every SEARCH below is unchanged by 2a-2e and unique at base `692e1df6`.

2f. `src/probos/types.py`: two additive response fields (appended last, both default `None`, so every positional or keyword construction, `dataclasses.replace` and `asdict` round trip stays valid).

SEARCH:
```python
    # AD-1324 amendment 2: closed token naming WHY a tier refusal happened (floor_unmet, ceiling,
    # exact_unavailable, ineligible, route_unverifiable, redo_floor_unmet); None = unclassified.
    refusal_cause: str | None = None
```
REPLACE:
```python
    # AD-1324 amendment 2: closed token naming WHY a tier refusal happened (floor_unmet, ceiling,
    # exact_unavailable, ineligible, route_unverifiable, redo_floor_unmet); None = unclassified.
    refusal_cause: str | None = None
    # AD-1327: who answered, as distinct from what was asked. ``answered_tier`` is the tier whose
    # fallback-chain attempt produced this response (``tier`` stays the requested one); set by
    # ``OpenAICompatibleClient``'s attempt loop and kept on cache replays. ``answered_model`` is
    # the model id the provider's reply named (``model`` stays the id sent): verbatim text, or ""
    # when the reply named none usable. None = not reported (test doubles, the mock client, errors).
    answered_tier: str | None = None
    answered_model: str | None = None
```

2g. `src/probos/cognitive/llm_client.py`: pool identity (D8, amended by review round 2). Import `replace` for 2i in the same edit.

SEARCH:
```python
from dataclasses import dataclass, field
from typing import Any, NamedTuple
```
REPLACE:
```python
from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple
```
SEARCH:
```python
def _cache_put(client: Any, key: str, response: Any, served_tier: str | None) -> None:
```
REPLACE:
```python
def _pool_base(tc: Mapping[str, Any]) -> str:
    return f"{tc['base_url']}|{tc.get('api_format', 'openai')}"


def _client_pool_key(tier_configs: Mapping[str, Mapping[str, Any]], tier: str) -> str:
    """The httpx pool a tier uses: ``base_url|api_format``.

    AD-1327: a pool's Authorization header is the key of the tier that last built it
    (``_build_client``): ``__init__`` builds it for the first tier in ``_LLM_TIERS``
    order, and ``_refresh_client`` rebuilds it for whichever tier is recovering (BF-612),
    which can be any tier on the pool. So a configured verifier tier shares a pool only
    when every other tier on that ``base_url|api_format`` has the verifier's key, and no
    build of the pool can carry another key; otherwise it gets its own pool,
    ``base_url|api_format|verifier``, whose requests, probe, refresh generation, in-flight
    cap and breaker use its own key. The suffix is a constant; no key, or anything derived
    from one, is part of a pool name (pool names are logged). Every other tier, and an
    unset verifier, keeps the pool it had.
    """
    tc = tier_configs[tier]
    base = _pool_base(tc)
    if tier != VERIFIER_TIER or not tc.get("model"):
        return base
    key = tc.get("api_key") or ""
    for other in _LLM_TIERS:
        oc = tier_configs[other]
        if other != VERIFIER_TIER and _pool_base(oc) == base and (oc.get("api_key") or "") != key:
            return f"{base}|{VERIFIER_TIER}"
    return base


def _echoed_model(data: Any) -> str:
    """AD-1327: the model id a provider's reply body names (its ``model`` field), verbatim.

    ``""`` when the body names none or names something that is not text. The consumer
    that persists it bounds it (``VerifierJudgePolicy.provenance``).
    """
    value = data.get("model") if isinstance(data, dict) else None
    return value if type(value) is str else ""


def _cache_put(client: Any, key: str, response: Any, served_tier: str | None) -> None:
```
SEARCH:
```python
    def _client_key(self, tier: str) -> str:
        """Return the client lookup key for a tier."""
        tc = self._tier_configs[tier]
        return f"{tc['base_url']}|{tc.get('api_format', 'openai')}"
```
REPLACE:
```python
    def _client_key(self, tier: str) -> str:
        """Return the client lookup key for a tier (``_client_pool_key``; AD-1327 verifier credential)."""
        return _client_pool_key(self._tier_configs, tier)
```
(`Mapping` and `Any` are already imported, `llm_client.py:15`, `:19`. No other site builds a pool key: every caller goes through `_client_key`, Verified block R1.)

2h. `src/probos/cognitive/llm_client.py`: the provider's model id in both transports (D9).

SEARCH:
```python
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
        )
```
REPLACE:
```python
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
            answered_model=_echoed_model(data),
        )
```
SEARCH:
```python
            cached=False,
            request_id=request.id,
        )

    def tier_info(self) -> dict[str, dict]:
```
REPLACE:
```python
            cached=False,
            request_id=request.id,
            answered_model=_echoed_model(data),
        )

    def tier_info(self) -> dict[str, dict]:
```

2i. `src/probos/cognitive/llm_client.py`: the answering tier, set before the cache write (D10).

SEARCH:
```python
                        if request.messages is None and response.content:
                            cache_key = self._cache_key(tier, request.prompt, request.system_prompt)
                            # Provenance is the tier whose model SERVED THIS request, read with its
```
REPLACE:
```python
                        # AD-1327: the tier whose attempt answered (its endpoint and route), on the
                        # returned response and the cached entry, so a replay still says who answered.
                        response = replace(response, answered_tier=attempt_tier)
                        if request.messages is None and response.content:
                            cache_key = self._cache_key(tier, request.prompt, request.system_prompt)
                            # Provenance is the tier whose model SERVED THIS request, read with its
```

2j. `src/probos/cognitive/llm_client.py`: both cache replays keep the provenance.

SEARCH:
```python
                            content=cached.content, model=cached.model, tier=tier,
```
REPLACE:
```python
                            content=cached.content, model=cached.model, tier=tier,
                            answered_tier=cached.answered_tier, answered_model=cached.answered_model,
```
SEARCH:
```python
                    content=cached.content,
                    model=cached.model,
                    tier=tier,
```
REPLACE:
```python
                    content=cached.content,
                    model=cached.model,
                    answered_tier=cached.answered_tier,
                    answered_model=cached.answered_model,
                    tier=tier,
```

### Section 3 -- `src/probos/cognitive/model_registry.py`: id normalisation and family

SEARCH:
```python
    exactly; the model router names them in its remedy for a tier the cost
    ceiling leaves without an admissible model.
    """
    return _DEFAULT_DESCRIPTORS
```
REPLACE:
```python
    exactly; the model router names them in its remedy for a tier the cost
    ceiling leaves without an admissible model.
    """
    return _DEFAULT_DESCRIPTORS


# AD-1327: model families by id substring, for the crew verifier's independence
# report. Deliberately small: an id that matches no marker, or markers of two
# families (a distilled "deepseek-r1-distill-qwen" names two), has no known
# family, and an unknown family is never reported as independent.
_FAMILY_MARKERS: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("gemini", "google"),
    ("gemma", "google"),
    ("llama", "meta"),
    ("qwen", "alibaba"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("codestral", "mistral"),
    ("deepseek", "deepseek"),
)


def normalise_model_id(model_id: str) -> str:
    """AD-1327: a model id compared as a model: stripped, after the last "/", case-folded.

    ``anthropic/claude-sonnet-4-6`` and ``Claude-Sonnet-4-6`` name one model.
    """
    return model_id.strip().rsplit("/", 1)[-1].casefold()


def model_family(model_id: str) -> str | None:
    """AD-1327: the vendor family a model id names, or None when unknown or ambiguous.

    A name the built-in catalog lists exactly takes the catalog's ``provider``.
    Otherwise the normalised id is matched against ``_FAMILY_MARKERS``; no match,
    or markers of two families, is None.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    known = _CATALOG_BY_NAME.get(model_id)
    if known is not None and known.provider != "unknown":
        return known.provider
    lowered = normalise_model_id(model_id)
    families = {family for marker, family in _FAMILY_MARKERS if marker in lowered}
    return families.pop() if len(families) == 1 else None
```

### Section 4 -- `src/probos/cognitive/model_router.py`

4a. No non-text tier's model answers a crew request through the any-tier fallback.

SEARCH:
```python
            for d in self._registry.all():
                if d.available and _within_ceiling(d, ceiling) and _meets_floor(d.tier, min_tier):
```
REPLACE:
```python
            for d in self._registry.all():
                # AD-1327: only a text tier's model may stand in for another tier; the
                # verifier model (registered under its own tier) never answers a crew request.
                if d.available and _tier_rank(d.tier) >= 0 and _within_ceiling(d, ceiling) and _meets_floor(d.tier, min_tier):
```

4b. `routed_tiers` and the two seeding/denial sites.

SEARCH:
```python
def build_model_routing(
    config: SystemConfig, *, emit_event: Any | None = None,
) -> ModelRouter | None:
    """BF-886 A-1: the model router ``config`` describes, or None when routing is off.

    Its registry holds exactly the configured model of each text tier
    (``ModelRegistry.from_tier_models``), and it applies the configured cost
    ceiling. The boot factory, startup wiring and ``probos doctor`` all build
    it here, so a probe obeys the policy a completion does.
    """
    if not config.model_routing.enabled:
        return None
    from probos.cognitive.llm_client import TEXT_TIERS

    registry = ModelRegistry.from_tier_models(
        {tier: config.cognitive.tier_config(tier)["model"] for tier in TEXT_TIERS},
    )
```
REPLACE:
```python
def routed_tiers(cognitive: Any) -> tuple[str, ...]:
    """AD-1327: the tiers the model router governs for ``cognitive``.

    The text tiers, then the ``verifier`` tier when ``llm_model_verifier`` names a
    model: that model is registered under its own tier, so the cost ceiling applies
    to it. Unset, this returns ``TEXT_TIERS`` itself.
    """
    from probos.cognitive.llm_client import TEXT_TIERS, VERIFIER_TIER
    from probos.cognitive.verifier_independence import is_verifier_tier_configured

    if is_verifier_tier_configured(cognitive):
        return (*TEXT_TIERS, VERIFIER_TIER)
    return TEXT_TIERS


def build_model_routing(
    config: SystemConfig, *, emit_event: Any | None = None,
) -> ModelRouter | None:
    """BF-886 A-1: the model router ``config`` describes, or None when routing is off.

    Its registry holds exactly the configured model of each routed tier
    (``routed_tiers``: the text tiers, and the verifier tier when set, AD-1327;
    ``ModelRegistry.from_tier_models``), and it applies the configured cost
    ceiling. The boot factory, startup wiring and ``probos doctor`` all build
    it here, so a probe obeys the policy a completion does.
    """
    if not config.model_routing.enabled:
        return None
    registry = ModelRegistry.from_tier_models(
        {tier: config.cognitive.tier_config(tier)["model"] for tier in routed_tiers(config.cognitive)},
    )
```
SEARCH:
```python
    """BF-886 A-1: ``{tier: reason}`` for each text tier ``config``'s cost ceiling leaves no model.
```
REPLACE:
```python
    """BF-886 A-1: ``{tier: reason}`` for each routed tier ``config``'s cost ceiling leaves no model.
```
SEARCH:
```python
    from probos.cognitive.llm_client import TEXT_TIERS

    return router.denials(TEXT_TIERS)
```
REPLACE:
```python
    return router.denials(routed_tiers(config.cognitive))
```

### Section 5 -- `src/probos/cognitive/crew_verdict.py`: the persisted judge record (lowest owning layer)

SEARCH:
```python
def criteria_to_json(
    criteria: tuple[CriterionVerdict, ...],
) -> list[dict[str, Any]]:
    return [criterion.model_dump(mode="json") for criterion in criteria]
```
REPLACE:
```python
def criteria_to_json(
    criteria: tuple[CriterionVerdict, ...],
) -> list[dict[str, Any]]:
    return [criterion.model_dump(mode="json") for criterion in criteria]


# AD-1327: how independent the model that judged a verdict is of the crew's models.
# "unknown" is degraded like the two "same" outcomes and is never reported as
# "independent" (cognitive/verifier_independence.py decides it).
JudgeIndependence = Literal["same_model", "same_family", "unknown", "independent"]
MAX_JUDGE_MODEL_CHARS = 256


def is_persistable_judge_model(value: str) -> bool:
    """AD-1327: whether the text ``value`` can be a judge record's ``model``.

    No NUL, at most ``MAX_JUDGE_MODEL_CHARS`` characters, and strict UTF-8:
    a lone surrogate (what a JSON ``\\ud800`` escape decodes to) is refused, because the
    strict encoders the record passes through (the finalizer checkpoint, owned steps,
    trust evidence) cannot write it. The one bound for a persisted record
    (``JudgeProvenance``) and for a provider's reply (``VerifierJudgePolicy.provenance``).
    """
    if "\x00" in value or len(value) > MAX_JUDGE_MODEL_CHARS:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class JudgeProvenance(BaseModel):
    """AD-1327: the model that judged one verdict, and how independent it is of the crew.

    ``tier`` is the tier the verifier requested: ``verifier`` when
    ``cognitive.llm_model_verifier`` is set, else ``standard``. ``model`` is the
    model id the provider's reply named (``LLMResponse.answered_model``), ``""``
    when it named none usable. ``fallback`` is True when the requested tier is not
    shown to have answered (``LLMResponse.answered_tier``): another tier of the
    fallback chain answered, or the response does not say which tier did.
    Persisted beside ``criteria`` and, like it, omitted when absent, so a verdict
    written before AD-1327 keeps its bytes.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tier: Literal["verifier", "standard"]
    model: str
    independence: JudgeIndependence
    fallback: bool

    @field_validator("model", mode="before")
    @classmethod
    def _validate_model(cls, value: object) -> str:
        if type(value) is not str or not is_persistable_judge_model(value):
            raise ValueError("judge_provenance_invalid")
        return value

    @model_validator(mode="after")
    def _validate_consistency(self) -> JudgeProvenance:
        if self.fallback and self.independence == "independent":
            raise ValueError("judge_provenance_invalid")
        if not self.model and self.independence != "unknown":
            raise ValueError("judge_provenance_invalid")
        return self


def parse_judge(value: object) -> JudgeProvenance:
    """AD-1327: validate a persisted judge record (a JSON object); anything else is refused."""
    if type(value) is not dict:
        raise ValueError("judge_provenance_invalid")
    return JudgeProvenance.model_validate(value, strict=True)


def judge_to_json(judge: JudgeProvenance) -> dict[str, Any]:
    return judge.model_dump(mode="json")
```
(`BaseModel`, `ConfigDict`, `field_validator`, `model_validator`, `Literal`, `Any` are already imported, `crew_verdict.py:5-15`. Pydantic's `ValidationError` subclasses `ValueError`, so callers catching `ValueError` see both.)

### Section 6 -- NEW `src/probos/cognitive/verifier_independence.py`

```python
"""AD-1327 (#1511): which model the crew verifier judges with, and how independent it is.

``crew_verifier.SubtaskVerifier`` asks one LLM to refute crew work. MASS
(arXiv:2610.12176; docs/research/mass-self-supervision-absorption.md, finding 3)
names the risk of a judge that shares the worker's model: a flawed judgement is
accepted, then reinforced. This module decides the tier the verifier requests and
classifies the judge's model against the models of the text tiers crew workers
run on (``llm_client.TEXT_TIERS``):

- ``cognitive.llm_model_verifier`` unset: the verifier requests ``standard``, the
  request it sent before AD-1327, and judges with the standard tier's model.
- set: it requests the ``verifier`` tier. ``OpenAICompatibleClient`` falls back
  from it to standard, fast and deep; a verdict the requested tier is not shown to
  have answered (``LLMResponse.answered_tier``) is marked ``fallback`` and never
  ``independent``. The judge's model is the id the provider's reply named
  (``LLMResponse.answered_model``), never the id the client sent.

Sameness compares normalised model ids (``model_registry.normalise_model_id``),
not endpoints. Families come from ``model_registry.model_family``; a family it
does not know makes the outcome ``unknown``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.cognitive.crew_verdict import (
    JudgeIndependence,
    JudgeProvenance,
    is_persistable_judge_model,
)
from probos.cognitive.llm_client import TEXT_TIERS, VERIFIER_TIER
from probos.cognitive.model_registry import model_family, normalise_model_id

if TYPE_CHECKING:
    from probos.config import CognitiveConfig

_STANDARD_TIER = "standard"

VERIFIER_REMEDIATION = (
    "Set cognitive.llm_model_verifier to a model of a different family from the fast, "
    "standard and deep tiers' models (with llm_base_url_verifier and llm_api_key_verifier "
    "when another endpoint serves it). Until then each verdict records that its judge "
    "is not independent."
)

_OUTCOME_TEXT: dict[str, str] = {
    "same_model": "the same model as a crew tier, so its verdicts are not independent",
    "same_family": "a model of the same family as a crew tier, so its verdicts are not independent",
    "unknown": "a model whose family is not known, so its independence is not established",
    "independent": "a model of a different family from every crew tier",
}


def is_verifier_tier_configured(cognitive: CognitiveConfig) -> bool:
    """AD-1327: whether ``cognitive.llm_model_verifier`` names a model.

    The verifier tier's base URL and key fall back to the shared ones, as the
    text tiers' do, so the model alone decides it. The setup module's
    ``TIER_CONFIGURED_CHECKS``, ``model_router.routed_tiers`` and
    ``VerifierJudgePolicy`` all read this one check.
    """
    return bool(cognitive.llm_model_verifier)


def classify_independence(judge_model: str, crew_models: Iterable[str]) -> JudgeIndependence:
    """AD-1327: how independent ``judge_model`` is of the models in ``crew_models``.

    ``same_model`` when its normalised id equals a crew model's; else
    ``same_family`` when its family is a crew model's family; else ``unknown``
    when there is nothing to compare or a family involved is not known; else
    ``independent``. Empty names in ``crew_models`` are ignored.
    """
    crew = [model for model in crew_models if model]
    judge = normalise_model_id(judge_model) if judge_model else ""
    if not judge or not crew:
        return "unknown"
    if judge in {normalise_model_id(model) for model in crew}:
        return "same_model"
    judge_family = model_family(judge_model)
    crew_families = {model_family(model) for model in crew}
    if judge_family is not None and judge_family in crew_families:
        return "same_family"
    if judge_family is None or None in crew_families:
        return "unknown"
    return "independent"


@dataclass(frozen=True)
class VerifierJudgePolicy:
    """AD-1327: the tier the crew verifier requests and the crew models it is compared with.

    Built once from ``CognitiveConfig`` when the crew orchestrator is wired and
    injected into ``SubtaskVerifier``, so each verdict's judge record, the startup
    line and ``probos doctor`` read one decision.
    """

    request_tier: str
    configured_model: str
    crew_models: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.request_tier not in (VERIFIER_TIER, _STANDARD_TIER):
            raise ValueError(f"verifier_judge_tier_invalid: {self.request_tier!r}")

    @classmethod
    def from_cognitive(cls, cognitive: CognitiveConfig) -> VerifierJudgePolicy:
        crew = tuple(cognitive.tier_config(tier)["model"] or "" for tier in TEXT_TIERS)
        if is_verifier_tier_configured(cognitive):
            return cls(VERIFIER_TIER, cognitive.llm_model_verifier, crew)
        return cls(_STANDARD_TIER, cognitive.tier_config(_STANDARD_TIER)["model"] or "", crew)

    @property
    def dedicated(self) -> bool:
        """Whether a verifier model is configured, so the verifier tier is requested."""
        return self.request_tier == VERIFIER_TIER

    def assess(self) -> JudgeIndependence:
        """The configured judge model's independence (the startup line and ``probos doctor``)."""
        return classify_independence(self.configured_model, self.crew_models)

    def provenance(self, *, answered_tier: object, answered_model: object) -> JudgeProvenance:
        """The judge record for one response, from what the LLM client says answered it.

        ``answered_model`` is the model id the provider's reply named
        (``LLMResponse.answered_model``); ``None``, a value that is not a string, or one
        ``is_persistable_judge_model`` refuses (NUL, longer than ``MAX_JUDGE_MODEL_CHARS``,
        not strict UTF-8) is recorded as ``""`` with ``unknown``. ``answered_tier`` is the tier whose attempt answered
        (``LLMResponse.answered_tier``); ``fallback`` is True unless it is the tier this
        policy requests, so a response that does not say is never ``independent``.
        Model ids never decide ``fallback``. Does not raise for any input (a test pins this).
        """
        model = answered_model if type(answered_model) is str else ""
        if not is_persistable_judge_model(model):
            model = ""
        fallback = not (type(answered_tier) is str and answered_tier == self.request_tier)
        independence = classify_independence(model, self.crew_models)
        if fallback and independence == "independent":
            independence = "unknown"
        return JudgeProvenance(
            tier=self.request_tier, model=model, independence=independence, fallback=fallback,
        )


def verifier_independence_report(policy: VerifierJudgePolicy) -> tuple[JudgeIndependence, str]:
    """AD-1327: the configured judge's independence and a one-line description of it.

    The line names models. The reports that show it to an operator (``probos doctor`` and
    the endpoint banner in ``__main__``) redact configured keys with the setup module's
    ``redact_keys``; the startup log line names the model as the runtime's other
    model logs do.
    """
    independence = policy.assess()
    source = (
        "cognitive.llm_model_verifier"
        if policy.dedicated
        else "the standard tier; cognitive.llm_model_verifier is unset"
    )
    detail = (
        f"{independence} -- judges with {policy.configured_model or '<none>'} ({source}), "
        f"{_OUTCOME_TEXT[independence]}"
    )
    return independence, detail
```

### Section 7 -- setup and Settings

7a. `src/probos/provider_setup.py` (keys must stay in `OPTIONAL_TIERS` order; `verifier` is last in both, `tests/test_ad1135_provider_setup.py:1374`).

SEARCH:
```python
from probos.cognitive.llm_client import _LLM_TIERS, _TIER_ORDER
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
REPLACE:
```python
from probos.cognitive.llm_client import _LLM_TIERS, _TIER_ORDER
from probos.cognitive.verifier_independence import is_verifier_tier_configured
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
SEARCH:
```python
    "image_gen": is_image_gen_tier_configured,  # cognitive/image_gen_dispatch.py:142
})
```
REPLACE:
```python
    "image_gen": is_image_gen_tier_configured,  # cognitive/image_gen_dispatch.py:142
    "verifier": is_verifier_tier_configured,  # AD-1327: cognitive/verifier_independence.py, the crew verifier's tier
})
```

7b. `src/probos/settings/section_registry.py` (HXI cockpit: a manual control for the new tier).

SEARCH:
```python
            FieldDescriptor("cognitive.llm_timeout_image_gen", "Image-gen tier — timeout (s)", "float"),
```
REPLACE:
```python
            FieldDescriptor("cognitive.llm_timeout_image_gen", "Image-gen tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_verifier", "Verifier tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_verifier", "Verifier tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_verifier", "Verifier tier — timeout (s)", "float"),
```

### Section 8 -- `src/probos/cognitive/crew_verifier.py`

8a. Imports.

SEARCH:
```python
from probos.cognitive.crew_verdict import (
    CriterionVerdict,
    parse_verdict_criteria,
    render_critique,
)
```
REPLACE:
```python
from probos.cognitive.crew_verdict import (
    CriterionVerdict,
    JudgeProvenance,
    parse_verdict_criteria,
    render_critique,
)
```
SEARCH:
```python
    from probos.cognitive.mcp_workbench import MCPDispatchOffer, MCPDispatchSource
    from probos.consensus.trust import TrustNetwork
```
REPLACE:
```python
    from probos.cognitive.mcp_workbench import MCPDispatchOffer, MCPDispatchSource
    from probos.cognitive.verifier_independence import VerifierJudgePolicy
    from probos.consensus.trust import TrustNetwork
```

8b. Verdict fields (appended last; positional constructors unchanged).

SEARCH:
```python
    verification_defect: bool = False
    criteria: tuple[CriterionVerdict, ...] | None = None
```
REPLACE:
```python
    verification_defect: bool = False
    criteria: tuple[CriterionVerdict, ...] | None = None
    # AD-1327: the model that judged this verdict; None when no judge answered or none was wired.
    judge: JudgeProvenance | None = None
```
SEARCH:
```python
    failure_code: SessionVerificationFailureCode | None
    criteria: tuple[CriterionVerdict, ...] | None = None
```
REPLACE:
```python
    failure_code: SessionVerificationFailureCode | None
    criteria: tuple[CriterionVerdict, ...] | None = None
    # AD-1327: the model that judged this verdict; None when no judge answered or none was wired.
    judge: JudgeProvenance | None = None
```

8c. Constructor injection.

SEARCH:
```python
        max_convergence_rounds: int = 2,
        ontology: Any = None,
    ) -> None:
```
REPLACE:
```python
        max_convergence_rounds: int = 2,
        ontology: Any = None,
        judge_policy: VerifierJudgePolicy | None = None,
    ) -> None:
```
SEARCH:
```python
        # behavior verbatim for every existing call site.
        self._ontology = ontology
```
REPLACE:
```python
        # behavior verbatim for every existing call site.
        self._ontology = ontology
        # AD-1327 (optional, Dependency Inversion): when wired, the judge call requests the
        # policy's tier and each answered verdict records its judge. None keeps the
        # pre-AD-1327 request (tier "standard") and records no judge.
        self._judge_policy = judge_policy
```

8d. Two helpers (before `_build_trace_section`).

SEARCH:
```python
    async def _build_trace_section(self, trace_ref: str | None) -> str:
```
REPLACE:
```python
    def _judge_tier(self) -> str:
        """AD-1327: the tier the judge call requests: ``standard`` unless the policy names the verifier tier."""
        return "standard" if self._judge_policy is None else self._judge_policy.request_tier

    def _judge_provenance(self, response: Any) -> JudgeProvenance | None:
        """AD-1327: the judge record for ``response``, or None when no policy is wired.

        Reads what the LLM client reports answered (``LLMResponse.answered_tier`` and
        ``answered_model``), never the model it sent. ``getattr``: the verifier's LLM is
        duck-typed (test doubles return other response objects); a response without them
        is recorded as unknown and not shown to come from the requested tier.
        """
        if self._judge_policy is None:
            return None
        return self._judge_policy.provenance(
            answered_tier=getattr(response, "answered_tier", None),
            answered_model=getattr(response, "answered_model", None),
        )

    async def _build_trace_section(self, trace_ref: str | None) -> str:
```

8e. `verify`.

SEARCH:
```python
        request = LLMRequest(
            prompt=prompt,
            system_prompt=self._JUDGE_SYSTEM_PROMPT,
            tier="standard",
        )
        try:
            response = await self._llm.complete(request)
            verdict = self._parse_verdict(getattr(response, "content", ""), verifier_id)
        except Exception:
```
REPLACE:
```python
        request_tier = self._judge_tier()
        request = LLMRequest(
            prompt=prompt,
            system_prompt=self._JUDGE_SYSTEM_PROMPT,
            tier=request_tier,
        )
        try:
            response = await self._llm.complete(request)
            verdict = self._parse_verdict(getattr(response, "content", ""), verifier_id)
            verdict = replace(verdict, judge=self._judge_provenance(response))
        except Exception:
```

8f. `verify_for_session`.

SEARCH:
```python
                failure_code="independent_verifier_unavailable",
            )
        try:
            result_text = self._session_result_text(
```
REPLACE:
```python
                failure_code="independent_verifier_unavailable",
            )
        judge: JudgeProvenance | None = None
        try:
            result_text = self._session_result_text(
```
SEARCH:
```python
            response = await self._llm.complete(LLMRequest(
                prompt=prompt,
                system_prompt=self._JUDGE_SYSTEM_PROMPT,
                tier="standard",
            ))
            tokens = self._session_tokens(getattr(response, "tokens_used", None))
            content = getattr(response, "content", None)
            return self._parse_session_verdict(content, verifier_id, tokens)
        except asyncio.CancelledError:
            raise
        except ValueError:
            return SessionVerificationPass(
                status="malformed",
                accepted=False,
                confidence=0.0,
                critique="Verifier response was malformed.",
                verifier_agent_id=verifier_id,
                tokens_used=0,
                failure_code="verification_defect",
            )
```
REPLACE:
```python
            response = await self._llm.complete(LLMRequest(
                prompt=prompt,
                system_prompt=self._JUDGE_SYSTEM_PROMPT,
                tier=self._judge_tier(),
            ))
            judge = self._judge_provenance(response)
            tokens = self._session_tokens(getattr(response, "tokens_used", None))
            content = getattr(response, "content", None)
            return replace(self._parse_session_verdict(content, verifier_id, tokens), judge=judge)
        except asyncio.CancelledError:
            raise
        except ValueError:
            return SessionVerificationPass(
                status="malformed",
                accepted=False,
                confidence=0.0,
                critique="Verifier response was malformed.",
                verifier_agent_id=verifier_id,
                tokens_used=0,
                failure_code="verification_defect",
                judge=judge,
            )
```
The judge prompt, system prompt, parsers and thresholds are untouched.

### Section 9 -- persistence: everywhere `criteria` goes, `judge` goes, omitted when absent

9a. `src/probos/cognitive/crew_finalizer.py`.

SEARCH:
```python
from probos.cognitive.crew_verdict import (
    CriterionVerdict,
    criteria_to_json,
    parse_criteria,
    validate_criteria,
)
```
REPLACE:
```python
from probos.cognitive.crew_verdict import (
    CriterionVerdict,
    JudgeProvenance,
    criteria_to_json,
    judge_to_json,
    parse_criteria,
    parse_judge,
    validate_criteria,
)
```
SEARCH:
```python
    criteria: tuple[CriterionVerdict, ...] | None = None

    @field_validator("criteria", mode="before")
    @classmethod
    def _validate_criteria(cls, value: object) -> tuple[CriterionVerdict, ...]:
        return parse_criteria(value)

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.criteria is None:
            # Absence is part of historical checkpoint bytes and trust identity.
            document.pop("criteria", None)
        return document
```
REPLACE:
```python
    criteria: tuple[CriterionVerdict, ...] | None = None
    judge: JudgeProvenance | None = None

    @field_validator("criteria", mode="before")
    @classmethod
    def _validate_criteria(cls, value: object) -> tuple[CriterionVerdict, ...]:
        return parse_criteria(value)

    @field_validator("judge", mode="before")
    @classmethod
    def _validate_judge(cls, value: object) -> JudgeProvenance:
        # AD-1327: a JSON object or a validated record; an explicit null is refused.
        return value if isinstance(value, JudgeProvenance) else parse_judge(value)

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.criteria is None:
            # Absence is part of historical checkpoint bytes and trust identity.
            document.pop("criteria", None)
        if self.judge is None:
            # AD-1327: the same rule for the judge record.
            document.pop("judge", None)
        return document
```
SEARCH:
```python
            failure_code=self.failure_code,
            criteria=self.criteria,
        )
```
REPLACE:
```python
            failure_code=self.failure_code,
            criteria=self.criteria,
            judge=self.judge,
        )
```
SEARCH:
```python
                **(
                    {"criteria": criteria_to_json(item.criteria)}
                    if item.criteria is not None else {}
                ),
            })
```
REPLACE:
```python
                **(
                    {"criteria": criteria_to_json(item.criteria)}
                    if item.criteria is not None else {}
                ),
                **({"judge": judge_to_json(item.judge)} if item.judge is not None else {}),
            })
```

9b. `src/probos/cognitive/crew_orchestrator.py` (owned legacy review payload write `:3966-3982`, read `:4079-4113`).

SEARCH:
```python
from probos.cognitive.crew_verdict import criteria_to_json, parse_criteria
```
REPLACE:
```python
from probos.cognitive.crew_verdict import criteria_to_json, judge_to_json, parse_criteria, parse_judge
```
SEARCH:
```python
            "criteria": (
                criteria_to_json(verdict.criteria)
                if verdict.criteria is not None
                else None
            ),
            "rounds": outcome.rounds,
```
REPLACE:
```python
            "criteria": (
                criteria_to_json(verdict.criteria)
                if verdict.criteria is not None
                else None
            ),
            **({"judge": judge_to_json(verdict.judge)} if verdict.judge is not None else {}),
            "rounds": outcome.rounds,
```
SEARCH:
```python
            verification_defect=verification["verification_defect"],
            criteria=criteria,
        )
```
REPLACE:
```python
            verification_defect=verification["verification_defect"],
            criteria=criteria,
            judge=parse_judge(verification["judge"]) if "judge" in verification else None,
        )
```

9c. `src/probos/cognitive/crew_synth.py` (three sites: episode `:177-192`, parent provenance `:1063-1083`, collaboration episode `:1265-1279`).

SEARCH:
```python
from probos.cognitive.crew_verdict import criteria_to_json
```
REPLACE:
```python
from probos.cognitive.crew_verdict import criteria_to_json, judge_to_json
```
SEARCH:
```python
                "status": outcome.status,
                **(
                    {"criteria": criteria_to_json(outcome.verdict.criteria)}
                    if outcome.verdict.criteria is not None
                    else {}
                ),
```
REPLACE:
```python
                "status": outcome.status,
                **(
                    {"criteria": criteria_to_json(outcome.verdict.criteria)}
                    if outcome.verdict.criteria is not None
                    else {}
                ),
                **({"judge": judge_to_json(outcome.verdict.judge)} if outcome.verdict.judge is not None else {}),
```
SEARCH:
```python
                        "critique": oc.verdict.critique,
                        **(
                            {"criteria": criteria_to_json(oc.verdict.criteria)}
                            if oc.verdict.criteria is not None else {}
                        ),
```
REPLACE:
```python
                        "critique": oc.verdict.critique,
                        **(
                            {"criteria": criteria_to_json(oc.verdict.criteria)}
                            if oc.verdict.criteria is not None else {}
                        ),
                        **({"judge": judge_to_json(oc.verdict.judge)} if oc.verdict.judge is not None else {}),
```
SEARCH:
```python
                    "status": oc.status,
                    **(
                        {"criteria": criteria_to_json(oc.verdict.criteria)}
                        if oc.verdict.criteria is not None else {}
                    ),
```
REPLACE:
```python
                    "status": oc.status,
                    **(
                        {"criteria": criteria_to_json(oc.verdict.criteria)}
                        if oc.verdict.criteria is not None else {}
                    ),
                    **({"judge": judge_to_json(oc.verdict.judge)} if oc.verdict.judge is not None else {}),
```

9d. `src/probos/cognitive/crew_trust.py` (validate, never trust, a supplied judge; the hash covers the exact JSON as before).

SEARCH:
```python
from probos.cognitive.crew_verdict import parse_verdict_criteria
```
REPLACE:
```python
from probos.cognitive.crew_verdict import parse_judge, parse_verdict_criteria
```
SEARCH:
```python
        if "criteria" in verdict:
            try:
                parse_verdict_criteria(verdict)
            except ValueError as exc:
                raise ValueError("crew_trust_evidence_invalid") from exc
```
REPLACE:
```python
        if "criteria" in verdict:
            try:
                parse_verdict_criteria(verdict)
            except ValueError as exc:
                raise ValueError("crew_trust_evidence_invalid") from exc
        if "judge" in verdict:
            try:
                parse_judge(verdict["judge"])
            except ValueError as exc:
                raise ValueError("crew_trust_evidence_invalid") from exc
```
Not changed: the API projection (`routers/crew_tasks.py:113-119`, pinned by `tests/test_ad1245_verdict_assessment.py:433`) and `crew_session_projection.py`; trust weighting by independence (would change a trust control).

### Section 10 -- wiring and reports

10a. `src/probos/startup/finalize.py`, `_wire_crew_orchestrator`.

SEARCH:
```python
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.cognitive.swe_harness.agentic_loop import resolve_event_correlation_settings
```
REPLACE:
```python
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.cognitive.swe_harness.agentic_loop import resolve_event_correlation_settings
    from probos.cognitive.verifier_independence import (
        VERIFIER_REMEDIATION,
        VerifierJudgePolicy,
        verifier_independence_report,
    )
```
SEARCH:
```python
    verifier = SubtaskVerifier(
        llm_client=llm_client,
        work_item_store=work_item_store,
        agent_registry=registry,
        trust_network=trust_network,
        agentic_executor=agentic_executor,
        runtime=runtime,
        max_convergence_rounds=max_rounds,
        ontology=ontology,
    )
```
REPLACE:
```python
    # AD-1327: the judge tier and model, decided once from the config. The log line is
    # the runtime's record of whether the verifier shares a crew tier's model.
    judge_policy = VerifierJudgePolicy.from_cognitive(config.cognitive)
    independence, judge_report = verifier_independence_report(judge_policy)
    if independence == "independent":
        logger.info("AD-1327: crew verifier: %s", judge_report)
    else:
        logger.warning(
            "AD-1327: crew verifier: %s; each verdict records its judge model and this "
            "independence. %s",
            judge_report, VERIFIER_REMEDIATION,
        )
    verifier = SubtaskVerifier(
        llm_client=llm_client,
        work_item_store=work_item_store,
        agent_registry=registry,
        trust_network=trust_network,
        agentic_executor=agentic_executor,
        runtime=runtime,
        max_convergence_rounds=max_rounds,
        ontology=ontology,
        judge_policy=judge_policy,
    )
```

10b. `src/probos/startup/finalize.py`, `_wire_model_routing` (the verifier model's ceiling status is reported at wiring like the text tiers').

SEARCH:
```python
    with exactly the models the operator configured for the text tiers
    (``TEXT_TIERS``; the vision tiers bypass the router, BF-273), priced from
```
REPLACE:
```python
    with exactly the models the operator configured for the text tiers
    (``TEXT_TIERS``; the vision tiers bypass the router, BF-273) and, when
    ``llm_model_verifier`` is set, the verifier tier (AD-1327, ``routed_tiers``), priced from
```
SEARCH:
```python
    from probos.cognitive.model_router import build_model_routing

    router = build_model_routing(config, emit_event=runtime.emit_event)
```
REPLACE:
```python
    from probos.cognitive.model_router import build_model_routing, routed_tiers

    router = build_model_routing(config, emit_event=runtime.emit_event)
```
SEARCH:
```python
    router.report_cost_ceiling(TEXT_TIERS)
```
REPLACE:
```python
    router.report_cost_ceiling(routed_tiers(config.cognitive))
```

10c. `src/probos/__main__.py`, `_create_llm_client`.

SEARCH:
```python
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient, TEXT_TIERS, _LLM_TIERS
from probos.cognitive.model_router import build_model_routing, ceiling_denials
```
REPLACE:
```python
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient, _LLM_TIERS
from probos.cognitive.model_router import build_model_routing, ceiling_denials, routed_tiers
from probos.cognitive.verifier_independence import VerifierJudgePolicy, verifier_independence_report
```
(`TEXT_TIERS` has one other use in this file, `:321`, replaced below; `provider_setup.TEXT_TIERS` uses are unaffected.)

SEARCH:
```python
    denied = {} if router is None else router.denials(TEXT_TIERS)
```
REPLACE:
```python
    denied = {} if router is None else router.denials(routed_tiers(cog))
```
SEARCH:
```python
        else:
            console.print(f"  [yellow]\u2717[/yellow] LLM {tier}: {where} unreachable")

    # BF-886 A-1: a tier the cost ceiling excludes was not probed. Its exclusion
```
REPLACE:
```python
        else:
            console.print(f"  [yellow]\u2717[/yellow] LLM {tier}: {where} unreachable")

    # AD-1327: while the crew orchestrator is on (the crew verifier is built only then),
    # say whether the verifier judges with a model the crew also runs on.
    if config.agentic_dispatch.orchestrator_enabled:
        independence, detail = verifier_independence_report(VerifierJudgePolicy.from_cognitive(cog))
        shown = escape(provider_setup.redact_keys(f"Crew verifier: {detail}", keys))
        mark = "[green]\u2713[/green]" if independence == "independent" else "[yellow]\u26a0[/yellow]"
        console.print(f"  {mark} {shown}")

    # BF-886 A-1: a tier the cost ceiling excludes was not probed. Its exclusion
```

10d. NEW `src/probos/doctor/checks/verifier_check.py`.

```python
"""AD-1327 (#1511): does the crew verifier judge with a model the crew also runs on?

Reads the configuration only and sends no request (``llm_tiers`` probes the
verifier tier when ``cognitive.llm_model_verifier`` is set). With the crew
orchestrator off the verifier never runs, so the result is OK and says so. With
it on: OK when the judge model is of a different family from every crew tier's
model; WARN for the same model, the same family, or a family not known. Never
FAIL: a shared judge weakens verification, it does not break the installation.
Each configured key's forms are redacted from the message, as in ``llm_tiers``.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos import provider_setup as ps
from probos.cognitive.verifier_independence import (
    VERIFIER_REMEDIATION,
    VerifierJudgePolicy,
    verifier_independence_report,
)
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _VerifierIndependenceCheck:
    name: str = "verifier_independence"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Crew verifier independence: skipped (config unavailable)",
            )
        cognitive = ctx.config.cognitive
        independence, detail = verifier_independence_report(VerifierJudgePolicy.from_cognitive(cognitive))
        detail = ps.redact_keys(detail, ps.configured_api_keys(cognitive))
        if not ctx.config.agentic_dispatch.orchestrator_enabled:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message=f"Crew verifier: not in use (agentic_dispatch.orchestrator_enabled is off); configured: {detail}",
            )
        if independence == "independent":
            return CheckResult(outcome=CheckOutcome.OK, message=f"Crew verifier: {detail}")
        return CheckResult(
            outcome=CheckOutcome.WARN,
            message=f"Crew verifier: {detail}",
            remediation=VERIFIER_REMEDIATION,
        )


register_check(_VerifierIndependenceCheck())
```

10e. `src/probos/doctor/checks/__init__.py` (after `extras_check`, so the AD-1137 order "extras follows the LLM check" holds).

SEARCH:
```python
    extras_check,
    nats_check,
```
REPLACE:
```python
    extras_check,
    verifier_check,
    nats_check,
```

### Section 11 -- existing tests that pin the tier set or the verdict shape (update; each is a deliberate contract change)

11a. `tests/test_ad1324_router_floor.py`:
SEARCH:
```python
    assert llm_mod._LLM_TIERS == (
        "fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen",
    )
```
REPLACE:
```python
    assert llm_mod._LLM_TIERS == (
        "fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier",
    )
```
11b. `tests/test_ad706c2_compute_use.py`:
SEARCH:
```python
    assert _LLM_TIERS == ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")
```
REPLACE:
```python
    assert _LLM_TIERS == ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier")
```
11c. `tests/test_ad732_vision_tier.py`:
SEARCH:
```python
    assert set(_LLM_TIERS) == {"fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen"}
```
REPLACE:
```python
    assert set(_LLM_TIERS) == {"fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier"}
```
11d. `tests/test_per_tier_llm.py`:
SEARCH:
```python
            assert set(result.keys()) == {"fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen"}
```
REPLACE:
```python
            assert set(result.keys()) == {"fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier"}
```
11e. `tests/test_bf069_llm_health.py` (three sites; `:66` is required, otherwise the verifier stays operational and "offline" becomes "degraded").
SEARCH:
```python
        client._consecutive_failures = {t: 0 for t in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")}
        client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")}
```
REPLACE:
```python
        client._consecutive_failures = {t: 0 for t in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier")}
        client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier")}
```
SEARCH:
```python
        for tier in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen"):
            client._consecutive_failures[tier] = 3
```
REPLACE:
```python
        for tier in ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier"):
            client._consecutive_failures[tier] = 3
```
SEARCH:
```python
        _tiers = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")
```
REPLACE:
```python
        _tiers = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", "verifier")
```
11f. `tests/test_ad1135_provider_setup.py` (the independent oracle must know the verifier's own check, or it reads True for an unknown tier, the B8 trap).
SEARCH:
```python
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
REPLACE:
```python
from probos.cognitive.verifier_independence import is_verifier_tier_configured
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
SEARCH:
```python
def _consumer_configured(config: object, tier: str) -> bool:
    # What the tier's runtime consumer reads: image_gen_dispatch.py:142 for image_gen, else vision_dispatch's check.
    return is_image_gen_tier_configured(config) if tier == "image_gen" else is_vision_tier_configured(config, tier)
```
REPLACE:
```python
def _consumer_configured(config: object, tier: str) -> bool:
    # What the tier's runtime consumer reads: image_gen_dispatch.py:142 for image_gen, the crew verifier's own
    # check for verifier (AD-1327; vision_dispatch's check reads True for a tier it does not know, B8), else
    # vision_dispatch's check.
    if tier == "verifier":
        return is_verifier_tier_configured(config)
    return is_image_gen_tier_configured(config) if tier == "image_gen" else is_vision_tier_configured(config, tier)
```
SEARCH:
```python
    assert {tier for tier, endpoint in endpoints.items() if endpoint.inherited} == {"vision", "compute_use", "image_gen"}
```
REPLACE:
```python
    assert {tier for tier, endpoint in endpoints.items() if endpoint.inherited} == {"vision", "compute_use", "image_gen", "verifier"}
```
SEARCH:
```python
        assert answers == [False, False, False, True]  # premise: each check gives both answers across these shapes
```
REPLACE:
```python
        # AD-1327: the verifier tier, like the text tiers, needs only a model (its URL falls back to the shared one).
        expected = [False, True, False, True] if tier == "verifier" else [False, False, False, True]
        assert answers == expected  # premise: each check gives both answers across these shapes
```
11g. `tests/test_ad1135_setup_cli.py`:
SEARCH:
```python
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
REPLACE:
```python
from probos.cognitive.verifier_independence import is_verifier_tier_configured
from probos.cognitive.vision_dispatch import is_vision_tier_configured
```
SEARCH:
```python
    return {
        tier: is_image_gen_tier_configured(cognitive) if tier == "image_gen" else is_vision_tier_configured(cognitive, tier)
        for tier in _OPTIONAL_TIERS
    }
```
REPLACE:
```python
    return {
        tier: (
            is_image_gen_tier_configured(cognitive) if tier == "image_gen"
            else is_verifier_tier_configured(cognitive) if tier == "verifier"
            else is_vision_tier_configured(cognitive, tier)
        )
        for tier in _OPTIONAL_TIERS
    }
```
11h. `tests/test_ad1244_verdict_criteria.py` (the field-order pin; positional constructors stay valid):
SEARCH:
```python
    assert [field.name for field in fields(VerificationVerdict)] == [
        "accepted", "confidence", "critique", "verifier_agent_id", "verification_defect", "criteria",
    ]
    assert fields(SessionVerificationPass)[-1].name == "criteria"
```
REPLACE:
```python
    assert [field.name for field in fields(VerificationVerdict)] == [
        "accepted", "confidence", "critique", "verifier_agent_id", "verification_defect", "criteria", "judge",
    ]
    assert [field.name for field in fields(SessionVerificationPass)][-2:] == ["criteria", "judge"]  # AD-1327 appends
    assert legacy.judge is None and session.judge is None
```

11i. `tests/test_ad1135_provider_setup.py:701` (Milestone 3, with Section 10). The census counts every module whose imports **or string constants, docstrings included** contain `provider_setup`. Section 10's `doctor/checks/verifier_check.py` imports it as `llm_check.py` does (a deliberate contract change: the doctor's providers check runs in the operator's CLI). Section 6's module must not appear: its docstrings say "the setup module" instead (already so above); do not reintroduce the token there.
SEARCH:
```python
    assert importers == {"__main__.py", "doctor/runner.py", "doctor/checks/llm_check.py"}
```
REPLACE:
```python
    # AD-1327: the crew verifier's doctor check reads setup's tier checks and key redaction, as llm_check does.
    assert importers == {"__main__.py", "doctor/runner.py", "doctor/checks/llm_check.py", "doctor/checks/verifier_check.py"}
```
11j. `tests/test_ad1270e1_config_facade.py:1548` (Milestone 3, with Section 12). Section 1 adds five `CognitiveConfig` fields; no other count in this test moves (measured).
SEARCH:
```python
    # AD-1316 adds three default-off effect-broker controls (1836 -> 1839).
    assert counts["field_definitions"] == 1839  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1316 adds three default-off effect-broker controls (1836 -> 1839).
    # AD-1327 adds the five cognitive.*_verifier fields of the crew verifier tier (1839 -> 1844).
    assert counts["field_definitions"] == 1844  # AD-1206 intentionally adds github_repository.
```
11k. `tests/fixtures/ad1152_agentic_off_golden.json:15, :17` (Milestone 3; fails `test_default_off_matches_pinned_base` and `test_default_off_golden_pins_only_descriptor_owner_platform[linux|win32]`). `default_config_sha256` is a change detector over the whole default `SystemConfig` dump (`tests/test_ad1152_agentic_correlation.py:468`), so any new config field moves it; `observation_sha256` is the digest of the observation that contains it. This is a refresh, not regenerating an oracle from the code under test: the orchestrator ran the test's own `_off_observation` on the applied tree and it differs from the golden on exactly one key, `default_config_sha256`; every request, event and constructor pin is unchanged. Precedent: AD-1324 (`e7b7ee71`) changed exactly these two lines for its config fields, as did AD-1315 and AD-1321..1325. Each old value occurs once in the file. If the Builder's tree differs from the reviewed Sections 1-10 in any default, recompute both with `_off_observation` and confirm the one-key diff again before pasting; any second differing key is a hard stop.
SEARCH:
```json
  "observation_sha256": "039a67f0e84be167db712c5ce83f40c9f38613decac7b86ba80236b3b692bbb2",
```
REPLACE:
```json
  "observation_sha256": "7c11abbd661ba480b0f9b5557a881c1813ed8f30d0ff59127d9f520bd0b0c032",
```
SEARCH:
```json
    "default_config_sha256": "87f40ca6357825bf248fb9a58d2b25bf59eba04b0c0285e8b9c3fcb539272499",
```
REPLACE:
```json
    "default_config_sha256": "149a63292ffd30448f94346195781ec6ebf5c28de4df9c2ba34055788d004643",
```
11l. `tests/test_per_tier_llm.py:256-264` `test_models_property_reflects_tier_configs` (Milestone 1; the full `client.models` dict; 11d is the other full pin in this file, `:287`).
SEARCH:
```python
            "image_gen": None,  # AD-730-3: image_gen peer tier, unconfigured by default
        }
```
REPLACE:
```python
            "image_gen": None,  # AD-730-3: image_gen peer tier, unconfigured by default
            "verifier": None,  # AD-1327: verifier tier, unconfigured by default
        }
```
11m. `tests/test_ad1325_boundaries.py:227` (Milestone 1, with 2f). The test compares `asdict(LLMResponse(...))` byte-for-byte with `tests/fixtures/ad1325_ad1324_flag_off_base.json`, an observation recorded at base `a6ec4d0e` whose sha256 the test's comment records (`:237`). 2f's two fields would add `"answered_model":null,"answered_tier":null`. Keep the base fixture and its hash as the base evidence and project the response onto the fields that existed then; test 45 pins the new defaults. Do **not** edit the fixture.
SEARCH:
```python
        "request": asdict(request),
        "response": asdict(response),
```
REPLACE:
```python
        "request": asdict(request),
        # AD-1327 appended two provenance fields (default None) after this base observation was
        # recorded; the fixture stays the exact base bytes, and test_ad1327_verifier_tier pins the defaults.
        "response": {
            key: value for key, value in asdict(response).items()
            if key not in ("answered_tier", "answered_model")
        },
```

### Section 12 -- generated docs (regenerate, then review the diff)

```
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
```
Expected diffs, and nothing else (anything else is a hard stop):
- `docs/development/config-reference.md`: five rows after `llm_api_format_image_gen` (`config-reference.md:129`) with the Section 1 descriptions.
- `docs/development/config-facade-baseline.yaml`: the five `CognitiveConfig` field rows after `llm_api_format_image_gen` (`:1086` region), and the digests and counts derived from them (`schema_sha256` of `CognitiveConfig` and of models embedding it, `canonical_dump_sha256`, `surface_counts`). Run with `PROBOS_LLM_URL` unset.
- `config/profiles/`: no change. `check_config_profiles.py` gates default-False booleans and environment reads (`scripts/check_config_profiles.py:6-27`); this AD adds neither, and no profile names an `llm_` key (search below).
- `docs/development/architecture-baseline.yaml`: **must stay byte-identical** (sha pinned at `tests/test_ad1324_srp_layout.py:19`). The checker stores no magnitudes (`architecture-baseline.yaml:5-6`); `SubtaskVerifier` and `OpenAICompatibleClient` are frozen debt rows (`:494`, `:581`); the new classes are small and import only cognitive modules (`doctor` and `__main__` are outside the layer map, `:12-17`).

### Section 13 -- trackers

13a. `PROGRESS.md`: AD-1327 entry on top, and BF-889 flipped to shipped (facts from PR #1521's body: canonical receipt and mutation campaign).

SEARCH:
```markdown
# ProbOS Progress

**BF-889 OPEN (2026-10-12), #1515 -- read_page reads real page text, states its cut, and reads a long page in sections; implementation candidate.**
```
REPLACE (fill the bracketed counts from the run; leave nothing bracketed):
```markdown
# ProbOS Progress

**AD-1327 OPEN (2026-10-13), #1511 -- the crew verifier can judge with its own model and records when it judges itself; implementation candidate.** A `verifier` LLM tier (`llm_model_verifier`, `llm_base_url_verifier`, `llm_api_key_verifier`, `llm_timeout_verifier`, `llm_api_format_verifier`) is in `_LLM_TIERS` and outside `_TIER_ORDER`, so AD-1324's tier choice and stakes floor never offer it; a verifier request falls back to standard, fast, deep. Unset, `SubtaskVerifier` sends the pre-AD-1327 request (`tier="standard"`, pinned by a golden test). When set, the model router registers the verifier model under its own tier, so the cost ceiling governs its calls and probe, and verifier attempts are routed exact. Each answered verdict carries `judge` (tier, model, independence `same_model`/`same_family`/`unknown`/`independent`, fallback), persisted wherever `criteria` is and omitted when absent, so older rows keep their bytes and trust-evidence hashes; a fallback verdict never records `independent`. The judge's model is the id the provider's reply named (new `LLMResponse.answered_model`; absent or unusable, including text that is not strict UTF-8, = `""`, `unknown`), and `fallback` means the requested tier's attempt did not answer (new `LLMResponse.answered_tier`, kept on cache replays), never a model-id comparison. A configured verifier shares a pool only when every other tier on its URL has its key, so its requests, probe and every pool rebuild carry its own key (review rounds 1 and 2: F1-F5). While `agentic_dispatch.orchestrator_enabled` is on, the boot banner, a runtime log line and the new `verifier_independence` doctor check report the outcome (WARN, never FAIL, unless independent). Tests: [N] new in `tests/test_ad1327_verifier_tier.py` and `tests/test_ad1327_verifier_independence.py`; [M] mutants killed of [K]. Contract `prompts/ad-1327-crew-verifier-tier-and-independence.md`.

**BF-889 SHIPPED (2026-10-13), #1515, PR #1521, merge commit `692e1df6` -- read_page reads real page text, states its cut, and reads a long page in sections.** Canonical gate `bf889-1515` exit 0, 44,461 passed, 60 skipped, on HEAD `95a928e7` (tree `06991093`, receipt sha256 `5800d881b7814130b2b8601c085d4afaf288584de08f23fe43b1cedfeb3fcfd8`, `tree_changed=false`); mutation campaign of record 60 of 60 killed, none inert or invalid; Diff Reviewer READY in round 3.
```

13b. `DECISIONS.md` (top of Era V).

SEARCH:
```markdown
## Era V — Civilization (Phases 31-36)

### BF-889 -- read_page reads a long page in sections (2026-10-12, #1515)
```
REPLACE:
```markdown
## Era V — Civilization (Phases 31-36)

### AD-1327 -- The crew verifier names its own model and records when it judges itself (2026-10-13, #1511)

- *Tier.* `verifier` is in `_LLM_TIERS` and outside `_TIER_ORDER`: agents cannot choose it and the stakes floor never ranks it, but a verifier request falls back to standard, fast, deep, and an unconfigured verifier tier is skipped. Unset, the crew verifier sends its pre-AD-1327 `standard` request (golden test). Rejected: inside `_TIER_ORDER` (agent-eligible); a second client (duplicated pools and health).
- *Routing.* When set, the verifier model is registered under its own router tier (`model_router.routed_tiers`) and verifier attempts are routed `exact_tier`, so the cost ceiling governs verifier calls and probes, and no crew model is sent to the verifier endpoint; the router's any-tier fallback no longer lets a non-text tier's model answer a crew request. Rejected: bypassing the router as vision does (BF-273), which would take verifier calls out of the cost ceiling.
- *Sameness.* Normalised model id (not endpoint) against the fast, standard and deep models; family from `model_registry.model_family` (catalog provider, else ten markers; none or two = unknown). `same_model`, `same_family` and `unknown` are degraded; only `independent` is not. Rejected: reusing `copilot_adapter._classify_provider` (private display label; buckets qwen and deepseek together).
- *Record.* `judge` (`JudgeProvenance`: tier, model, independence, fallback) on both verdict types, persisted beside `criteria` and omitted when absent (the AD-1244 rule), so older rows keep their bytes and evidence hashes. A pre-AD-1327 build refuses rows with `judge`, as it refuses `criteria`; that fails closed.
- *Provenance (review round 1).* The judge's `model` is the provider's reply `model` (`LLMResponse.answered_model`, set by both transports; absent, non-text, NUL, over 256 characters or not strict UTF-8 = `""` and `unknown`; one predicate, `crew_verdict.is_persistable_judge_model`, bounds both the reply and a persisted record, because the strict checkpoint, owned-steps and trust encoders refuse a lone surrogate (review round 2)), never the id sent; `LLMResponse.model` keeps meaning "sent". `fallback` is True unless the requested tier's attempt answered (`LLMResponse.answered_tier`, set in the attempt loop before the cache write and copied by both cache replays); a response that does not say is degraded. Rejected: fallback by model-id inequality (a 503 on the dedicated endpoint with a same-id standard answer read as no fallback); the router's served tier (None on routed non-exact attempts); replacing `LLMResponse.model` (every token and log consumer would change).
- *Credential (review rounds 1 and 2).* A configured verifier shares a pool only when every other tier on that `base_url|api_format` has its key; otherwise it gets its own pool (`|verifier`, a constant; no key in pool names), so its requests, probe, refresh, in-flight cap and breaker use its key. Round 2: any tier on a pool rebuilds it with its own key in a BF-612 refresh, so comparing with the first tier only was not enough. Rejected: always isolating (a second pool, probe and breaker in the single-key configuration); rebuilding with the pool's original key (changes refresh for every tier); a per-request header (the shared pool's failure state and probe reuse would still stand for the verifier); credential-aware pooling for every tier (changes existing tiers; out of scope). Existing per-tier keys on a shared URL keep the first tier's key; that predates AD-1327 and is reported separately.
- *Reports.* Banner line, runtime log and the `verifier_independence` doctor check report only while `agentic_dispatch.orchestrator_enabled` (the verifier's only consumer); otherwise doctor says it is not in use, keeping the AD-1137 quickstart's "All checks passed.". WARN, never FAIL.
- Contract `prompts/ad-1327-crew-verifier-tier-and-independence.md`.

### BF-889 -- read_page reads a long page in sections (2026-10-12, #1515)
```

13c. `docs/development/roadmap.md`: no AD-1327 row exists (search below); add none.

---

## Tests

Harnesses to reuse (do not invent new mock chains):
- Client over HTTP: the `_build_client` monkeypatch with `httpx.MockTransport` in `tests/test_ad1324_router_floor.py:29-58` and `_wired` `:75-87`. Write `_FakeEndpoints` that records `(request.url.host, body["model"])` and returns the same 200 body, with an opt-in per-host failure (raise `httpx.ConnectError("down", request=request)` after recording). **Review round 1:** its reply carries `"model": body["model"]` (an honest provider echo) in both test files, or the D9 rule records `""` and test 25 fails for the wrong reason.
- Verifier: `_judge` in `tests/test_ad1245_verdict_assessment.py:67-98` (`_Registry`, `_Agent`, `_ScriptedLLM`, `_StaticAgenticExecutor` from `tests/test_ad1126_verified_finalization.py`; `_FakeStore`, `_result` from `tests/test_ad860_crew_verifier.py`). Add a `_FakeJudgeLLM` that returns `probos.types.LLMResponse(content=..., model=<name>, tokens_used=3)` and records each `LLMRequest`. **Review round 1:** it carries what the real client carries, `answered_model=<name>` and `answered_tier=request.tier`, unless built with `provenance=False`, which returns the plain response (the absent-provenance case).
- Seam doubles (review round 1, tests 42-48). Do not monkeypatch `_build_client`, which drops the Authorization header. Either (a) a loopback `http.server.ThreadingHTTPServer` on `127.0.0.1:0` in a daemon thread, shut down in the fixture's teardown, with the first path segment choosing the behaviour (the harness of `logs/architect/probe_ad1327_r1_findings.py:29-55`: record `path`, `Authorization` and body `model`; per segment `status` and `echo`, where `...` omits the field); or (b) for unit tests, patch `probos.cognitive.llm_client.httpx.AsyncClient` with a subclass whose `__init__` passes `transport=httpx.MockTransport(handler)`, so the real `_build_client` still bakes the real headers. Under (a), `monkeypatch.delenv` `PROBOS_LLM_URL`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (and their lower-case forms), or a proxy could intercept loopback.
- Persistence: `_historical_verdict`, `_canonical`, `_round`, `_verification`, `_derive` in `tests/test_ad1244_verdict_criteria.py:316-402`; the owned legacy pipeline in `tests/test_ad1192_owned_steps_finalization.py:1367` with its `_Verifier` (`:132-150`).
- Probe short-circuit: `tests/test_ad742a_vision_fast_tier.py:145-160`. Banner: `_Connectivity` in `tests/test_ad1137_doctor.py:1303-1313`.
- Every `_Fake*` asserts its own premise (it was called, with the host or tier the test means), and each "never" test has a negative control that shows the probe can see the thing it says is absent.

### `tests/test_ad1327_verifier_tier.py` (Milestone 1)

1. `test_verifier_tier_is_in_llm_tiers_and_outside_the_text_chain` -- `VERIFIER_TIER == "verifier"`, in `_LLM_TIERS`, not in `_TIER_ORDER`; `TEXT_TIERS is _TIER_ORDER`; `provider_setup.OPTIONAL_TIERS[-1] == "verifier"`; `list(TIER_CONFIGURED_CHECKS) == list(OPTIONAL_TIERS)`.
2. `test_tier_config_verifier_unset_has_no_model_and_the_shared_endpoint` -- with `llm_base_url_standard` set (premise: standard's URL differs from the shared one), `tier_config("verifier")` has model `None` and the shared URL and key.
3. `test_tier_config_verifier_set_uses_its_own_fields_then_the_shared_ones` -- all five fields set, then only the model.
4. `test_blank_verifier_model_is_unset` -- `""`, `"   "` give `None`; `"m"` stays.
5. `test_client_state_covers_every_tier_including_verifier` -- key sets of `_tier_configs`, `_consecutive_failures`, `_consecutive_successes`, `_request_timestamps`, `_consecutive_429s`, `models`, `tier_info()`, `get_health_status()["tiers"]` all equal `set(_LLM_TIERS)`.
6. `test_unset_verifier_tier_is_not_probed` -- `check_connectivity()` gives `results["verifier"] is False` and no `_check_endpoint("verifier")`; negative control: with a verifier model **and its own base URL** set it is probed (a tier on an already-checked endpoint reuses that result without a call, `llm_client.py:1159-1160`).
7. `test_unset_verifier_tier_request_is_sent_down_the_standard_chain` -- separate hosts per tier; `complete(tier="verifier")` sends exactly one body, to the standard host, with the standard model, and that body equals the body `complete(tier="standard")` sends.
8. `test_configured_verifier_request_goes_to_its_endpoint_with_its_model`.
9. `test_verifier_falls_back_to_standard_then_fast_then_deep` -- judge and standard hosts fail; the hosts' first appearances, in order, are judge, standard, fast (a failed endpoint may be retried once after a pool refresh, BF-665); the response model is fast's; deep's host is never contacted.
10. `test_agent_tier_choice_and_stakes_floor_never_offer_verifier` -- `"verifier" not in tier_policy.TIER_RANK`; `TierChoiceConfig(stakes_floor={"high": "verifier"}).stakes_floor == {}`; `model_router._tier_rank("verifier") == -1`.
11. `test_routed_tiers_add_the_verifier_only_when_configured` -- unset returns the `TEXT_TIERS` object itself (`is`); set returns `(*TEXT_TIERS, "verifier")`.
12. `test_build_model_routing_registers_the_verifier_model_under_its_own_tier` -- `by_tier("verifier")` names the verifier model; unset: no `verifier` entry and the registry equals today's (`by_tier` per text tier).
13. `test_verifier_model_never_substitutes_for_a_crew_tier` -- `ModelRegistry.from_tier_models({"verifier": "claude-opus-4-6", "standard": "claude-sonnet-4-6"})` (verifier first: premise `registry.all()[0].tier == "verifier"`); `choose(tier="fast").chosen_model == "claude-sonnet-4-6"`; only a verifier entry: `choose(tier="fast").chosen_model == ""`.
14. `test_router_never_serves_a_verifier_attempt_with_a_crew_model` -- wired router, verifier configured at its own host; `registry.mark_unavailable(<verifier model>)` (premise: returns True); `complete(tier="verifier")` records no request to the judge host and one to the standard host.
15. `test_cost_ceiling_governs_verifier_calls_and_probe` -- ceiling 20, verifier `claude-opus-4-6` (catalog 75): `complete(tier="verifier")` sends only the standard model; `check_connectivity()` has no `"verifier"` key and no judge-host request; `ceiling_denials(config)` names `"verifier"`; negative control: ceiling 100 sends to the judge host.
16. `test_provider_setup_keeps_the_shared_url_for_a_verifier_with_a_model` -- `optional_tier_endpoints` text with `llm_model_verifier` and no own URL: `tiers_using_shared_url` names it; without a model it does not.
17. `test_settings_section_offers_the_verifier_fields` -- the three field paths are in `get_section("llm_tiers")`.

### `tests/test_ad1327_verifier_independence.py` (Milestones 2 and 3)

Classification and contract:
18. `test_model_family_and_normalisation` -- catalog names give `anthropic`; `gpt-5.1` openai; `ollama/qwen3:32b` alibaba; `deepseek-r1-distill-qwen-32b` None (two families); `mystery-7b` None; `""` None; `normalise_model_id("anthropic/Claude-Sonnet-4-6") == "claude-sonnet-4-6"`.
19. `test_classify_independence_outcomes` -- parametrised: same id after normalisation -> `same_model`; `claude-opus-4-6` vs claude crew -> `same_family`; `gpt-5.1` -> `independent`; `mystery-7b` -> `unknown`; known judge vs a crew with an unknown model -> `unknown`; empty judge or empty crew -> `unknown`; `unknown-judge-and-crew-families` (`mystery-7b` vs `("claude-sonnet-4-6", "mystery-8b")` -> `unknown`); `empty-crew-names-are-ignored` (`gpt-5.1` vs `("", "claude-sonnet-4-6")` -> `independent`).
20. `test_judge_provenance_validates_persisted_records` -- valid round trip through `judge_to_json`/`parse_judge`; refused: `None`, a list, `fallback: 1`, unknown independence, `fallback` with `independent`, empty model with a known outcome, NUL in model, 257-char model, a lone surrogate in model (`"gpt-\ud800-5"`, id `lone-surrogate-model`; review round 2), an extra key; and `parse_judge(<a JudgeProvenance instance>)` raises (only a JSON object is a persisted record).
21. `test_judge_provenance_tier_names_are_llm_tiers` -- `typing.get_args` of the `tier` annotation is a subset of `_LLM_TIERS` and contains `VERIFIER_TIER`.
22. `test_policy_from_cognitive` -- unset: tier `standard`, model = standard's, `assess() == "same_model"` for the default config; set: tier `verifier`; `VerifierJudgePolicy("deep", "m", ())` raises.
23. `test_provenance_never_raises_and_labels_fallback` (revised for D9/D10; keyword arguments `answered_tier`, `answered_model`) -- dedicated policy `("verifier", "gpt-5.1", claude crew)`: with `answered_tier="verifier"` and `answered_model` each of `None`, `7`, `""`, `"x\x00"`, `"a" * 257`, `"gpt-\ud800-5"` (review round 2): model `""`, `unknown`, `fallback False`; control: `"gpt-é-5"` (non-ASCII scalar text) is kept verbatim. `("verifier", "GPT-5.1")` -> model `"GPT-5.1"`, independent, not fallback. `("verifier", "claude-sonnet-4-6")` -> `same_model`, **not** fallback (the dedicated tier answered with a crew model's id). `("standard", "claude-sonnet-4-6")` -> `same_model`, fallback. `("standard", "gemini-2.5-pro")` -> fallback and `unknown` (premise: `classify_independence("gemini-2.5-pro", crew) == "independent"`). `(None, "gpt-5.1")` and `(7, "gpt-5.1")` -> fallback and `unknown` (provenance absent: never independent). Standard policy `("standard", "claude-sonnet-4-6", crew)`: `("standard", "claude-opus-4-6")` -> `("standard", "claude-opus-4-6", "same_model", False)` (its tier answered, whatever model the router chose); `("fast", "claude-sonnet-4-6")` -> fallback True. Comment wording (review round 2 cleanup, `tests/test_ad1327_verifier_independence.py:316` and `:322` on the candidate): above the standard-policy case write `# No verifier model is configured: the standard tier itself answering with another model id is not a fallback.`, and above the fast case `# Only the requested tier counts as answered: the fast tier answering for the standard policy (the fast/deep chain) is a fallback.` Do not say the standard tier's "chain" answering is not a fallback; the fast/deep chain is one.

Verifier:
24. `test_unset_verifier_requests_match_the_pre_ad1327_golden[legacy|session]` -- with `judge_policy=None` and with `VerifierJudgePolicy.from_cognitive(CognitiveConfig())`, `dataclasses.asdict(request)` without `id` equals the literal golden `{"prompt": <the prompt both calls built>, "system_prompt": SubtaskVerifier._JUDGE_SYSTEM_PROMPT, "tier": "standard", "temperature": 0.0, "top_p": None, "max_tokens": 2048, "tools": None, "tool_choice": "auto", "messages": None, "agent_id": None, "work_item_id": None, "min_tier": None, "tier_choice_reason": None, "exact_tier": False}`, and the two prompts are equal.
25. `test_configured_verifier_judges_through_config_client_and_verifier[legacy|session]` -- `CognitiveConfig(llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1", llm_model_*="claude-sonnet-4-6")`, a real `OpenAICompatibleClient(config=...)` over `_FakeEndpoints` (content = a valid verdict JSON), `SubtaskVerifier(..., judge_policy=VerifierJudgePolicy.from_cognitive(cfg))`: the judge host got the request with model `gpt-5.1`; `verdict.judge == JudgeProvenance(tier="verifier", model="gpt-5.1", independence="independent", fallback=False)` (`_FakeEndpoints` echoes the model sent).
26. `test_verifier_endpoint_down_falls_back_to_standard_and_labels_the_verdict` -- same, judge host fails (premise: it was attempted): answered by the standard model, `judge.fallback is True`, `independence == "same_model"`.
27. `test_wired_verifier_records_a_judge_on_every_answered_verdict` -- legacy accepted, legacy unparseable (defect), session accepted, session malformed: each has a judge.
28. `test_unanswered_verdicts_carry_no_judge` -- no independent verifier (both paths), LLM raises (both paths): `judge is None`.

Persistence:
29. `test_historical_verdict_without_judge_keeps_its_bytes` -- `_historical_verdict()` through `_VerdictRecord` -> `to_verdict()` -> `_verdict_document`: canonical bytes and sha256 equal; `"judge" not in` the document.
30. `test_judge_round_trips_through_the_verdict_record` -- `_verdict_document(SessionVerificationPass(..., judge=J))["judge"] == judge_to_json(J)`; `_VerdictRecord.model_validate(doc).to_verdict().judge == J`; a second round trip gives equal bytes.
31. `test_persisted_judge_is_validated_not_trusted` -- `_VerdictRecord.model_validate` refuses each invalid judge of test 20, including `"judge": None` and the lone surrogate (review round 2: shares `_INVALID`; a detector, as `_VerdictRecord` validates through `parse_judge` before any encoder).
32. `test_session_checkpoint_restart_restores_the_judge` -- through the finalizer checkpoint (`_convergence_from_checkpoint`, `crew_finalizer.py:2432-2503`) as `tests/test_ad1244_verdict_criteria.py:579` does for criteria.
33. `test_trust_evidence_rejects_an_invalid_judge_and_hashes_exact_json` -- `_derive` raises `crew_trust_evidence_invalid` for invalid judges (review round 2: the shared `_INVALID` now includes the lone surrogate; it raises the same token with or without the new bound, since `_exact_json_bytes` encodes strictly, `crew_trust.py:56-64`, so here it is a passing case, not a detector; tests 20 and 31 detect); with a valid judge, `evidence_sha256 == sha256(_canonical(evidence))`; without one, the hash equals today's (premise: the payload has no `judge` key).
34. `test_synth_provenance_and_episodes_carry_the_judge` -- harness `tests/test_ad1245_verdict_assessment.py:384-420`: a judged outcome has `judge` in the parent provenance `subtasks` entry and in the stored collaboration episode outcomes; an unjudged outcome has no `judge` key.
35. `test_owned_legacy_review_restores_the_judge` -- the `tests/test_ad1192_owned_steps_finalization.py:1367` pipeline with a `_JudgedVerifier(_Verifier)` returning a verdict with a judge: the recovered `ConvergenceOutcome.verdict.judge` equals it; the payload without a judge has no `judge` key; and the owned-legacy **episode** payload (`crew_synth._legacy_episode_payload`, `crew_synth.py:159`) carries `judge` when judged and no `judge` key otherwise. This test, not 34, kills mutation row 22: test 34 uses the other synthesis path and never reaches `_legacy_episode_payload`.

Reports and wiring (Milestone 3):
36. `test_doctor_reports_each_independence_outcome[same_model|same_family|independent|unknown]` -- orchestrator on; `same_model` (unset), `same_family` (`claude-opus-4-6`), `independent` (`gpt-5.1`), `unknown` (`mystery-7b`): WARN with `VERIFIER_REMEDIATION`, except `independent` OK; the message starts `Crew verifier: <outcome> --`; the source text is `(cognitive.llm_model_verifier)` when set and `(the standard tier; cognitive.llm_model_verifier is unset)` when unset.
37. `test_doctor_is_ok_when_the_orchestrator_is_off` -- default `SystemConfig()`: OK, message names "not in use"; `config=None`: WARN skipped.
38. `test_doctor_and_banner_redact_a_key_in_the_verifier_model` -- model and `llm_api_key_verifier` both a key (`ps.validate_key_transport` premise as `tests/test_ad1137_doctor.py:1393`): `ps.carries_key` false on both outputs.
39. `test_boot_banner_reports_each_independence_outcome` -- `_create_llm_client` with `_Connectivity`: the four lines (warning mark for all but `independent`); orchestrator off: no `Crew verifier` line.
40. `test_wired_crew_orchestrator_injects_the_judge_policy_and_logs_it` -- `tests/test_ad867_crew_orchestrator.py:176-179` config with the orchestrator on and a recording `SubtaskVerifier` monkeypatched onto `probos.cognitive.crew_verifier`: `judge_policy == VerifierJudgePolicy.from_cognitive(cfg.cognitive)`; caplog has one WARNING starting `AD-1327: crew verifier: same_model`; with `gpt-5.1`, INFO instead.
41. `test_quickstart_shape_doctor_has_no_new_warning` -- `_VerifierIndependenceCheck().run` on a context whose config has every text tier set to one model and the orchestrator off returns OK (keeps `tests/test_ad1137_quickstart_chain.py:276` true; that subprocess test still runs once in Milestone 3); and the registered check names include `verifier_independence` right after `extras` (premise for 10e).

Review round 1 -- client seams, in `tests/test_ad1327_verifier_tier.py` (Milestone 1; seam double (b) unless stated):
42. `test_verifier_with_its_own_key_on_a_shared_url_gets_its_own_pool` -- every tier on one URL, `llm_api_key="shared-k"`, `llm_model_verifier="gpt-5.1"`, `llm_api_key_verifier="judge-k"`. Then: `_client_key("verifier") == _client_key("standard") + "|verifier"`; `len(client._clients) == 2`; the verifier pool's `headers["Authorization"] == "Bearer judge-k"` and the standard pool's is `"Bearer shared-k"`; `_client_pool_states`, `_endpoint_failure_states` and `_endpoint_semaphores` each have the verifier key; no pool key contains `"judge-k"` or `"shared-k"`. Real requests: `complete(tier="verifier")` reaches the handler with `Bearer judge-k`, and `complete(tier="standard")` with `Bearer shared-k`. Probe: `check_connectivity()` sends a `gpt-5.1` request with `Bearer judge-k` (premise: the handler saw it). Controls, each with the pool key set equal to today's (`{f"{url}|openai"}` plus the vision/compute/image pools the config implies, computed with `_pool_base`): the same key for verifier and shared; the verifier unset while `llm_api_key_fast="fast-k"` (an unset verifier would otherwise differ from fast's pool key); the verifier with its own URL and key (own pool by URL, no suffix).
43. `test_refreshed_verifier_pool_keeps_the_verifier_key` -- with 42's config, `await client._refresh_client("verifier", observed_generation=<the verifier pool state's generation>)` returns True; the new verifier client's `Authorization` is still `Bearer judge-k`, and the standard pool object is the same object as before (identity).
44. `test_transports_carry_the_providers_model_id` -- `_call_openai` and `_call_ollama_native` (the `api/chat` body shape), each over a MockTransport whose reply `model` is each of: `"gpt-5.1-2025-11-13"` -> `answered_model` is that string; absent, `None`, `7` -> `""`; `"x\x00y"` and `"gpt-\ud800-5"` (review round 2) -> verbatim (the policy bounds it, test 23). The handler must send bytes it encoded itself, `content=json.dumps(payload).encode()` (ASCII escapes, as a provider's `\ud800` escape arrives), not `httpx.Response(json=...)`, which may encode non-ASCII strictly and raise before the client sees the reply. Every case: `response.model` is the id sent, and `response.answered_tier is None` (transports do not set it).
45. `test_attempt_loop_records_the_answering_tier_and_replays_keep_it` -- `LLMResponse(content="x")` has `answered_tier is None and answered_model is None` (default pin, 11m). `endpoints` fixture, verifier configured at its own host: `complete(tier="verifier")` -> `answered_tier == "verifier"`; with the judge host down -> `"standard"` (and `response.tier == "verifier"`, the requested tier). Then every host down, the same request again: the final cache replay has `cached is True` and the same `answered_tier` and `answered_model` as the response that filled it. The rate-limit replay (`rate_config=LLMRateConfig(rpm_standard=1, max_wait_seconds=0.0)`, `config_models/knowledge.py:238-247`; two `tier="standard"` calls inside the window, the second budget-exhausted; premise: the second response is `cached is True`) keeps both fields too. `dataclasses.replace(response, content="y")` keeps both.

Review round 1 -- one end-to-end test per finding, real `OpenAICompatibleClient` + real `SubtaskVerifier` (`_verifier`, `_run`), loopback server (seam double (a)), in `tests/test_ad1327_verifier_independence.py` (Milestone 2). Each asserts its premise: the server recorded the verifier request.
46. `test_f1_verifier_key_reaches_a_shared_endpoint_e2e[legacy|session]` -- every tier on one loopback URL, crew `claude-sonnet-4-6`, `llm_api_key="shared-k"`, `llm_model_verifier="gpt-5.1"`, `llm_api_key_verifier="judge-k"`. The server answers 401 to a `gpt-5.1` request without `Bearer judge-k`, and echoes the model otherwise. The `gpt-5.1` request carried `Bearer judge-k`; `verdict.judge == JudgeProvenance("verifier", "gpt-5.1", "independent", False)`. Negative control: with the server's 401 rule inverted (it refuses `Bearer judge-k`), the verdict is a `fallback` with `same_model`, which shows the check sees the header.
47. `test_f2_judge_record_names_the_providers_model_e2e[legacy|session]` -- verifier `claude-sonnet-4-6` on its own path, crew `gpt-5.1`. Reply echoes: `"gpt-5.1"` -> `("verifier", "gpt-5.1", "same_model", False)`; `None`, `7`, `"x\x00"`, `"a" * 257`, `"gpt-\ud800-5"` (review round 2; the loopback server's `json.dumps` sends it as a `\ud800` escape) and an absent field -> `("verifier", "", "unknown", False)`; control `"claude-sonnet-4-6"` -> `independent`. Premise each time: the server saw `claude-sonnet-4-6` sent.
48. `test_f3_dedicated_endpoint_down_same_model_id_is_a_fallback_e2e[legacy|session]` -- verifier and crew all `claude-sonnet-4-6`, the verifier on its own path answering 503, standard answering 200 with an honest echo: `judge == ("verifier", "claude-sonnet-4-6", "same_model", True)`. Premise: the server recorded the 503 verifier request before the standard one. Control: with the dedicated path up, `fallback` is False and the outcome is `same_model`.

Review round 2 (2026-10-13). The F4 recipe is the orchestrator's probe (`logs/architect/probe_ad1327_r2_findings.py:36-96`): one URL; `llm_api_key="a-k"` (fast's, and the shared key), `llm_api_key_standard="b-k"`, `llm_api_key_verifier="a-k"`, `llm_model_verifier` set; the server answers the first request for standard's model with 200 and empty content (BF-612 recovery) and every other request normally. `_FakeJudgeLLM` gains a keyword `answered_model: str | None = None` (default: its `model`), so a response can name a different model than the one sent.
49. `test_verifier_never_shares_a_pool_a_sibling_rebuilds_with_another_key` (`tests/test_ad1327_verifier_tier.py`, Milestone 1, seam double (b)) -- the F4 config. Premises: `_client_key("fast") == _client_key("standard")` and the pool's `Authorization` is `Bearer a-k` (fast built it). Then `_client_key("verifier") == _client_key("standard") + "|verifier"`. Through the real recovery: `complete(tier="standard")` with the handler's first standard reply empty (premise: the handler saw two standard requests and the standard pool state's generation is 1); then `complete(tier="verifier")` reaches the handler with `Bearer a-k`, and the verifier pool's header is still `Bearer a-k`. Controls: (i) all keys equal (`llm_api_key="a-k"` only): `_client_key("verifier") == _client_key("standard")` and the pool key set equals the unset-verifier set (one shared pool: one probe, one breaker); after the same standard recovery the verifier request carries `Bearer a-k`; (ii) verifier unset with `llm_api_key_standard="b-k"`: `_client_key("verifier")` is the base key (no suffix) and the pool key set equals the set with the verifier unset and one key.
50. `test_f4_sibling_refresh_keeps_the_verifier_key_e2e[legacy|session]` (`tests/test_ad1327_verifier_independence.py`, Milestone 2, loopback seam double (a)) -- real `OpenAICompatibleClient` + real `SubtaskVerifier` (`_verifier`, `_run`); crew `claude-sonnet-4-6`, `llm_model_verifier="gpt-5.1"`, the F4 keys. The server answers 401 to a `gpt-5.1` request without `Bearer a-k`, empties the first `claude-sonnet-4-6` reply, and echoes the model otherwise. First a standard request through the client (premise: two standard requests recorded, the second after the empty one), then the verifier path: the `gpt-5.1` request carried `Bearer a-k`; `verdict.judge == JudgeProvenance("verifier", "gpt-5.1", "independent", False)`. Controls: all keys equal -> the same judge, and `_client_key("verifier") == _client_key("standard")`; the verifier unset while standard has `b-k` -> the judge request is sent as `tier="standard"` with the standard model, judge `("standard", "claude-sonnet-4-6", "same_model", False)`.
51. `test_f5_unencodable_reply_model_still_writes_the_checkpoint` (`tests/test_ad1327_verifier_independence.py`, Milestone 2) -- (i) encoder level: premise `crew_finalizer._compact_bytes({"model": "gpt-\ud800-5"}, maximum=10_000, error="e")` raises `ValueError("e")` (the hazard is visible to this probe); `judge_to_json(_dedicated_policy().provenance(answered_tier="verifier", answered_model="gpt-\ud800-5"))` equals `{"tier": "verifier", "model": "", "independence": "unknown", "fallback": False}` and passes `_compact_bytes`, `work_item_steps.owned_json_bytes` and `crew_trust._exact_json_bytes` (same arguments as their call sites); (ii) checkpoint level: test 32's harness with `_FakeJudgeLLM("gpt-5.1", [_ACCEPT, _ACCEPT], answered_model="gpt-\ud800-5")` (premise: the fake's responses carry the lone surrogate): `finalize` stops at the pause with the "durable verdict checkpoints" cancellation, not `crew_finalization_checkpoint_too_large`, and the final verification checkpoint's `verdict["judge"]` is the record of (i); control: `"gpt-é-5"` is written verbatim.

## Mutation table (targeted; run once in Milestone 3 against the committed tree)

Single-line anchors; each occurs exactly once in the named file after the build. Mutate in place with a `.mutbak` sibling, restore in `finally`, baseline first. Not-found = INERT; timeout = INVALID.

| # | File | Anchor (exact line, leading spaces as shown) | Mutation | Expected killer |
|---|---|---|---|---|
| 1 | `cognitive/llm_client.py` | `            verifier_first = [tier] if self._tier_configs[tier].get("model") else []` | `verifier_first = [tier]` | 7 |
| 2 | `cognitive/llm_client.py` | `            fallback_tiers = [*verifier_first, "standard", *(t for t in _TIER_ORDER if t != "standard")]` | `fallback_tiers = [*verifier_first, *_TIER_ORDER]` | 9 |
| 3 | `cognitive/llm_client.py` | `                    _override, _served = self._resolve_route_for_tier(attempt_tier, exact_tier=True)` | `exact_tier=False` | 14 |
| 4 | `cognitive/llm_client.py` | `            if tier in ("vision", "vision_fast", VERIFIER_TIER) and not tc.get("model"):` | drop `VERIFIER_TIER` | 6 |
| 5 | `cognitive/llm_client.py` | `        if tier not in TEXT_TIERS and tier != VERIFIER_TIER:` | `if tier not in TEXT_TIERS:` | 15 |
| 6 | `cognitive/model_router.py` | `                if d.available and _tier_rank(d.tier) >= 0 and _within_ceiling(d, ceiling) and _meets_floor(d.tier, min_tier):` | drop `_tier_rank(d.tier) >= 0 and` | 13 |
| 7 | `cognitive/model_router.py` | `        return (*TEXT_TIERS, VERIFIER_TIER)` | `return TEXT_TIERS` | 11, 12, 15 |
| 8 | `config.py` | `            "verifier": self.llm_model_verifier,` | `self.llm_model_standard` | 2, 6 |
| 9 | `config.py` | `        return None if isinstance(value, str) and not value.strip() else value` | `return value` | 4 |
| 10 | `cognitive/model_registry.py` | `    return families.pop() if len(families) == 1 else None` | `families.pop() if families else None` | 18 |
| 11 | `cognitive/model_registry.py` | `    return model_id.strip().rsplit("/", 1)[-1].casefold()` | `return model_id.strip()` | 18, 19 |
| 12 | `cognitive/verifier_independence.py` | `    if judge_family is None or None in crew_families:` | `if judge_family is None:` | 19 |
| 13 | `cognitive/verifier_independence.py` | `        if fallback and independence == "independent":` | `if False:` | 23 |
| 14 | `cognitive/verifier_independence.py` | `    return bool(cognitive.llm_model_verifier)` | `return True` | 11, 22 |
| 15 | `cognitive/crew_verdict.py` | `        if self.fallback and self.independence == "independent":` | `if False:` | 20 |
| 16 | `cognitive/crew_verifier.py` | `        return "standard" if self._judge_policy is None else self._judge_policy.request_tier` | `return "standard"` | 25 |
| 17 | `cognitive/crew_verifier.py` | `            verdict = replace(verdict, judge=self._judge_provenance(response))` | delete line (`pass`) | 25, 27 |
| 18 | `cognitive/crew_verifier.py` | `            return replace(self._parse_session_verdict(content, verifier_id, tokens), judge=judge)` | `return self._parse_session_verdict(content, verifier_id, tokens)` | 25, 27 |
| 19 | `cognitive/crew_finalizer.py` | `        if self.judge is None:` | `if False:` | 29 |
| 20 | `cognitive/crew_finalizer.py` | `                **({"judge": judge_to_json(item.judge)} if item.judge is not None else {}),` | `**{},` | 30, 32 |
| 21 | `cognitive/crew_orchestrator.py` | `            judge=parse_judge(verification["judge"]) if "judge" in verification else None,` | `judge=None,` | 35 |
| 22 | `cognitive/crew_synth.py` | `                **({"judge": judge_to_json(outcome.verdict.judge)} if outcome.verdict.judge is not None else {}),` | `**{},` | 35 |
| 23 | `cognitive/crew_trust.py` | `        if "judge" in verdict:` | `if False:` | 33 |
| 24 | `doctor/checks/verifier_check.py` | `        if not ctx.config.agentic_dispatch.orchestrator_enabled:` | `if False:` | 37, 41 |
| 25 | `startup/finalize.py` | `        judge_policy=judge_policy,` | `judge_policy=None,` | 40 |
| 26 | `cognitive/verifier_independence.py` | `    if judge_family is not None and judge_family in crew_families:` | `    if judge_family in crew_families:` | 19 (`unknown-judge-and-crew-families`) |
| 27 | `cognitive/verifier_independence.py` | `    crew = [model for model in crew_models if model]` | `    crew = list(crew_models)` | 19 (`empty-crew-names-are-ignored`) |
| 28 | `cognitive/verifier_independence.py` | `        fallback = not (type(answered_tier) is str and answered_tier == self.request_tier)` | `        fallback = answered_tier not in (self.request_tier, None)` (absent provenance read as answered; replaces the exploratory "`self.dedicated and` dropped" mutant, whose line D10 removed) | 23 |
| 29 | `cognitive/verifier_independence.py` | `        if policy.dedicated` | `        if True` | 36 (source text) |
| 30 | `cognitive/crew_verdict.py` | `    if type(value) is not dict:` | `    if False:` | 20 (`parse_judge(<instance>)`) |
| 31 | `cognitive/llm_client.py` | `            return f"{base}\|{VERIFIER_TIER}"` | `            return base` | 42, 46 |
| 32 | `cognitive/llm_client.py` | `    if tier != VERIFIER_TIER or not tc.get("model"):` | `    if tier != VERIFIER_TIER:` | 42 (unset-verifier control) |
| 33 | `cognitive/llm_client.py` | `    return value if type(value) is str else ""` | `    return ""` | 44, 47 |
| 34 | `cognitive/llm_client.py` | `                        response = replace(response, answered_tier=attempt_tier)` | `                        pass` | 45, 48 |
| 35 | `cognitive/llm_client.py` | `                    answered_tier=cached.answered_tier,` | `                    answered_tier=None,` | 45 |
| 36 | `cognitive/verifier_independence.py` | `        model = answered_model if type(answered_model) is str else ""` | `        model = answered_model or ""` | 23 (`7` raises) |
| 37 | `cognitive/llm_client.py` | `        if other != VERIFIER_TIER and _pool_base(oc) == base and (oc.get("api_key") or "") != key:` | `        if other == "fast" and _pool_base(oc) == base and (oc.get("api_key") or "") != key:` (the round-1 first-tier rule, for these configs) | 49, 50 |
| 38 | `cognitive/llm_client.py` | `    key = tc.get("api_key") or ""` | `    key = ""` | 42 (same-key control), 49 (control i) |
| 39 | `cognitive/crew_verdict.py` | `        value.encode("utf-8")` | `        value.encode("utf-8", "surrogatepass")` | 20, 23, 31, 47, 51 |
| 40 | `cognitive/crew_verdict.py` | `        if type(value) is not str or not is_persistable_judge_model(value):` | `        if type(value) is not str:` | 20, 31 |
| 41 | `cognitive/verifier_independence.py` | `        if not is_persistable_judge_model(model):` | `        if False:` | 23, 47, 51 |
| 42 | `cognitive/crew_verdict.py` | `    if "\x00" in value or len(value) > MAX_JUDGE_MODEL_CHARS:` | `    if len(value) > MAX_JUDGE_MODEL_CHARS:` (NUL encodes as UTF-8, so only this clause refuses it) | 20, 23, 31, 47 |

(Row 31's anchor contains a literal `|`, escaped in this table as `\|`. The line in the file is `            return f"{base}|{VERIFIER_TIER}"`; review round 2 keeps that line and its indentation, so row 31 and row 32 stand. The tree is CRLF: match the line without its line ending and write the replacement with the same ending. Rows 26, 27, 29 and 30 come from the orchestrator's exploratory run, recorded here as part of the campaign. Rows 37-42 are review round 2's. Against the repaired tree, rerun every row whose file round 2 changed: `llm_client.py` rows 1-5, 31-38; `crew_verdict.py` rows 15, 30, 39, 40, 42; `verifier_independence.py` rows 12-14, 26-29, 36, 41. The other rows' files are unchanged since the round-1 campaign (compare sha256 first). Row 42's `\x00` is the four source characters backslash, x, 0, 0, as in the file.)

Not mutated (anchors not unique as single lines, or pure wiring covered by named tests): the two `oc.verdict.judge` sites in `crew_synth.py` (one is a substring of the other), the orchestrator write line (test 35 covers it). The two `            answered_model=_echoed_model(data),` transport lines are identical, so neither is a unique anchor; row 33 mutates their shared helper, and test 44 covers each transport. The rate-limit replay line (2j, first SEARCH) is covered by test 45.

## What This Does NOT Change

- Verification criteria, the judge prompts (`_JUDGE_SYSTEM_PROMPT`, `_build_judge_prompt`, `_build_session_judge_prompt`), parsers and thresholds.
- `config/system.yaml` (reference vessel), `config/profiles/*`, `architecture-baseline.yaml`.
- AD-1324 tier choice, `TierChoiceConfig`, the stakes floor and `TEXT_TIERS`/`_TIER_ORDER`.
- Vision, vision_fast, compute_use and image_gen routing (still bypass the router).
- The crew-task API projection and trust weighting (no trust write reads `judge`).
- `routers/agents.py:1767-1772` lists configured tiers for display; a configured verifier appears there as vision does.
- `LLMResponse.model` (the id sent) and `LLMResponse.tier` (the tier requested) keep their meanings; token accounting, logs and the cache key read them unchanged. Pool identity, credentials, breakers and in-flight caps of every tier except a configured verifier whose key some sibling on its URL does not share are unchanged (the existing tiers' shared-URL key limitation is pre-existing and reported separately).
- No second provider is required; no new dependency; no security control changes (the cost ceiling now also covers the verifier).

## Do Not Build

- Do not build #1510 / AD-1326 (procedure-comparison judge) or move procedure evolution to any tier.
- Do not add multi-judge ensembles, panels or votes across judges.
- Do not add `rpm_verifier`, per-tier temperature/top_p/max_tokens/suffix fields for the verifier, or a `default_llm_tier` validator.
- Do not add `judge` to the crew-task API projection or the HXI, and do not weight trust by independence.
- Do not refactor `copilot_adapter._classify_provider`.
- Do not edit `config/system.yaml`, `config/profiles/*` or `docs/development/architecture-baseline.yaml`.

## Milestones (fresh Builder each, about 150 calls)

| M | Sections | Effort | Focused gate (`d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:randomly`) |
|---|---|---|---|
| 1 | 1-7 (including 2f-2j), 11a-11g, 11l, 11m; tests 1-17, 42-45, 49 | medium (mechanical edits, one new module, 22 tests) | `tests/test_ad1327_verifier_tier.py tests/test_ad1325_boundaries.py tests/test_llm_client.py tests/test_ad543_tool_call_protocol.py tests/test_ad1164_continue_or_ask.py tests/test_bf697_agentic_final_text_on_max_iterations.py tests/test_ad1200_repository_instruction_transport.py tests/test_bf654_endpoint_concurrency_cap.py tests/test_bf686_breaker_log_attribution.py tests/test_ad1324_provenance_concurrency.py tests/test_ad1324_tier_policy.py tests/test_ad617_llm_rate_governance.py tests/test_ad1324_router_floor.py tests/test_ad706c2_compute_use.py tests/test_ad732_vision_tier.py tests/test_ad742a_vision_fast_tier.py tests/test_bf069_llm_health.py tests/test_bf246_llm_health_probe.py tests/test_per_tier_llm.py tests/test_ad1135_provider_setup.py tests/test_ad1135_setup_cli.py tests/test_ad1135_setup_chain.py tests/test_bf886_model_routing_config.py tests/test_ad730_3_agent_image_gen.py tests/test_ad1002_instructions_api.py tests/test_bf674_llm_endpoint_cooldown.py tests/test_bf612_empty_content_retry.py` |
| 2 | 8, 9, 11h (with the revised Sections 5, 6 and 8d); tests 18-35, 46-48, 50, 51 | high (persistence across five modules; tests 32, 34, 35 reuse heavy fixtures) | `tests/test_ad1327_verifier_independence.py tests/test_ad1244_verdict_criteria.py tests/test_ad1245_verdict_assessment.py tests/test_ad1242_crew_verifier_trace.py tests/test_ad860_crew_verifier.py tests/test_ad861_crew_synth.py tests/test_ad1126_verified_finalization.py tests/test_ad1192_owned_steps_finalization.py tests/test_ad1282_verifier_credit_full_chain.py tests/test_bf784_verification_defect_is_recorded.py tests/test_bf836_verification_defect_reaches_the_api.py tests/test_ad1125_room_bound_execution.py tests/test_ad867_crew_orchestrator.py` |
| 3 | 10, 11i-11k, 12, 13; tests 36-41; mutation table | medium | `tests/test_ad1327_verifier_tier.py tests/test_ad1327_verifier_independence.py tests/test_ad1135_provider_setup.py tests/test_ad1137_doctor.py tests/test_ad801_doctor.py tests/test_ad484_ux_adoption.py tests/test_ad867_crew_orchestrator.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1152_crew_token_usage.py tests/test_ad1152_agentic_correlation.py tests/test_ad1126_verified_finalization.py tests/test_config_reference_current.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2_config_models.py tests/test_ad1185_config_profiles.py tests/test_ad1324_srp_layout.py`, then `tests/test_ad1137_quickstart_chain.py` once |

Milestone 3 also runs, and reports exit codes:
```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad1327-1511
```
Expected: architecture and store-registry pass with no baseline change; profiles pass unchanged; reference and facade pass after the Section 12 regeneration. The broad gate is the orchestrator's (`--label ad1327-1511 --receipt logs/gates/ad1327-1511.receipt.json`).

**Applying review round 1 to the already-built candidate** (the orchestrator's tree, not a fresh base): apply 2f-2j and 11m as written, and replace Sections 5's docstring, 6's module docstring, `provenance` and report docstring, 8d's `_judge_provenance` and 10's `__main__` comment with the revised text (2a's comment and the 10/6 docstrings already match the code, S3). Update `_FakeEndpoints` (both files) and `_FakeJudgeLLM` as described under Tests, revise test 23, and add tests 42-48. Run Milestone 1's and Milestone 2's focused lists, then mutation rows 26-36.

**Applying review round 2 to the already-built candidate:** in `llm_client.py` replace `_client_pool_key` with 2g's revised function (docstring and body); in `crew_verdict.py` add `is_persistable_judge_model` after `MAX_JUDGE_MODEL_CHARS` and change `_validate_model`'s condition (Section 5); in `verifier_independence.py` replace the `MAX_JUDGE_MODEL_CHARS` import with `is_persistable_judge_model` and apply the `provenance` docstring and bound (Section 6). Tests: add the `lone-surrogate-model` entry to `_INVALID`, extend tests 23, 44, 47 as described, rewrite the two test-23 comments (`tests/test_ad1327_verifier_independence.py:316`, `:322`), add `_FakeJudgeLLM`'s `answered_model` keyword and tests 49-51. Run Milestone 1's and Milestone 2's focused lists, then the mutation rows the table's note names.

**Hard stops (hand to the Architect):** a focused failure outside the pins of Section 11; any change needed to `tests/fixtures/ad1325_ad1324_flag_off_base.json`; any existing test that counts pools or pool keys failing (D8 must leave every non-verifier pool as it is); any facade-baseline row change beyond Section 12's list; any change to `architecture-baseline.yaml`; `_VERDICT_KEYS` failing in `tests/test_ad1126_verified_finalization.py:2055` (it should not: `_make_verifier` at `:964` wires no policy); a doctor check order test failing.

## Acceptance Criteria

- [ ] Unset `llm_model_verifier`: both verifier paths send the pre-AD-1327 request (test 24 golden) and an unset `verifier` request is sent down the standard chain (test 7).
- [ ] Set: `verify` and `verify_for_session` use it, config -> client -> verifier (test 25).
- [ ] Every per-tier structure in the client iterates `_LLM_TIERS` (test 5); `verifier` is outside `_TIER_ORDER` and falls back to standard, fast, deep (tests 1, 9, 10).
- [ ] Startup and `probos doctor` report `same_model`, `same_family`, `unknown` and `independent`, each tested (tests 36, 39), WARN never FAIL, quiet when the orchestrator is off (tests 37, 39, 41).
- [ ] Verdicts persist the judge model and independence (tests 30, 32, 34, 35); a fallback verdict is labelled and never `independent` (tests 23, 26); old rows keep their bytes and hashes (tests 29, 33).
- [ ] The cost ceiling governs verifier calls and probes (test 15); no crew model is sent to the verifier endpoint and no verifier model answers a crew request (tests 13, 14).
- [ ] `config-reference.md` and the facade baseline document the five fields; profiles need none (Section 12).
- [ ] A verifier key that differs from its shared pool's reaches the provider on requests and the probe; no key in pool names; every other tier's pooling unchanged (tests 42, 43, 46).
- [ ] A configured verifier shares a pool only when every other tier on it has the verifier's key, so a sibling's BF-612 refresh never changes the verifier's key; the single-key configuration keeps one pool (tests 49, 50).
- [ ] The judge record names the provider's reply model; absent or unusable = `""` with `unknown`; `LLMResponse.model` still names the id sent (tests 44, 47).
- [ ] Unusable includes text that is not strict UTF-8 (a lone surrogate): one predicate bounds the policy and the persisted record, and such a reply no longer stops the verdict checkpoint from being written (tests 20, 23, 31, 47, 51).
- [ ] `fallback` is decided by the answering tier, kept on cache replays; a same-id standard answer after a dedicated failure is a fallback (tests 23, 45, 48).
- [ ] `tests/test_ad1325_boundaries.py` still matches its base fixture byte-for-byte (11m), and the fixture is unchanged.
- [ ] All 42 mutants killed or explained; no INERT or INVALID left unexplained.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots

- *Internal.* MASS absorption note (`docs/research/mass-self-supervision-absorption.md:32`, `:44`): adopted as the motivation and owner. AD-1244 `criteria` persistence (`crew_finalizer.py:248-254`, `test_ad1244_verdict_criteria.py:305-427`): adopted as the compatibility rule. AD-732 vision tier: adapted (a peer in `_LLM_TIERS`; unlike vision it falls back into the text chain, since a text judge can be served by a text tier, and it is routed). BF-273 router bypass: rejected (cost ceiling). BF-886 A-1 "a probe is a generation request": adopted. AD-1137 quickstart pin: constraint honoured by D7.
- *External.* Panickssery, Bowman and Feng, "LLM Evaluators Recognize and Favor Their Own Generations" ([arXiv:2404.13076](https://arxiv.org/abs/2404.13076)): self-preference correlates with self-recognition; adopted as the reason `same_model` is the strongest warning. Verga et al., "Replacing Judges with Juries" ([arXiv:2404.18796](https://arxiv.org/abs/2404.18796)): judges from disjoint model families show less intra-model bias; adopted as the reason the outcome is graded by family, while juries themselves are out of scope (the issue rules out ensembles; considered, deferred).
- *Blind spots handled.* An unregistered tier would be served by a crew model through the router (D3). The cost ceiling would not have covered verifier calls or probes (D3). The doctor warning would have broken the quickstart contract (D7). An unset `verifier` request from a future caller would send model `None` (Section 2b skips it). Setup's shared-URL guard (B7) must count a verifier with a model (test 16).
- *Blind spots found by review round 1 (and handled).* Pools bake the first tier's key, so a per-tier key on a shared URL never reached the provider (D8). The response's `model` was the id sent, so a provider that served another model was recorded as the configured one (D9). Fallback inferred from model ids could not see a same-id fallback (D10). The doubles carried none of these seams, so tests 42-48 use doubles that do. *External:* the OpenAI chat-completion object documents `model` as "the model used for the chat completion" ([API reference](https://developers.openai.com/api/docs/api-reference/chat); SDK type `model: str`, [openai-python `ChatCompletion`](https://docs.camel-ai.org/_modules/openai/types/chat/chat_completion.html)), and Ollama's `/api/chat` reply carries `model` ([Go API types](https://pkg.go.dev/github.com/ollama/ollama@v0.16.3-rc0/api)). Adopted as the basis for "absent echo = unknown". *Considered, deferred:* credential-aware pooling for the existing tiers (pre-existing, reported separately); bounding `answered_model` in the transport (only the persisted record needs the bound).
- *Blind spots found by review round 2 (and handled).* A pool's header is the key of the tier that last built it, and any tier on the pool can rebuild it (BF-612), so "the first tier's key" was not a stable owner (D8 amendment). Provider text, newly persisted by D9, can be a lone surrogate that strict UTF-8 encoders refuse; the record's bound now includes encodability (D9 amendment). ProbOS-specific plumbing; no external search needed beyond JSON's `\uXXXX` escapes (RFC 8259 permits an unpaired escape, which decodes to a lone surrogate in Python). *Considered, deferred:* the same encodability hazard for `critique` and response content (pre-existing; reported separately).
- *Considered, deferred.* `rpm_verifier` (verifier uses the 60 rpm default only when `llm_rate` is set); `default_llm_tier` accepts any string, including `verifier` (pre-existing, operator-only); one model under two spellings (`claude-sonnet-4.5` vs `claude-sonnet-4-5`) reads as `same_family`, which is still degraded; crew agents that call non-text tiers (vision) are not in the comparison set; the API projection does not show `judge`.

## Verified Against Codebase (2026-10-13, base `692e1df6`)

```
rg -n "_LLM_TIERS|_TIER_ORDER|TEXT_TIERS" src/probos/cognitive/llm_client.py
  42: _LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")
  48: _TIER_ORDER: tuple[str, ...] = ("fast", "standard", "deep")
  51: TEXT_TIERS: tuple[str, ...] = _TIER_ORDER
  213, 290, 296, 324, 329, 348, 352, 381, 427, 1139, 2434, 2472: for/in _LLM_TIERS
  1502: if tier in ("vision", "compute_use"):   1504: elif tier == "vision_fast":   1510: elif exact:
  1513: fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]
  1146: if tier in ("vision", "vision_fast") and not tc.get("model"):
  1036-1044: _probe_model: if tier not in TEXT_TIERS: return configured ... decision = preview(tier=tier)
  972: if tier in ("vision", "vision_fast", "compute_use"): return RouteResult(None, None)   (BF-273 bypass)
  1546-1550: if exact: _override, _served = self._resolve_route_for_tier(... exact_tier=True)
  1467-1472: rpm_limits = {"fast": ..., "standard": ..., "deep": ...}; 1073: limit = rpm_limits.get(tier, 60)
  2356-2359: LLMResponse(content=content, model=model, tier=request.tier or self.default_tier
rg -n "class CognitiveConfig|llm_model_vision|def tier_config|image_gen\": self" src/probos/config.py
  311: class CognitiveConfig(BaseModel):   365-369: vision fields   521-525: image_gen fields
  586: def tier_config   593-599 / 602-608 / 611-617 / 620-626 / 629-635: maps   674: "model": model_map.get(tier, self.llm_model_standard)
rg -n "tier=\"standard\"|class VerificationVerdict|class SessionVerificationPass|def verify|ontology: Any = None|def _build_trace_section" src/probos/cognitive/crew_verifier.py
  160, 204, 1296-1320, 1340, 1384, 1421, 1793, 1848
rg -n "criteria" src/probos/cognitive/{crew_finalizer,crew_orchestrator,crew_synth,crew_trust}.py
  crew_finalizer.py:241, 248-254, 265, 3370-3374   crew_orchestrator.py:76, 3972-3976, 4082-4112
  crew_synth.py:49, 185-189, 1077-1080, 1273-1276   crew_trust.py:14, 184-188, 202-208 (evidence_sha256)
rg -n "def build_model_routing|def ceiling_denials|for d in self._registry.all|def _tier_rank" src/probos/cognitive/model_router.py
  84, 286-287, 439-460, 463-474
rg -n "TIER_CONFIGURED_CHECKS|OPTIONAL_TIERS =" src/probos/provider_setup.py      49, 51-57, 331, 805-810, 820
rg -n "SubtaskVerifier\(|from probos.cognitive.crew_verifier|report_cost_ceiling|orchestrator_enabled" src/probos/startup/finalize.py
  2112-2114, 2165, 2235-2244, 3856-3866
rg -n "TEXT_TIERS|_LLM_TIERS|def _create_llm_client" src/probos/__main__.py      56, 211, 309, 321, 328-343
rg -n "register_check|name: str = \"llm_tiers\"" src/probos/doctor/checks/llm_check.py   334, 357
rg -n "extras_check|llm_check" src/probos/doctor/checks/__init__.py              13, 14
rg -n "TIER_RANK|for t in TEXT_TIERS" src/probos/cognitive/tier_policy.py      26, 429-432
rg -n "tiers = \(\"fast\"" src/probos/config_models/agentic.py               383
rg -n "provider=|_CATALOG_BY_NAME" src/probos/cognitive/model_registry.py      37, 51-87, 90, 148-150
rg -n "def _classify_provider" src/probos/cognitive/copilot_adapter.py         107-118
rg -n "escape\(message\)" src/probos/doctor/runner.py                          145-150
rg -n "LLMResponse\(|\"model\": model" src/probos/cognitive/llm_client.py
  2280 / 2386: payload "model": model   2356-2358 / 2417-2419: LLMResponse(content=content, model=model, ...)
  -> on success the response's model is the id the client SENT (1581: model = _override or tc["model"]), not the provider's
     echo; a dated snapshot id in the reply never produces a false judge `fallback` (orchestrator saw the same at :2375 on the applied tree)
```

Executed by the orchestrator (2026-10-13, Sections 1-11 applied to base `692e1df6`; reported, not re-run here):
- every SEARCH applies exactly once; the tree imports and compiles; `gen_config_reference.py`, `check_config_facade.py --update-baseline/--check` (fields 1839 -> 1844), `check_config_profiles.py`, `check_architecture_principles.py` (srp-size 92), `check_store_registry.py` pass; `architecture-baseline.yaml` unchanged.
- diagnostic full suite: 6 failed, 44,455 passed, 60 skipped before 11i-11l; the 6 pass after (380 passed in the four files), 0 failed.
- golden precedent: `git log --oneline -1 e7b7ee71 -- tests/fixtures/ad1152_agentic_off_golden.json` -> `e7b7ee71 feat(cognition): add agent-directed tier choice (AD-1324, #1479)`.

Review round 1 (2026-10-13; read on the installed candidate tree, whose lines outside AD-1327's own edits equal base `692e1df6` -- `git diff 692e1df6 --stat`: `llm_client.py` 35 lines, `types.py` untouched):
```
R1  pool identity: rg -n "_client_key\(|\['base_url'\]\}\||_tier_configs\[[^\]]+\]\s*=" src/probos/cognitive/llm_client.py
      296 (only _tier_configs write, __init__); 306, 387, 445, 499, 528, 577, 631, 784, 855, 1164, 1166, 1554, 1643 (logged), 2472: every pool-keyed
      site calls _client_key; 435-438 the only place a key is built.  301-308 pools built in _LLM_TIERS order; 404-406 failure states from _clients;
      384-389 semaphores per _client_key; 814-830 _build_client bakes Authorization from the tier it is given; 855 _refresh_client rebuilds via it.
    config.py:713-717 tier_config: "base_url": url_map.get(tier) or llm_base_url; "api_key": key_map.get(tier) if not None else llm_api_key
      -> an UNSET verifier has the shared key, which differs from fast's when llm_api_key_fast is set: hence the `tc.get("model")` guard in 2g.
R2  transports: 2319 / 2425 data = resp.json(); 2375-2386 / 2436-2445 LLMResponse(model=model, ...) -- body "model" never read.
R3  attempt loop: 1552 for attempt_tier in fallback_tiers; 1571 _served = attempt_tier if no router else None; 1791-1795 cache write with _served;
      1828 return response (the only success return). Replays rebuild: 1487-1490 (rate limit), 1958-1965 (final).
R4  imports: 15 from collections.abc import AsyncIterator, Callable, Mapping; 18 from dataclasses import dataclass, field; 19 typing Any.
      rg "[^.\w]replace\(|import.*\breplace\b" llm_client.py -> none (no name clash for `replace`).
R5  verifier: crew_verifier.py:1356 _judge_provenance -> policy.provenance(getattr(response, "model", None)) (the only provenance caller;
      rg "\.provenance\(" src/probos -> crew_verifier.py only); verifier_independence.py:122-137 provenance, :132 fallback by model inequality.
R6  rate config: config_models/knowledge.py:238 LLMRateConfig, :243 rpm_standard, :247 max_wait_seconds; llm_client.py:347 self._rate_config = rate_config.
R7  S1-S3 sync, on the tree: crew_synth.py:159 def _legacy_episode_payload, :190 the row-22 line; tests/test_ad1327_verifier_independence.py:223-224
      (the two test-19 params); llm_client.py:44 "so neither can select it."; __main__.py:346 "(the crew verifier is built only then),";
      verifier_independence.py:144-147 the report docstring as revised here.
NOTE: the earlier claim above ("a dated snapshot id in the reply never produces a false judge fallback") still holds under D10, for a new reason:
      fallback is decided by the answering tier, not by any model id.
```

Review round 2 (2026-10-13; read on the round-1 candidate tree in this worktree):
```
S1  pool writers: rg -n "_clients\b" src/probos/cognitive/llm_client.py
      337 dict; 345-346 __init__ builds `self._build_client(tier)` per _client_key in _LLM_TIERS order; 919 old_client; 923 install
      `self._clients[client_key] = new_client`; 929 rollback to old_client; 2627 pop at close. No other write.
    rg -n "_refresh_client\(" src/probos -> llm_client.py:870 (def), :1745 (only caller, BF-612 recovery, `attempt_tier`)
    llm_client.py:892 client_key = self._client_key(tier); :908 new_client = self._build_client(tier); 859-863 header from
      self._tier_configs[tier]["api_key"] -> a refresh bakes the REFRESHING tier's key.
    llm_client.py:47 _LLM_TIERS = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", VERIFIER_TIER)
    llm_client.py:109-130 _client_pool_key as built in round 1 (first matching tier decides; :122 model guard; :129 the |verifier return)
    config.py:349 llm_api_key_standard, :535 llm_api_key_verifier (per-tier keys exist for the F4 recipe)
S2  bound: crew_verdict.py:106 MAX_JUDGE_MODEL_CHARS = 256; :131-134 _validate_model (type, NUL, length); verifier_independence.py:29-33
      imports MAX_JUDGE_MODEL_CHARS (its only code use is :136); :135 type gate (row 36); :136-137 NUL/length bound.
    rg "MAX_JUDGE_MODEL_CHARS" tests -> none (removing the import from verifier_independence breaks no test import).
S3  encoders: crew_finalizer.py:131-144 _compact_bytes (ensure_ascii=False, .encode("utf-8"); catches ValueError -> error token);
      :2347/:2353 _write_json_checkpoint; :2264, :3688 provenance bytes. work_item_steps.py:83-88 owned_json_bytes (ensure_ascii=False;
      ValueError/UnicodeError -> owned_steps_format_invalid). crew_orchestrator.py:3977 judge in the owned legacy payload, :3985 owned_json_bytes.
      crew_synth.py:190 legacy episode judge, :430 payload, :598 owned_json_bytes; :1082 parent provenance judge, :1087
      json.dumps(provenance, sort_keys=True, default=str) (ASCII escapes); :1279 collaboration episode judge, :1297 episodic.store.
      episodic.py:3556 json.dumps(ep.outcomes), :1046 json.dumps(content, ...) for the hash (ASCII escapes).
      crew_trust.py:56-64 strict encode (UnicodeError caught), :189-193 parse_judge first, :207-212 hash.
    crew_finalizer.py:252-256 _VerdictRecord._validate_judge -> parse_judge (so test 31 reaches the bound).
S4  tests on the candidate: tests/test_ad1327_verifier_independence.py:104-116 _INVALID / _INVALID_JUDGES (shared by 20 :250, 31 :499,
      33 :588); :131-151 _FakeJudgeLLM(model, contents, *, error, provenance) sets answered_model=self.model; :316, :322 the two comments.
    probe: logs/architect/probe_ad1327_r2_findings.out -> F4_pool_keys one key, verifier_has_own_pool false, after_refresh key B;
      F5 policy keeps the lone surrogate, checkpoint encoder refuses, wire answered_model carries it; ASCII and U+00E9 controls encode.
```

## Hidden Pins Enumerated (2026-10-13)

**Review round 2 (2026-10-13).** No new hidden pin found by search. The 2g change alters a pool key only when `llm_model_verifier` is set, and no existing test outside the two AD-1327 files configures one (Absence R1, unchanged), so every existing pool-count and pool-key test (101 `_client_key` uses in 5 files, below) sees the base key. In the AD-1327 files: test 42's controls and test 43 hold under the new rule (all tiers share one key there, or the verifier has its own URL); the shared `_INVALID` list gains one entry, so tests 20, 31 and 33 each gain one case (33 passes with or without the bound). `MAX_JUDGE_MODEL_CHARS` is imported by no test. The full suite on the repaired tree remains the enumeration of record.

**Review round 1: the shared-contract change to `probos/types.py::LLMResponse` (2f), enumerated by search.** The full suite on the repaired tree is still the enumeration of record.
```
RUN   rg -n "LLMResponse\(" src/probos            -> 20 sites, all in llm_client.py: 1487, 1491, 1958, 1975, 1993, 2009, 2045 (_complete_inner),
                                                      2375, 2436 (transports, 2h), 2862-3009 (MockLLMClient). Only 1487 and 1958 copy from
                                                      another response (2j). Keyword-only everywhere; appended defaulted fields are safe.
RUN   rg -n "replace\((response|resp|cached|result)\b" src/probos  -> tier_policy.py:136 dataclasses.replace(response, **changes) (keeps all fields)
RUN   rg -n "model=(cached|response|resp|result|llm_response|raw)\.model" src/probos
      -> agentic_dispatch.py:3790, cognitive_agent.py:4463 (token records read .model only; D9 keeps .model = sent); llm_client.py:1488, 1960 (2j)
RUN   rg -n "asdict\((resp|response|llm_response|reply|answer)\b|vars\(\w*resp" src/probos  -> none
RUN   rg -n "fields\(LLMResponse|asdict\(|__dataclass_fields__|==\s*LLMResponse\(|LLMResponse\(\"" tests  (then filtered to LLMResponse objects)
      PINNED: test_ad1325_boundaries.py:227 asdict(LLMResponse) == fixture bytes (ad1325_ad1324_flag_off_base.json, sha at :237) -> 11m
      safe: test_ad1152_agentic_correlation.py:315, 442 (asdict of agentic results; the golden has no LLMResponse keys, see next RUN);
            test_ad1327_verifier_independence.py:309 (asdict of an LLMRequest); no `== LLMResponse(` anywhere
RUN   rg -l "refusal_cause|stop_reason|error_kind" tests/fixtures ; rg -n "[\"']refusal_cause[\"']\s*:|[\"']stop_reason[\"']\s*:\s*[\"']stop" tests
      -> only ad1325_ad1324_flag_off_base.json (11m); no inline dict literal of LLMResponse fields
RUN   rg -n "LLMResponse\([^)=]*,[^)=]*," tests    -> test_ad706c2_compute_use.py:100 (_FakeLLMResponse, not LLMResponse): no positional use
RUN   rg -n "assert \w+ is (resp|response|canned|expected_response|fake_response|reply|mock_resp)\b" tests
      -> test_ad1324_tier_policy.py:43 (tier_policy, no client), test_ad594b_consult_primitive.py:75 (no client): 2i's replace creates a new
         object only inside OpenAICompatibleClient's attempt loop; test_bf612_empty_content_retry.py:418 `_cache[...] is cached` is the
         empty-response path, which 2i does not reach (empty content is not a success)
RUN   rg -n "_call_(openai|ollama_native)\s*=|setattr\([^)]*_call_(openai|ollama_native)|patch\.object\([^)]*_call_(openai|ollama_native)" tests
      -> test_llm_client.py:264, 278 (return LLMResponse; replace is valid); test_ad1200_repository_instruction_transport.py:343 (returns an
         error LLMResponse; not the success path). No stub returns a non-dataclass to the attempt loop.
RUN   rg -n "_cache_put\(self, cache_key|model=cached\.model|from dataclasses import dataclass, field|content=cached\.content" tests ;
      rg -n "getsource\(.*(llm_client|OpenAICompatibleClient)" tests
      -> source scans: test_ad742a_vision_fast_tier.py:127, 137 (vision lines, untouched), test_bf686_breaker_log_attribution.py:245-247
         (two lines, untouched), test_bf886_model_routing_config.py:852 (TEXT_TIERS alias, untouched). No scan names a 2f-2j line.
RUN   rg -c "_client_key" tests -> 101 in 5 files (bf654: 41, test_llm_client: 28, bf674: 23, bf612: 5, bf246: 4);
      rg -l "llm_model_verifier|\"verifier\": \{|_tier_configs\[\"verifier\"\]" tests -> only the two test_ad1327_* files. So no existing test
      configures a verifier model, and 2g returns the unchanged base key for every existing call.
RUN   architecture-baseline.yaml:581-588 OpenAICompatibleClient srp-size (triggers lines, methods; no magnitude) -> 2g adds module functions, no row change.
```

**Revision (2026-10-13): four pins below were missed by the search enumeration and found by execution.** The orchestrator applied Sections 1-11 (as first drafted) to base `692e1df6` and ran a diagnostic full suite: **6 failed, 44,455 passed, 60 skipped**. The 6 failures are exactly these four pins (1 + 1 + 3 + 1 tests); with 11i-11l and the Section 6 docstring rewording applied, all 6 pass (380 passed in the four files), so **0 failed** remain. Why search missed them: the census counts docstring tokens (11i), a field count and a whole-config digest are pins of *any* config field, not of tier names (11j, 11k), and the `client.models` dict pins tiers as dict keys with per-line comments, which the tuple/set-literal search did not match (11l).

```
FOUND by full suite (not search):
  test_ad1135_provider_setup.py:701  importer set (verifier_check.py import; verifier_independence.py docstrings :606, :692 as drafted) -> 11i + Section 6 rewording
  test_ad1270e1_config_facade.py:1548  field_definitions == 1839 -> 1844 -> 11j
  fixtures/ad1152_agentic_off_golden.json:15, :17  observation_sha256 / default_config_sha256 (3 tests) -> 11k
  test_per_tier_llm.py:256-264  full client.models dict -> 11l
RE-ENUMERATED after the run, per term (every test file that mentions it):
  rg -n "field_definitions|default_config_sha256|client\.models|importers ==|provider_setup\.py\"" tests
    test_ad1270e1_config_facade.py:1548 (pinned, 11j); test_ad1152_agentic_correlation.py:468 (generator; golden pinned, 11k);
    test_per_tier_llm.py:243-244 (single keys, safe), :256 (pinned, 11l); test_ad1135_provider_setup.py:682, 701 (pinned, 11i);
    test_ad1137_doctor.py:1437 importers of probos.doctor == {"__main__.py"} (imports only, no string constants; Section 10
      adds no probos.doctor import outside doctor/ -- __main__ already imports it; safe); test_codebase_index.py:396 (unrelated)
    endpoint.models == [...] in test_ad1324_router_floor.py, test_ad1324_tier_choice_e2e.py, test_bf886_model_routing_config.py
      (one request's model list, not the tier set; safe)
  rg -n '"image_gen"[,:)\]}]' tests ; rg -n '"vision_fast"[,:)\]}]' tests   (tier-name dict/set/tuple literals)
    pinned and repaired: test_ad1324_router_floor.py:98 (11a), test_ad706c2_compute_use.py:201 (11b), test_ad732_vision_tier.py:563 (11c),
      test_per_tier_llm.py:263 (11l), :287 (11d), test_bf069_llm_health.py:26, 27, 66, 541 (11e), test_ad1135_provider_setup.py:1147 (11f)
    safe: test_ad1135_provider_setup.py:1150 (verifier unset there), 1225, 1261-1262, 1381, 1392, 1397; test_ad1135_setup_cli.py:1881-1890;
      test_ad1137_doctor.py:677, 1325 (derived; verifier -> False); test_ad1324_tier_policy.py:52, 54; test_ad730_3_agent_image_gen.py:362;
      test_ad742a_vision_fast_tier.py (single-tier); test_ad742e_vision_budget.py:33-34 (vision budget keys, not tiers);
      test_bf246_llm_health_probe.py:176; test_bf886_model_routing_config.py:332
  _LLM_TIERS / OPTIONAL_TIERS: unchanged from the first enumeration below.
NO FURTHER PIN: the full suite is the enumeration of record; its 6 failures map one-to-one onto the four pins.
```

First enumeration (search only, as drafted):

```
RUN   rg -n "_LLM_TIERS|OPTIONAL_TIERS" tests
FOUND exact tier-set pins: test_ad1324_router_floor.py:97-99, test_ad706c2_compute_use.py:201, test_ad732_vision_tier.py:563
      oracle/inherited pins: test_ad1135_provider_setup.py:1124-1126, 1147, 1374-1379; test_ad1135_setup_cli.py:883-889
      derived, safe: test_ad1135_provider_setup.py:1130-1132, 1142, 1172-1180; test_ad1135_setup_chain.py:214;
                     test_ad1137_doctor.py:1325, 1350, 1401; test_ad1137_quickstart_chain.py:264; test_ad1135_setup_cli.py:867
RUN   rg -n '"fast", "standard", "deep", "vision"' tests   (literal tuples)
FOUND test_bf069_llm_health.py:26, 27, 66, 541 (66 and 541 break); test_bf246_llm_health_probe.py:176 (safe: unset verifier is not probed);
      test_per_tier_llm.py:287 (breaks)
RUN   rg -n "fallback_tiers|_tier_rank\(d\.tier\)|for d in self\._registry\.all" tests ; rg -n "TEXT_TIERS" tests/test_bf886_model_routing_config.py
FOUND test_ad742a_vision_fast_tier.py:130-139 source scan ('tier == "vision_fast"', '["vision_fast", "vision"]', 'tier in ("vision", "compute_use")',
      "fallback_tiers = [tier]") -- all kept; test_ad742a:274-295 regex for the 4-tuple ending at "vision" -- not matched;
      test_bf886_model_routing_config.py:843-857 AST alias TEXT_TIERS = _TIER_ORDER -- unchanged
RUN   rg -n "sha256|_BASELINE|golden|hexdigest" tests/{test_ad1324_*,test_ad1244_*,test_ad1270e*,test_ad1185_*,test_ad1282_*,test_ad1242_*}.py
FOUND test_ad1324_srp_layout.py:19,57 architecture-baseline sha (file must not change); test_ad1324_router_floor.py:102 golden choose (text path unchanged);
      test_ad1244_verdict_criteria.py:335-345 historical verdict bytes+sha, :416-427 trust evidence hash (judge omitted when None keeps both);
      test_ad1270e1/e2 read config-facade-baseline.yaml (regenerated, Section 12) [RETRACTED as complete: e1:1548 also pins the field count, 11j]; test_ad1185_config_profiles.py:400 relative sha (defaults unchanged)
RUN   rg -n "fields\(VerificationVerdict|fields\(SessionVerificationPass|VerificationVerdict\([^a-z)]|SessionVerificationPass\([^a-z)]|asdict\(" tests src
FOUND test_ad1244_verdict_criteria.py:310-313 (field order; updated 11h); positional constructors test_ad1244:265, 306-307, test_ad1245:195-196 (append-safe);
      test_ad1125_room_bound_execution.py:201 asdict round trip (safe); src: only keyword construction (crew_verifier.py, crew_orchestrator.py:4106, crew_finalizer.py:257)
RUN   rg -n "set\([^)]*verdict[^)]*\)\s*==" tests
FOUND test_ad1126_verified_finalization.py:2055 (_make_verifier :964 wires no policy -> no judge; safe); test_ad1245_verdict_assessment.py:433 (API projection, not edited)
RUN   rg -n "All checks passed|warning\(s\) above" tests
FOUND test_ad1137_quickstart_chain.py:276 (orchestrator off -> new check OK; D7); test_ad1137_doctor.py:1245-1284 (registry patched; safe)
RUN   rg -n "llm_model_vision_fast|llm_api_key_image_gen" --files-with-matches (outside src)
FOUND docs/development/config-reference.md:114,126; docs/development/config-facade-baseline.yaml:1074,1086 (both regenerated); config/system.yaml (not touched)
```

## Absence Verified (2026-10-13)

```
CLAIM: no verifier tier, verifier model field or judge record exists yet
RUN:   rg -n "VERIFIER_TIER|judge_policy|JudgeProvenance|def model_family|def normalise_model_id|llm_model_verifier" src/probos
FOUND: none
RUN:   rg -n '"verifier"' src/probos
FOUND: only ownership roles (crew_orchestrator.py:192-430, 3398, 3670-3678, 4021; crew_finalizer.py:719-722; crew_session.py:2354-3209;
       work_item_steps.py:1602, 1638; workforce.py:2884-7211) -- a separate namespace from LLM tiers
HOLDS: yes

CLAIM: no model-family metadata exists besides the 3-entry catalog provider and a private display classifier
RUN:   rg -n -i "family|vendor|provider" src/probos/cognitive/{model_registry,tier_policy,llm_client,crew_verifier}.py ; rg -n -i family <config.py, provider_setup.py, __main__.py, startup/finalize.py, config_models/agentic.py, doctor/checks/llm_check.py>
FOUND: model_registry.py:37 (ModelDescriptor.provider), :54/63/76 (all "anthropic"), :150 ("unknown"); copilot_adapter.py:107 _classify_provider (private, display); no "family"
HOLDS: yes

CLAIM: SubtaskVerifier is constructed only in _wire_crew_orchestrator, which returns early unless orchestrator_enabled
RUN:   rg -n "SubtaskVerifier\(" src/probos
FOUND: crew_verifier.py:1288 (class), startup/finalize.py:2235; gate at finalize.py:2112-2114
HOLDS: yes

CLAIM: no profile sets an llm_ key; no roadmap row for AD-1327
RUN:   rg -c "llm_|cognitive" config/profiles ; rg -n "AD-1327|#1511" docs/development/roadmap.md PROGRESS.md DECISIONS.md
FOUND: 0 ; none (only docs/research/mass-self-supervision-absorption.md:32, :44)
HOLDS: yes

CLAIM (R1): no LLMResponse field or code path already carries the answering tier or the provider's model id
RUN:   rg -n "answered_" src/probos ; rg -n "data\.get\(\"model|data\[\"model" src/probos/cognitive/llm_client.py
FOUND: retroactive_evolver.py:207-208 ("answered_by" relation names, unrelated); on the candidate tree also verifier_independence.py:122-129
       (the as-built `answered_model` parameter of `provenance`, which revised Section 6 replaces); no data.get("model") / data["model"] read
HOLDS: yes

CLAIM (R1): nothing outside llm_client.py constructs an LLMResponse, so 2j's two replays are the only copies to extend
RUN:   rg -c "LLMResponse\(" src/probos
FOUND: llm_client.py:20 (and no other file)
HOLDS: yes

CLAIM (R1): no existing test configures a verifier model, so D8 changes no existing pool key
RUN:   rg -l "llm_model_verifier|\"verifier\": \{|_tier_configs\[\"verifier\"\]" tests
FOUND: tests/test_ad1327_verifier_independence.py, tests/test_ad1327_verifier_tier.py only
HOLDS: yes

CLAIM (R1): no test fixture or inline literal pins LLMResponse's field set except test_ad1325_boundaries (11m)
RUN:   rg -l "refusal_cause|stop_reason|error_kind" tests/fixtures ; rg -n "asdict\(\w*(resp|reply|answer|llm_out|completion)\w*\)|fields\(\w*(LLMResponse|resp)" tests
FOUND: tests/fixtures/ad1325_ad1324_flag_off_base.json ; tests/test_ad1325_boundaries.py:227
HOLDS: yes

CLAIM (R2): nothing but __init__ and _refresh_client installs a pool, and _refresh_client has one production caller
RUN:   rg -n "_clients\b" src/probos/cognitive/llm_client.py ; rg -n "_refresh_client\(" src/probos
FOUND: llm_client.py:337, 345, 346, 352, 411 (comment), 443, 833, 919, 923, 929, 2606, 2627 ; llm_client.py:870 (def), 1745
HOLDS: yes -- installs at 346 and 923 (929 restores the previous client); 2627 pops at close

CLAIM (R2): no judge-model encodability check exists yet, and the new predicate name and mutation anchors are free
RUN:   rg -n "encode\(|UnicodeEncodeError|is_persistable_judge_model" src/probos/cognitive/{crew_verdict,verifier_independence}.py ;
       rg -n "key = tc\.get\(|value\.encode\(|if False|surrogatepass" src/probos/cognitive/{llm_client,crew_verdict,verifier_independence}.py
FOUND: none ; none
HOLDS: yes

CLAIM: no router test registers a non-text-tier descriptor (so the 4a guard changes no existing case)
RUN:   rg -n 'tier="(vision|compute_use|image_gen|vision_fast|other|x|custom|premium)"' tests/*{router,registry,463,886,1324}*
FOUND: test_ad1324_router_floor.py:210 (an LLMRequest, not a descriptor); test_ad1022 (workstations, unrelated)
HOLDS: yes
```

Could not run (bridge): the five `scripts/*.py --check` tools and pytest against the edited tree (no edits were applied); their expected results above are derived from reading the scripts and baselines, not measured. **Superseded 2026-10-13:** the orchestrator ran them (see Verified Against Codebase); the search-only enumeration was incomplete (Hidden Pins, Revision).

Could not run (review round 2, bridge): Python. Not measured here: that pydantic's strict `str` accepts a lone surrogate (taken from the orchestrator's probe, `F5_policy_keeps_lone_surrogate: true`); that `httpx.Response(json=...)` encodes strictly (hence test 44's explicit bytes; harmless if it does not); the mutants' kill sets; whether `episodic.store` reaches ChromaDB metadata that refuses a surrogate (moot after the bound: the record never carries one); the work-item `verification` column's encoder (likewise moot).
