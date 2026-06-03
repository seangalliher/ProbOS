# BF-599 — Yeo confabulates "I can't browse the web" despite a live `web_search` capability (conversational front-door does not see or route to mesh capabilities)

**Status:** Architect-reviewed (verify-first pass complete) — ready for Builder
**Issue:** https://github.com/seangalliher/ProbOS/issues/814 — conversational front-door capability-gap confabulation
**Target repo:** OSS (`d:\ProbOS`)
**Wave:** 209
**Scope decision (Architect):** Ship **D1 only** (capability grounding). D2 (auto-delegation routing on the
DM path) is split out to child **BF-599b** — Yeo overrides neither `act()` nor the response pipeline, so
actually performing+summarizing a mesh fetch is materially larger than a single grounding commit. D1 alone
stops the confabulation (the LLM stops refusing once the live capability is in its prompt).
**Forward markers:** BF-599b (D2 delegation routing); AD-840 (generalized reusable `ResearchSkill`, see §6)
**One commit** titled: `fix(yeoman): BF-599 ground Yeo in live ship capabilities (stop web-research confabulation)`

> **Architect verify-first corrections baked into this revision:**
> 1. **Intent name fix.** `PageReaderAgent` registers the intent **`read_page`** (params `{"url": ...}`),
>    NOT `page_reader`. `page_reader` is only the agent_type / pool name. Surface/route `read_page`.
> 2. **D1 cannot be yeoman.py-only.** The conversational (`direct_message`) path builds the system prompt
>    via `compose_instructions(..., hardcoded_instructions="")` in `cognitive_agent._decide_via_llm`
>    (~L2222) — Yeo's `instructions`/`_ROLE_RULES` are NOT in the DM prompt. A base-class extension hook
>    is required (see §2.1). This is the reusable seam §7 wants.
> 3. **Registry accessor.** There is no "list registered intents" method. Use
>    `runtime.registry.get_by_pool("web_search" | "page_reader" | "http")` presence checks (the real public
>    API on `AgentRegistry`), or iterate `registry.all()` reading each agent's `.intent_descriptors`
>    (pattern: `agent_onboarding.py:151`). Do NOT invent `registry.registered_intents()`.
> 4. **Verified live:** `http` pool = 3 instances (unconditional builtin); `web_search`/`page_reader` pools
>    = 2 each, gated on `config.utility_agents.enabled`; `_CAPABILITY_GAP_RE` importable from
>    `probos.cognitive.decomposer`; `_mesh_fetch` broadcasts `http_fetch`.

---

## 1. Problem

The Captain asked Yeo (the Yeoman / conversational front-door, AD-766) whether it could research a
live URL (`https://learn.microsoft.com/en-us/microsoft-scout/overview`). Yeo replied that it is unable
to browse live URLs or fetch web content and suggested filing the capability as a *gap*.

**That refusal is a confabulation.** The capability exists and is running:

- **`http_fetch`** — [`HttpFetchAgent`](src/probos/agents/http_fetch.py) registers the `http_fetch` intent
  ("Fetch a URL via HTTP and return the response"). The `http` pool is spawned at startup with **3 live
  instances** ([`startup/agent_fleet.py`](src/probos/startup/agent_fleet.py), `("http", "http_fetch", 3)`).
  It owns per-domain rate limiting and `Retry-After`/`429` handling.
- **`web_search`** — [`WebSearchAgent`](src/probos/agents/utility/web_agents.py) registers `web_search`
  ("Search the web and return summarized results") and implements it by broadcasting `http_fetch` through
  the mesh via `_mesh_fetch()`. **It never calls `httpx` directly** (Design Principle #10).
- **`page_reader`** — [`PageReaderAgent`](src/probos/agents/utility/web_agents.py) registers `page_reader`
  (read + summarize a specific URL), same mesh-fetch pattern.

So the Bridge can already search the web and read pages. Yeo just cannot *see* those capabilities and does
not *route* to them.

### Root cause (classification: capability exists, conversational path neither advertises nor delegates to it)

1. **Yeo's instructions are silent on web capability.** Yeo's system prompt is only
   `persona + _ROLE_RULES` ([`yeoman.py:141`](src/probos/cognitive/yeoman.py#L141), reassigned in
   `initialize()` at [`yeoman.py:215`](src/probos/cognitive/yeoman.py#L215)). Neither `_DEFAULT_PERSONA`,
   the Captain Card persona, nor `_ROLE_RULES` mentions `web_search`, `http_fetch`, `page_reader`, or
   research/browsing.
2. **No live capability map is injected into any CognitiveAgent's decision context.** There is no code path
   that renders the registry's registered intents into the system prompt. Yeo answers capability questions
   from a static string, not from the live registry — the same failure class the AD-317→320 Ship's Computer
   grounding work fixed for the *decomposer*, but Yeo was never put on that grounding.
3. **Direct messages bypass the decomposer.** A DM/@-mention to Yeo arrives as a conversational intent and
   runs Yeo's `decide()` → `_decide_via_llm()` straight from `self.instructions`. The `IntentDecomposer`
   — which *would* map "research this URL" → `web_search`/`page_reader` — is not invoked on the DM path.
   So even though the decomposer knows the capability, Yeo's conversational reply never consults it.

The net effect: the LLM is asked "can you browse?", sees no browsing capability in its prompt, and asserts a
hard refusal instead of delegating.

> **Gap-regex caution (repo standing flag).** Yeo's *refusal text* matched the capability-gap pattern
> (`_CAPABILITY_GAP_RE`: "can't", "unable to", "don't have"). Any NEW instruction text added by this BF MUST
> be phrased positively (e.g. "Web research is available by delegating to …") and MUST NOT contain
> "can't / cannot / unable to / don't have", or it will trip the gap regex and/or re-teach the refusal.

---

## 2. Design

D1 (capability grounding) only — D2 is split to BF-599b (see header scope decision). Do NOT add direct
`httpx` calls to Yeo — all web access stays mesh-delegated (Design Principle #10).

### 2.1 D1 — Capability grounding (the fix)

Give Yeo a **live, registry-derived** list of delegatable ship capabilities so it answers from reality.

**Base-class hook (required — see correction #2).** The conversational path uses
`hardcoded_instructions=""`, so the block CANNOT go in Yeo's `instructions`. Add a small overridable hook on
`CognitiveAgent` and append it to the assembled conversational prompt:

- In [`src/probos/cognitive/cognitive_agent.py`](src/probos/cognitive/cognitive_agent.py), add a protected
  method `def _conversational_capability_block(self, observation: dict) -> str:` that returns `""` by
  default (so no other agent's behavior changes — OCP/LSP preserved).
- In `_decide_via_llm`, inside the `is_conversation` branch, after `composed` is built and the
  intent-specific blocks are appended (and before the AD-809 personality-overlay append), do:
  `composed += self._conversational_capability_block(observation)` — guard for non-empty so the default
  no-ops cleanly. This is the reusable grounding seam (forward §7 / shared mixin candidate).

**Yeo override (in [`yeoman.py`](src/probos/cognitive/yeoman.py)).** Override
`_conversational_capability_block` to render a compact, registry-derived block naming the web-research
capabilities that are actually live:

- Read the live registry via `self._runtime.registry` and check pool presence with
  `registry.get_by_pool("web_search")`, `registry.get_by_pool("page_reader")`, `registry.get_by_pool("http")`.
  Only include a capability line when its pool is present (so the block stays truthful as pools change).
- Map pool → (intent name, human description) using the REAL intent names:
  `web_search` pool → intent `web_search` ("search the web");
  `page_reader` pool → intent **`read_page`** ("read + summarize a URL");
  `http` pool → intent `http_fetch` ("fetch a URL").
- Honest-degrade: if `self._runtime` is None or has no `registry` (test rigs / federated peers), return `""`.
- The block MUST be positive/affirmative (gap-regex caution). Suggested shape (final wording Builder's
  discretion, but MUST avoid `can't`/`cannot`/`unable to`/`don't have`):
  `"\n\nShip capabilities you can delegate through the mesh: web_search (search the web), read_page (read +
  summarize a URL), http_fetch (fetch a URL). When the Captain asks you to research or read a web page,
  delegate to the right specialist (e.g. @NumberOne for Science research) rather than declining."`
  (Steer toward the EXISTING wired `[DM @callsign]`/`delegate_to_crew` path — Science callsign is
  `Number One` per `DELEGATION_MAP` — since auto-execute is BF-599b, not this commit.)

---

## 3. Acceptance criteria

- A test calling Yeo's `_conversational_capability_block(observation)` with a **real** `AgentRegistry`
  fixture (NOT `MagicMock` — phantom-attribute trap, repo conventions) in which `web_search`/`page_reader`/
  `http` pools have a registered stub agent, asserting the returned string contains `web_search`,
  `read_page`, and `http_fetch`.
- A test asserting the default `CognitiveAgent._conversational_capability_block` returns `""` (LSP: other
  agents unaffected).
- A test asserting Yeo's block returns `""` when `self._runtime` is None (honest-degrade).
- A test asserting the rendered block contains **none** of the gap-regex tokens — import and apply
  `_CAPABILITY_GAP_RE` from `probos.cognitive.decomposer` (`assert not _CAPABILITY_GAP_RE.search(block)`).
- No new direct `httpx`/`requests` import in `yeoman.py` (assert by source grep in the test).
- Full suite stays green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 4. Do NOT

- Do NOT add `httpx`/`requests` to Yeo or any crew agent — web access stays mesh-delegated.
- Do NOT bake the capability list into the static `instructions` string — render it from the live registry.
- Do NOT implement D2 auto-delegation/broadcast here — that is BF-599b. This commit is grounding only.
- Do NOT change the default behavior of any agent other than Yeo — the base hook MUST return `""` by default.
- Do NOT refactor the decomposer, the intent bus, or `WebSearchAgent`/`PageReaderAgent`.
- Do NOT invent a registry accessor — use `get_by_pool(...)` (verified public API) or `registry.all()`.
- Do NOT build the generalized `ResearchSkill` here (that is AD-840, §6).

## 5. Files

- `src/probos/cognitive/cognitive_agent.py` — default `_conversational_capability_block` hook (returns `""`)
  + one append line in the `is_conversation` branch of `_decide_via_llm`.
- `src/probos/cognitive/yeoman.py` — Yeo override of `_conversational_capability_block` (registry-derived).
- `tests/test_bf599_yeo_web_research_delegation.py` — new test module.
- `PROGRESS.md` + `DECISIONS.md` — BF-599 entry in the same commit.

## 6. Forward marker — AD-840 (out of scope)

The Captain's design question: *should crew agents perform web search directly, or use the Ship's Computer?*
Answer (already the codebase principle): **delegate through the mesh.** `web_search`/`page_reader` are the
reusable capability surface (the "tool"); a **research skill** is a thin orchestration any crew agent invokes
that delegates those intents through the mesh, inheriting governance (consensus, trust, per-domain rate
limiting, episodic logging) for free. AD-840 should define a reusable `ResearchSkill` (multi-source fetch →
synthesize → cite) so any crew member — not just Yeo — gains research by composing the existing tool, with
zero direct HTTP. BF-599 only closes the immediate Yeo confabulation/routing gap.

## 7. For-free learning

- Confirms the AD-317→320 grounding pattern (inject live system state into the prompt) should extend to ALL
  conversational crew agents, not just the decomposer. Candidate follow-up: a shared capability-grounding
  mixin so no agent confabulates its own limits again.
- Reinforces the mesh-delegation invariant (Design Principle #10) as the answer to "tool vs direct call":
  the Ship's Computer (mesh) is the single governed execution surface for tools.
