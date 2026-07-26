# AD-1149 — Prompt caching / stable prefix reuse (cognitive / llm_client / swe_harness)

**Issue: #1074 · Epic #1068 (harness parity) · nominally lands after AD-1146 (#1073).**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1149** (#1074). HEAD at investigation: `43b3cee3`. AD ceiling: **AD-1152**. BF ceiling: **BF-680**. Next free: AD-1153 / BF-681. AD-1149 and AD-1150 have zero references in `PROGRESS.md`, `DECISIONS.md`, or `docs/development/roadmap.md` — AD-1149 is free and reserved by #1074.**

---

## ⛔ VERDICT — **DEFER. Do not build.**

**AD-1149 is not buildable as a measurable optimisation at HEAD `43b3cee3`.** The gating question — *can the primary endpoint express and honour a cache directive, and can the benefit be observed* — was resolved empirically against the live Copilot proxy. Both halves fail:

| Question | Answer at HEAD | Consequence |
|---|---|---|
| Can `LLMRequest` / `OpenAICompatibleClient` express a cache directive today? | **No.** `LLMRequest` (`types.py:241-257`) has no cache field. `_call_openai_compatible` builds a closed payload of `model` / `messages` / `temperature` / `max_tokens` / optional `top_p` / optional `tools`+`tool_choice` (`llm_client.py:1828-1840`). | Cheap to add — this is **not** the blocker. |
| Does the Copilot proxy honour `cache_control`? | **No evidence it does, and strong evidence it does not.** A *malformed* directive is accepted with HTTP 200. | The directive is not reaching an Anthropic validator. |
| Can the benefit be measured? | **No. There is no measurement channel of any kind.** The proxy returns `usage` as a fixed zero stub on every request. | Acceptance criterion *"cache hit/miss surfaced in token accounting"* is **unachievable**, not merely hard. |

**Shipping AD-1149 at HEAD would add a config flag, a request field, and a test asserting that the field we wrote is the field we wrote. That is a placebo with a test suite.** Recommend closing #1074 with the unblock conditions in §Unblock, and re-opening when the endpoint changes.

**Both readings of the probe lead to the same verdict**, which is why this is decisive rather than merely suggestive:

- **Reading A — the proxy strips `cache_control` before forwarding.** Then the directive has no effect. Defer.
- **Reading B — the proxy forwards `cache_control` unvalidated.** Then it *might* have an effect, but with `usage` reporting zeros there is no way to observe, verify, or regress it. An optimisation nobody can measure is indistinguishable from dead code. Defer.

---

## The gating experiment (reproduce before overriding this verdict)

Run against the live proxy. No repo files touched; the script lives in `%TEMP%`.

```python
# %TEMP%\ad1149_probe.py  — POST http://127.0.0.1:8080/v1/chat/completions
# FILLER = ~1500 tokens of stable text (clears Anthropic's 1024-token cache minimum).
# A: plain string system, no directive
# B: system content as blocks, cache_control {"type": "ephemeral"}   (write)
# C: byte-identical repeat of B                                       (expect read hit)
# D: unknown top-level field  "prompt_cache_key": "probos-ad1149-probe"
# E: malformed directive       cache_control {"type": "NOT_A_REAL_CACHE_TYPE"}
```

Observed, 2026-07-26, proxy up (`GET /v1/models` → 200, advertising `claude-opus-4.6`, `claude-opus-4.7`, `claude-opus-4.8`, `claude-opus-5`, `claude-sonnet-*`):

```
--- A baseline plain-string system      : HTTP 200  usage = {"completion_tokens":0,"prompt_tokens":0,"total_tokens":0}
--- B cache_control block (write)       : HTTP 200  usage = {"completion_tokens":0,"prompt_tokens":0,"total_tokens":0}
--- C cache_control block (repeat)      : HTTP 200  usage = {"completion_tokens":0,"prompt_tokens":0,"total_tokens":0}
--- D unknown top-level cache key       : HTTP 200  usage = {"completion_tokens":0,"prompt_tokens":0,"total_tokens":0}
--- E malformed cache_control type      : HTTP 200  usage = {"completion_tokens":0,"prompt_tokens":0,"total_tokens":0}

response top-level keys : ['choices', 'created', 'id', 'model', 'object', 'usage']
choice keys             : ['finish_reason', 'index', 'message']
message keys            : ['content', 'role']
```

Three findings, each independently sufficient:

1. **`usage` is a zero stub, universally.** Identical on `claude-sonnet-4.6` and `claude-opus-4.6`, on a ~1500-token prompt that certainly consumed tokens. There is no `prompt_tokens_details`, no `cached_tokens`, no `cache_read_input_tokens`, no `cache_creation_input_tokens`. **The response carries no token information at all.**
2. **A malformed `cache_control.type` returns 200 with normal output.** A conforming Anthropic passthrough rejects anything outside the documented type set at the schema layer. A 200 means the directive never met that validator.
3. **An unknown top-level field is accepted silently.** So #1074's acceptance criterion *"an endpoint that does not support caching still succeeds — no error, no retry storm"* is **already satisfied by an endpoint that ignores everything**. It passes whether or not caching works, and therefore proves nothing. It cannot be used as evidence the feature functions.

---

## ⛔ CORRECTION 1 — "the prefix changes every turn and nothing is cacheable" is **false on both paths**

Issue #1074 states the AD is blocked on AD-1146 because *"the loop rebuilds one flat `prompt` string per iteration (`agentic_loop.py:155`), so the prefix changes every turn and nothing is cacheable."*

**The system prompt is byte-identical across every iteration on both paths at HEAD.** The loop passes the same `system_prompt` argument unchanged on each turn — structured (`agentic_loop.py:731-746`) and flattened (`agentic_loop.py:747-758`) alike — and the transport emits it as `messages[0]` either way (`llm_client.py:1797-1803`). `tools` is the same list object on both branches. So a stable, cacheable prefix of `system + tools` **already exists**.

| | Structured ON (AD-1146) | Structured OFF (shipped default) |
|---|---|---|
| `messages[0]` system content | stable | stable |
| `tools` array | stable | stable |
| First user turn | stable (the original task, `agentic_loop.py:685-688`) | **rebuilt every turn** — the whole transcript is re-flattened into one user string (`agentic_loop.py:749-751`) |
| Cacheable region | system + tools + **all prior turns** | system + tools **only** |

**The correct statement is not "nothing is cacheable" — it is "the cacheable region is short, and only AD-1146 makes it long."** That changes the AD's shape: it is not blocked on AD-1146 for *correctness*, it is blocked on AD-1146 for *value*. See DD-5.

**Also note `agentic_loop.py:155` is not the flattening site at HEAD.** The flattening is `agentic_loop.py:749-751`; line 155 sits inside the AD-1151 trace-bounds documentation. The reference has drifted since the issue was written.

---

## ⛔ CORRECTION 2 — "surface cache hit/miss in the existing token accounting" presumes accounting that does not exist

Issue #1074: *"Surface cache hit/miss in the existing token accounting so the saving is measurable."*

There is no existing token accounting on the primary endpoint. `_call_openai_compatible` reads `usage.total_tokens` / `usage.prompt_tokens` / `usage.completion_tokens` (`llm_client.py:1898-1901`) and the proxy returns `0` for all three. The parsing is correct; the source is empty.

**Knock-on finding, out of scope for AD-1149 but the Captain should know:** `AgenticLoop` accumulates `result.total_tokens += int(response.tokens_used or 0)` (`agentic_loop.py:774`), so against the primary endpoint that counter is **permanently zero**. The `token_budget` hard stop immediately below it therefore **can never fire on the shipped text tiers**. AD-1142's `crew_token_budget` ships at `None` so nothing regressed, but any operator who sets a spend ceiling today gets a knob that is inert. That is a genuine defect and a bigger prize than caching — see §Unblock.

---

## ⛔ CORRECTION 3 — "verify per-endpoint behaviour at build rather than assuming" — done, and the answer is negative

Issue #1074 got this instruction exactly right. It has now been executed. The verification did not confirm the premise; it falsified it. **Do not treat the instruction as still-open work. It is closed, with a negative result.**

There is also no second endpoint to fall back on for measurement. The agentic loop runs on `self._tier`, a text tier; `fast`, `standard`, and `deep` all resolve to `http://127.0.0.1:8080/v1` (`config/system.yaml:31,38,42,46`). The only non-proxy endpoints configured are `vision` and `vision_fast` on Ollama (`:50,:63`), which the loop never uses — and Ollama's OpenAI-compatible shim exposes no client-side prompt-cache directive either. **There is no arm of this system where the effect could be measured today.**

---

## Pinned design decisions

### DD-1 — Gating: expressible, not honourable, not measurable ⇒ **defer**

Adding a cache field to `LLMRequest` and emitting it from `_call_openai_compatible` is a ~20-line change. That was never the difficulty. The difficulty is that the only endpoint the agentic loop talks to discards the directive and reports no tokens. **AD-1149 is deferred on evidence, not on effort.**

### DD-2 — Where the stable prefix boundary sits (for whenever this is unblocked)

**Boundary: after the system prompt and after the tool-definitions block — i.e. `system + tools`, not through the first user turn.**

Rationale: `system` and `tools` are stable on **both** loop paths (Correction 1), so a `system + tools` breakpoint is the one placement that is correct regardless of the AD-1146 flag. Extending through the first user turn is only sound with `structured_tool_messages = True`; on the flattened path the single user turn is the whole growing transcript and would be a guaranteed miss every turn while also being the largest block. **Placing a breakpoint on the flattened user turn would cost cache-write overhead on every iteration and return nothing.** Do not do it.

### DD-3 — What invalidates the prefix

The "stable" prefix is stable *within one child's run*, not across children. Every item below produces a distinct cache entry, so the cache population is per-child, not per-system:

| Invalidator | Mechanism | Scope of divergence |
|---|---|---|
| Per-agent system prompt | `run(system_prompt=...)` is caller-supplied | per agent |
| Per-agent / per-department / per-grant tool set | `run(tools=...)` is caller-supplied | per agent, and per grant change *within* an agent |
| AD-835 per-tier `system_prompt_suffix` | appended to the system message by the transport, resolved from the **attempt** tier (`llm_client.py:1301`, applied `:1817-1826`) | changes on tier fallback mid-run |
| Tier fallback `deep → fast → standard` | `model` changes (`claude-opus-4.6` ↔ `claude-sonnet-4.6`, `config/system.yaml:34-36`) | provider caches are per-model — a fallback is always a cold cache |
| AD-1142 compaction | rewrites `messages` (see DD-4) | once per compaction event |

**Consequence for the value case:** a fleet of N crew children with N distinct system prompts and tool sets shares nothing. The saving is *within* one child's iterations only. That is still real — a 25-iteration child re-sends its system prompt 25 times — but it is not the fleet-wide win the issue's framing implies.

### DD-4 — Interaction with AD-1142 compaction

`SessionCompactor.compact` **preserves `messages[0]` verbatim when it is the system message** (`session_compactor.py:90-92`) and preserves the original user turn by identity (`:95-98,:108-109,:139`). So:

- **The `system + tools` breakpoint survives compaction intact.** DD-2's boundary is compaction-safe by construction. This is the second reason to put the boundary there and not further in.
- **Everything after the summary-insertion point is a new prefix.** The turn immediately following each compaction is a guaranteed miss beyond `system + tools`, and re-pays the cache-write cost for the new suffix.
- The compaction trigger is occupancy-based (`agentic_loop.py:717-722`) and fires at most once per iteration, so the miss rate is bounded by compaction frequency rather than being pathological. Compaction is also best-effort and may return the history unchanged (`agentic_loop.py:903-913`), in which case the prefix is untouched.

**No change to AD-1142 semantics is permitted by this AD.** Compaction must not be re-ordered, delayed, or made cache-aware. A cache is an optimisation; compaction is a correctness bound on the working context. The bound wins.

### DD-5 — The AD-1146 dependency, stated plainly: two default-OFF flags multiply

`structured_tool_messages` ships **`False`** (`config.py:4396-4405`) and is pinned `False` in the ablation (`tests/ablation/sigma_report.py:109`). AD-1149 would also ship default-OFF per convention #14.

**Two default-OFF flags in series means the feature is off in every shipped configuration.** Even granting a cooperative endpoint, AD-1149 would deliver zero production effect until someone flips `structured_tool_messages` — and with it OFF the cacheable region is `system + tools` only, which is the smallest and least valuable slice.

**Therefore: AD-1149 is effectively dead until `structured_tool_messages` defaults ON**, independently of the proxy question. That is a second, orthogonal reason to defer. Flipping AD-1146's default is its own decision with its own risk surface (it changes the wire shape for every agentic call) and must not be smuggled in as a side effect of a caching AD.

### DD-6 — AD-1147 parallel execution does **not** destabilise the prefix. Confirmed.

`_execute_tool_uses` reassembles strictly by request index — `return [by_index[index] for index in range(len(tool_uses))]` (`agentic_loop.py:1034`) — never by completion order, on both the sequential default path and the parallel path. `partition_tool_uses` covers every index exactly once. The `role:"tool"` messages therefore appear in a deterministic order that matches the assistant turn's `tool_calls` array.

**No risk here, and no work for AD-1149.** Recorded so the question is closed rather than re-litigated. If a future AD ever makes result ordering completion-dependent, that AD invalidates prefix stability and must say so.

### DD-7 — Measurement: what would count, and why nothing available counts today

A cache optimisation is acceptable only with a **provider-reported** signal. Acceptable signals:

- OpenAI-shape: `usage.prompt_tokens_details.cached_tokens`.
- Anthropic-shape: `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens`.

**Not acceptable as a substitute:**

- Wall-clock latency delta. Confounded by proxy queueing, model load, endpoint cooldown (BF-674), and lane contention. Not reproducible in a gate.
- Locally computed "tokens we would have re-sent". That measures our own arithmetic, not the provider's behaviour.
- The presence of the directive in the outbound payload. See DD-9.

Today the proxy supplies **none** of these, and supplies no token counts at all.

### DD-8 — Default posture: not applicable

The AD does not ship. If it is later unblocked, the posture is default-OFF per convention #14, byte-identical when off — the `cache_control` key must be absent from the payload dict entirely when the flag is off, not present-and-empty.

### DD-9 — What an offline test can assert, and why that is not enough

An offline test **can** be written today. `tests/test_ad1146_multiturn_messages.py:88-104` already has `_CapturingHTTPClient`, which captures the final `chat/completions` payload without a live provider. An AD-1149 test could assert:

- flag OFF ⇒ payload dict byte-identical to HEAD (achievable, and genuinely useful);
- flag ON ⇒ `messages[0].content[0].cache_control == {"type": "ephemeral"}` (achievable);
- the prefix bytes are identical across iterations 1..N of one run (achievable, and the one assertion in #1074 that is both offline-checkable and non-tautological).

It **cannot** assert a cache hit, a token saving, or any provider behaviour.

**The first two bullets are tautologies.** They assert that the field we chose to write is the field we wrote. Under Reading A of the probe they would pass green forever while the feature does nothing whatsoever. **A green suite that cannot distinguish "working" from "silently discarded" is worse than no feature**, because it manufactures confidence. This is the single most important reason to defer rather than to ship with a caveat.

The third bullet — prefix-stability assertion — is the only durable value in the AD, and it is worth extracting **only if** caching is actually coming. See §Unblock.

### DD-10 — Endpoint governance is untouched either way

For the record, so a future build does not re-derive it: any eventual implementation adds a request-body field only. It must not touch `_client_key` (`llm_client.py:324`), the endpoint permit/lease/generation machinery, the BF-674 shared-endpoint cooldown, or the tier fallback chain `_TIER_ORDER` (`llm_client.py:46`). A cache directive is payload, not lifecycle.

---

## Unblock — exactly what must change before AD-1149 is worth building

**All three. Any one alone is insufficient.**

1. **The primary endpoint must report token usage.** `usage.prompt_tokens` must be non-zero and truthful for a request that consumed tokens. Re-run the §Gating experiment; case A must return non-zero counts. *Without this, nothing about cost or caching is observable — and this also un-breaks the `token_budget` stop (Correction 2), which is arguably the larger prize and should be pursued on its own merits regardless of caching.*
2. **The endpoint must report a cache-specific signal.** `cached_tokens`, or `cache_read_input_tokens` + `cache_creation_input_tokens`. Case C in the experiment must show a read hit that case A does not. *Without this there is a hit/miss ratio nobody can see.*
3. **`agentic_loop.structured_tool_messages` must default ON**, via its own AD with its own risk review. *Without this the cacheable region is `system + tools` only and two default-OFF flags multiply to zero (DD-5).*

**Corroborating evidence that would also settle it:** the proxy rejecting a malformed `cache_control.type` with a 4xx. That would prove the directive reaches a real validator, which is currently the strongest single piece of counter-evidence.

**Recommended sequencing if the Captain wants to pursue this line:** condition 1 first, as its own item — token accounting is independently valuable, unblocks the inert `token_budget` stop, and is a strict prerequisite for 2. Then re-probe for 2. Only then revisit AD-1149 and condition 3. Do not mint a number for the token-accounting item here; the ceiling is AD-1152 / BF-680 and the Captain decides whether it is an AD or a BF.

---

## What to build IF and ONLY IF §Unblock is satisfied

Recorded so the design survives the deferral. **Not authorisation to build.**

1. `LLMRequest.cache_breakpoints: list[str] | None = None` (`types.py:241`) — semantic marker names (`"system"`, `"tools"`), not provider syntax. `None` preserves today's shape exactly.
2. `_call_openai_compatible` (`llm_client.py:1828`) translates markers to provider syntax at the transport boundary, following the AD-835 `effective_system_suffix` precedent: resolved from the **attempt** tier config at the call site (`llm_client.py:1301`) and threaded down as a parameter. **The transport must never read global tier state.** The AD-835b forward marker in that method's docstring (`llm_client.py:1779-1786`) names exactly this seam.
3. `LLMResponse` gains `cached_prompt_tokens: int = 0` and `cache_written_tokens: int = 0`, parsed alongside the existing `usage` reads (`llm_client.py:1898-1901`), defaulting to `0` when absent — honest-degrade, never an error.
4. `AgenticLoopConfig.prompt_caching_enabled: bool = False` (`config.py`, beside `structured_tool_messages` at `:4396`), pinned `False` in `PINNED_AGENTIC_LOOP` (`tests/ablation/sigma_report.py:108`) so the ablation fingerprint records the posture.
5. Breakpoints placed per DD-2 (`system + tools`), never on the flattened user turn.

---

## Do NOT build here

- Any change to AD-1146 / AD-1147 / AD-1148 / AD-1151 / AD-1142 semantics, defaults, or wire shape. **Flipping `structured_tool_messages` to default-ON is explicitly out of scope** — it is Unblock condition 3 and belongs to its own AD.
- A second LLM client, or a provider-abstraction layer.
- Provider-specific forks of the agentic loop. One loop, one transport, adaptation at the tier-config boundary only.
- Response caching. Distinct from prompt caching; the AD-617-era result cache already exists.
- Any change to tier/fallback logic, `_client_key`, endpoint concurrency governance, lease/generation handling, or the BF-674 cooldown.
- Anything requiring a live provider in the default gate.
- Latency-based or locally-computed "savings" telemetry as a stand-in for provider-reported cache counters (DD-7).

---

## Files (verify each at build)

| Path | Role | Touched by this AD |
|---|---|---|
| `src/probos/types.py` | `LLMRequest` `:241` / `LLMResponse` `:261` | **No** (deferred) |
| `src/probos/cognitive/llm_client.py` | payload construction `:1828`; `usage` parse `:1898-1901`; tier-config seam `:1301` | **No** (deferred) |
| `src/probos/cognitive/swe_harness/agentic_loop.py` | both request shapes `:731-758` | **No** (deferred) |
| `src/probos/config.py` | `AgenticLoopConfig` `:4396+` | **No** (deferred) |
| `tests/ablation/sigma_report.py` | `PINNED_AGENTIC_LOOP` `:108` | **No** (deferred) |
| `prompts/ad-1149-prompt-caching.md` | this document | **Yes** — the only artifact |
| `PROGRESS.md` · `docs/development/roadmap.md` | deferral record | **Yes**, on Captain's decision |

**Test files named for the record — none are to be run or created under this deferral:**

- `tests/test_ad1149_prompt_caching.py` — would be new; **do not create**.
- `tests/test_ad1146_multiturn_messages.py` — payload byte-identity regression; **do not run**.
- `tests/test_llm_client.py` — transport regression; **do not run**.
- `tests/test_ad1142_crew_child_compaction.py` — compaction-interaction regression; **do not run**.

**The full suite must NOT be run.** No source changes are authorised, so there is nothing to gate.

---

## Builder checks (unverifiable from this spec — confirm before relying on it)

1. **Re-run the §Gating experiment yourself.** A proxy build can change under you. If case A returns non-zero `prompt_tokens`, or case E returns a 4xx, **stop and escalate** — this verdict was correct on 2026-07-26 and may no longer be.
2. Confirm the proxy is the one ProbOS actually uses: `config/system.yaml:31` `llm_base_url: http://127.0.0.1:8080/v1`, with `standard` and `deep` `null` (`:42,:46`) and therefore inheriting it.
3. Confirm `structured_tool_messages` still defaults `False` (`config.py:4397`) and is still pinned `False` in the ablation (`tests/ablation/sigma_report.py:109`). If either flipped, DD-5 changes and the value case must be re-argued.
4. Confirm `_execute_tool_uses` still returns by request index (`agentic_loop.py:1034`). If a later AD makes ordering completion-dependent, DD-6 is void.
5. Confirm `SessionCompactor` still preserves `messages[0]` when it is the system message (`session_compactor.py:90-92`). If that changes, DD-4's compaction-safe boundary is void.
6. The zero-`usage` finding implies `result.total_tokens` (`agentic_loop.py:774`) is permanently `0` against the primary endpoint and the `token_budget` stop cannot fire. **Verify this independently before it is acted on** — it is a Correction-2 side finding, not a claim this AD tested end-to-end.

---

## Tracking

On Captain's decision to defer:

- **`PROGRESS.md`** — record AD-1149 as **DEFERRED (not built)** with the one-line reason: *"the Copilot proxy silently discards `cache_control` and reports a zero `usage` stub, so neither the directive nor its benefit is observable; see `prompts/ad-1149-prompt-caching.md` §Unblock."* State that AD-1152 remains the AD ceiling and BF-680 the BF ceiling — **no number is consumed by a deferral**.
- **`docs/development/roadmap.md`** — mark the AD-1149 row deferred, linking this document.
- **`DECISIONS.md`** — **no entry.** A deferral is not an architectural decision about the system; it is a decision about the work queue. The reasoning lives in this prompt and in `PROGRESS.md`.
- **Issue #1074** — close as *deferred, not-planned-at-HEAD*, quoting §Unblock verbatim so the reopen conditions are unambiguous. Epic #1068 stays open; AD-1149 is one item within it, not the epic.

---

## Done-when

- [ ] The Captain has read the §Gating experiment results and accepted or overridden the verdict.
- [ ] `PROGRESS.md` records the deferral with its one-line reason and confirms no AD number was consumed.
- [ ] `docs/development/roadmap.md` AD-1149 row marked deferred.
- [ ] Issue #1074 closed with §Unblock quoted.
- [ ] No source file changed. No test file created. No test run.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-07-26, HEAD `43b3cee3`)

```
# Working tree clean at investigation time.
git log --oneline -1
  43b3cee3 AD-1142: crew-child context compaction + token budget
git status --short
  (empty)

# AD / BF ceilings — AD-1149 and AD-1150 unused in all trackers.
AD max across PROGRESS.md, DECISIONS.md, roadmap.md, decisions-era-5-unification.md : 1152
BF max across PROGRESS.md, DECISIONS.md, roadmap.md                                 : 680
grep -n "AD-1149\|AD-1150" PROGRESS.md DECISIONS.md docs/development/roadmap.md
  (no matches)

# #1074's "0 matches" premise — accurate for the cache identifiers.
grep -rn "cache_control\|prompt_cache\|cached_tokens" src/probos/
  (no matches; "ephemeral" matches exist only in execution/ scratch-dir contexts, unrelated)

# LLMRequest has no cache field; LLMResponse.cached is not provider prompt caching.
src/probos/types.py
  241: class LLMRequest:
  253:     tools: list[dict] | None = None
  258:     messages: list[dict] | None = None
  261: class LLMResponse:
  268:     cached: bool = False          # hardcoded False by the transport, llm_client.py:1911

# The payload is a closed dict — no seam for a cache directive today.
src/probos/cognitive/llm_client.py
  1803:     messages.append({"role": "user", "content": request.prompt})
  1828:     payload = {
  1839:     payload["tools"] = request.tools
  1898:     usage = data.get("usage", {})
  1899:     tokens_used = usage.get("total_tokens", 0)
  1900:     prompt_tokens = usage.get("prompt_tokens", 0)

# System message emitted at index 0 on BOTH request shapes (Correction 1).
  1797:     if request.system_prompt and not (messages and messages[0].get("role") == "system"):
  1798:         messages.insert(0, {"role": "system", "content": request.system_prompt})
  1802:         messages.append({"role": "system", "content": request.system_prompt})

# AD-835 tier-config seam (the sanctioned precedent for a transport-level directive).
  1301:     effective_system_suffix = tc.get("system_prompt_suffix")
  1779-1786: AD-835b forward marker naming per-tier tool-format remapping as the planned extension.

# Both loop paths pass the SAME system_prompt every iteration (Correction 1).
src/probos/cognitive/swe_harness/agentic_loop.py
   685:     messages: list[dict] = [
   731:     if self._structured_tool_messages:
   749:         assembled_user_prompt = "\n\n".join(       # flattened path rebuilds the USER turn only
   774:     result.total_tokens += int(response.tokens_used or 0)   # permanently 0 vs the proxy
  1034:     return [by_index[index] for index in range(len(tool_uses))]   # DD-6 order preservation

# Compaction preserves messages[0] system verbatim (DD-4).
src/probos/cognitive/swe_harness/session_compactor.py
    90:     system_msg = (
    91:         messages[0]
    92:         if messages and messages[0].get("role") == "system"

# AD-1146 ships default-OFF and is pinned OFF in the ablation (DD-5).
src/probos/config.py
  4396:     structured_tool_messages: bool = Field(
  4397:         default=False,
tests/ablation/sigma_report.py
   108: PINNED_AGENTIC_LOOP: dict[str, Any] = {
   109:     "agentic_loop.structured_tool_messages": False,

# Every text tier resolves to the Copilot proxy; only vision leaves it (Correction 3).
config/system.yaml
    31:   llm_base_url: http://127.0.0.1:8080/v1
    38:   llm_base_url_fast: http://127.0.0.1:8080/v1
    42:   llm_base_url_standard: null
    46:   llm_base_url_deep: null
    50:   llm_base_url_vision: http://127.0.0.1:11434/v1
    34:   llm_model_fast: claude-sonnet-4.6
    36:   llm_model_deep: claude-opus-4.6

# Offline payload-capture harness already exists (DD-9).
tests/test_ad1146_multiturn_messages.py
    88: class _CapturingHTTPClient:
    89:     """httpx.AsyncClient stand-in capturing the final chat/completions payload."""

# Live proxy probe, 2026-07-26 — the gating evidence.
GET  http://127.0.0.1:8080/v1/models                      -> 200, claude-opus-4.6/4.7/4.8/5, claude-sonnet-*
POST http://127.0.0.1:8080/v1/chat/completions  case A    -> 200, usage {0,0,0}
POST                                            case B    -> 200, usage {0,0,0}   (cache_control write)
POST                                            case C    -> 200, usage {0,0,0}   (byte-identical repeat)
POST                                            case D    -> 200, usage {0,0,0}   (unknown top-level field)
POST                                            case E    -> 200, usage {0,0,0}   (MALFORMED cache_control.type)
response top-level keys: ['choices','created','id','model','object','usage']  -- no cache fields anywhere
```
