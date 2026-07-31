# AD-1153 — Offer the browser to the agentic loop, read-only (tools / agentic harness)

**Issue: #1080 · Epic #1068 (agentic harness parity). Depends on nothing; AD-1147 (#1072) and AD-1148 (#1073) are in-tree at HEAD `d0b36061`.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1153** (#1080). AD ceiling: AD-1155 assigned (#1082). BF ceiling: BF-681. No new AD. One new BF is authorised: **BF-682** (DD-8), file-only, do not fix.**

Give a crew agent a governed way to *read* a live web page from inside `AgenticLoop` — navigate, enumerate the page, extract its text — so a task that needs a real application's rendered state stops degrading to `http_fetch` or a confabulated verb. Default-OFF.

**v1 is read-only and that is the deliverable, not a compromise.** The rationale is in DD-1: the six actions offered here are the exact set that cannot reach the tier-3 confirmation gate, and the tier-3 gate is broken for an unattended caller. Ship the half that is safe now; the mutating half waits on AD-1154 (#1081).

---

## Why / context

`BrowserTool` (`tool_id="browser"`) is registered by `startup/finalize.py::_wire_browser_tool` (`:289`, AD-706), gated on `config.browser_tool.enabled` plus an importable Playwright. Both are satisfied on the Captain's machine. `WorkItemAgenticExecutor.run` assembles the offered set at `agentic_dispatch.py:964-969` from ten sources — `granted_ids, mesh_ids, mcp_ids, exec_ids, skill_ids, search_ids, delegate_ids, event_log_ids, oracle_ids, publish_ids`. There is no browser block.

Everything below was read off the live tree at HEAD `d0b36061`. Several of these contradict issue #1080; the corrections are load-bearing and the DDs turn on them.

**The invoke surface is 11 actions, not the whole handler table.** `BrowserTool.invoke` rejects any action outside `{goto, state, click, type, scroll, screenshot, wait, back, forward, extract_text, verify}` before touching a session (`tool.py:225-231`). `_HANDLERS` additionally holds `compute_use_click`, `drag`, `key_combo`, `mouse_move`, `mouse_button`, `upload_file`, `download`, `eval_js`, `fill_credential` (`actions.py:553`, `:778-795`) — **all nine are unreachable through `invoke`.** The `elif action == "compute_use_click"` / `"fill_credential"` branches inside `invoke` (`:378`, `:386`) are dead behind that guard. So the credential vault, arbitrary JS, and file upload/download are structurally out of reach of any `invoke` caller, including this one. That materially shrinks the surface this AD is reasoning about and nothing here widens it.

**`goto` is unconditionally tier 2.** `classify_action` returns `2` for `goto` at `actions.py:833` *before* any URL inspection. The tier-3 path tokens (`checkout`, `payment`, `transfer`, `subscribe`, `signup`, `register` — `actions.py:36-39`) and `tier_3_domain_patterns` are only consulted for `click`/`type`/`drag`/`mouse_button` (`actions.py:851-876`). **Navigating to `https://shop.example/payment` is not gated at all.** The Captain's stated fear — an unattended agent auto-approving a `*/payment*` navigation — is real, but the mechanism is *absence of a gate*, not a gate that auto-approves.

**`destructive_url_patterns` is not a BrowserTool guardrail.** Issue #1080 lists it among the tool's protections. It has exactly one reader in `src/`: `reply_pipeline.py:684`, inside the AD-745 DM dispatch stage. So do `url_matches_destructive_pattern` and the `action_dispatch_max_consecutive_autonomous` trust-budget cap. `BrowserTool.invoke` consults none of them. That path is gated on `browser_tool.action_dispatch_enabled` (`config.py:1761`), which is False and explicitly out of scope. **An agentic-loop caller gets domain allow/denylist, `classify_action` tiering, the tier-3 token gate, per-domain rate limiting and the session duration cap — and nothing else.**

**The tier-3 gate does not block and does not auto-approve. It returns a success.** `tool.py:305-312` returns `ToolResult(output={"intervention_required": True, "tier": 3, "session_id": ...})` with `error=None`. `ToolCallResult.from_tool_result` (`tool_call.py:51-65`) branches on `error is not None`, so the loop records `is_error=False` and hands the model the literal string `{'intervention_required': True, 'tier': 3, 'session_id': '...'}`. Neither of the two failure modes the Captain named is what happens: it **silently no-ops and reads as success**, which is worse than either, because the likely model behaviours are to narrate completion or to retry — and each retry mints a fresh token into `_pending_confirmations` (`tool.py:696-711`), pruned only by `reap_expired()` (`:206-214`).

**Rank is trust-derived, not a caste.** `_resolve_agentic_identity` sets `rank = Rank.from_trust(trust_network.get_score(agent_id)).value` (`agentic_dispatch.py:127-130`); the `rank=` argument to `run` is a fallback used only when registry, ontology and trust are *all* absent. `Rank.from_trust` (`crew_profile.py:38-47`) reads `TRUST_LIEUTENANT = 0.5` (`config.py:22`). Built-in agents seed at Beta(2,2) = 0.50 ⇒ **lieutenant**. Self-designed agents seed at Beta(1,3) = 0.25 ⇒ ensign. The resolved rank is written back into the loop context at `agentic_dispatch.py:1025-1032`, so offer-time and invoke-time agree.

**"Even a granted crew child gets nothing" is incorrect.** `resolve_permission` Layer 4 grants *up* over the rank matrix (`registry.py:359-367`), and `browser` is not in `_GATED_TOOL_IDS` (`:79`), so a Captain grant lands in `granted_ids` (`:756-762`). A Captain grant of `read` on `browser` to an ensign resolves to `read`; `check_and_invoke` requires only READ (`registry.py:310`). **The Captain escape hatch works today and must keep working.**

**Permission level cannot express a read/write split.** `check_permission` is keyed by `(agent_id, tool_id, required)` (`registry.py:285-302`) — there is no action dimension. And `AgenticLoop._run_one_tool_call` calls `self._executor.invoke(...)` without `required=` (`agentic_loop.py:1200-1207`), so `check_and_invoke`'s default `ToolPermission.READ` applies to **every** tool call. A `commander` (`write`) and a `lieutenant` (`read`) therefore receive an identical action surface. Answering the issue's decision #2 plainly: **a per-action permission split is not expressible through `check_permission`, by rank or by level.** The alternative is DD-1.

**Output is unbounded.** `from_tool_result` does `str(raw)` on the output dict (`tool_call.py:59`). `extract_text` returns `page.inner_text("body")` verbatim (`actions.py:325-337`); `state` returns the whole element list; `screenshot` returns a base64 PNG (`actions.py:257`). `tool_result_max_chars` ships at 0 (`config.py:4406`), so `_bound_tool_output` (`agentic_loop.py:1239-1245`) is a no-op on defaults. Answering the issue's decision #4: **yes, this needs its own cap.**

**`domain_allowlist` defaults to `None` = allow-all** (`config.py:1572`), subject only to an empty `domain_denylist`.

---

## Pinned design decisions

### DD-1 — v1 offers six read actions, enforced by a fail-safe allowlist. `click` / `type` / `scroll` / `screenshot` / `verify` wait for AD-1154

`_BROWSER_LOOP_ACTIONS = frozenset({"goto", "state", "extract_text", "back", "forward", "wait"})`

**Why these six and not the other five.** Under `classify_action`, `state`/`extract_text`/`back`/`forward`/`wait` are tier 1 (`actions.py:830`) and `goto` is tier 2 (`:833`). Tier-3 escalation is reachable *only* through `click`/`type`/`drag`/`mouse_button` (`:851`) and the always-3 verbs (`:817-828`), none of which are in this set. **The v1 allowlist provably cannot reach the tier-3 gate.** That is the whole argument: rather than depending on a confirmation flow that degrades to a success-shaped no-op for an unattended caller, this AD ships the subset for which that flow is never consulted. Assert it as a test — enumerate the six against the real `classify_action` and require `max(tier) <= 2`.

Excluded, each for its own reason:

| Action | Tier | Why out of v1 |
|---|---|---|
| `click`, `type` | 2 or 3 | The mutating verbs. Both can escalate to tier 3, and tier 3 is broken unattended. These are what AD-1154 (#1081) exists to unblock. |
| `scroll` | 1 | Classified silent, and it does not mutate server state — but it drives infinite-scroll fetches, and `extract_text` reads `inner_text("body")` (`actions.py:333`), which already includes off-screen text. No capability is lost. Minimal Authority: leave it out. |
| `screenshot` | 1 | Returns `screenshot_b64` (`actions.py:257`), which `str()` renders as raw base64 into the transcript. Enormous and semantically worthless to a text loop — pure context poison. If vision is wanted later it needs an `AttachmentStore` ref, which is a different AD. |
| `verify` | 1 | Makes a vision-tier LLM call and writes to `AttachmentStore` (`actions.py:610-745`). A cost and side-effect surface, not a page read. |

**Enforcement seam: `DispatchToolExecutor`, not `BrowserTool`.** `DispatchToolExecutor` (`agentic_dispatch.py:221-253`) subclasses `ToolExecutor`, is constructed only by this executor (`:720`), and its `invoke` already sees `tool_id` and `params`. Put the guard there. Consequences that make this the right seam and not merely a convenient one:

- **Zero edits under `src/probos/tools/browser/`.** The DM path calls `browser_tool.invoke(...)` directly (`reply_pipeline.py:752`) and is byte-identical.
- It is a **fail-safe partition, exactly like `PARALLEL_SAFE_TOOL_IDS`** (`agentic_loop.py:70-78`): membership is the only way through, so an unknown, renamed, or newly added action is refused by default. This is the reuse the issue asked for in decision #2 — same taxonomy, same failure direction, no second vocabulary.
- It is a **module constant, not a config field**, for the reason AD-1147/DD-1 gives verbatim: it is a safety property of the loop, not a tuning knob an operator should be able to widen. Do not add a `browser_allowed_actions` config field.

**Do not narrow a Captain grant.** With `browser_enabled` on, an agent can hold `browser` via *both* the new offer and a pre-existing Captain grant. Narrowing the grant path would silently revoke a working capability and invert Layer 4's grant-up semantics. So the restriction is armed **only when the tool reached the offer through the new block and `"browser" not in granted_ids`**. Give `DispatchToolExecutor` a public method — `restrict_browser_actions(actions: frozenset[str]) -> None` — called after the offer blocks resolve. A keyword-only constructor parameter would be more DIP-idiomatic, but the executor is constructed at `:720` and `granted_ids` is not known until `:756`; moving the construction ~250 lines is a larger refactor than this AD warrants. Name the tradeoff in the method docstring. Unarmed (the default) ⇒ `invoke` is byte-identical to today.

**Refusal shape.** A blocked action returns `ToolResult(error=<framed text>)` — an **error**, so `from_tool_result` sets `is_error=True` (`tool_call.py:51-57`) and the model corrects rather than believing it acted. Never a success-shaped no-op; that is the exact defect DD-1 exists to route around. The tool is never invoked, so no session is created.

### DD-2 — Rank floor: leave `ensign: none` exactly as registered. Do not touch `_wire_browser_tool`

The registered matrix is `{ensign: none, lieutenant: read, commander: write, senior_officer: full}` (`finalize.py:328-333`). It stays.

**AD-1140/DD-1's reasoning does not transfer, and the difference is worth stating.** That AD chose `write` at every rank because a floor above ensign would have made AD-1141 dead on arrival, and because a publish is additive and reversible — git history plus `_archived/` plus status promotion. Driving a live browser is neither additive nor reversible: the page is somebody else's system. Same axiom (Safety Budget), different risk class, different instrument.

**`ensign` is not a caste — it is trust < 0.5.** Because rank is derived from the trust score (`crew_profile.py:38-47`, `TRUST_LIEUTENANT = 0.5`), `ensign: none` denies the browser precisely to agents that are new, self-designed (Beta(1,3) = 0.25), or currently failing. That is Minimal Authority operating as designed, and it is the only non-trivial rank matrix on any tool in the registry — every sibling agentic tool ships an empty matrix (ship-wide READ) or `write` at every rank. Lowering it would erase the one place the trust ladder actually binds a capability.

**It is not dead on arrival.** Built-in agents seed at Beta(2,2) = 0.50 and are **already lieutenant**, so they get `read` on the day the flag is turned on. A crew child below the line earns in, or the Captain grants in — and the grant path already works (Layer 4 grant-up, `registry.py:359-367`).

**Do not add `browser` to `_GATED_TOOL_IDS`.** Adding it would drop the tool from `granted_ids` (`:756-762`) and force every grant through the rank matrix, which returns `none` for an ensign — **removing** the Captain's existing escape hatch for probationary agents. `event_log_query` / `oracle_query` / `publish_finding` are in that set because they carry `allowed_departments` and a raw grant would route around the department layer. **`browser` is registered with no `allowed_departments`** (`finalize.py:322-335`), so there is no department layer to route around and the gate has nothing to protect. Assert `"browser" not in _GATED_TOOL_IDS` as a regression guard.

**Offer-side check: `ToolPermission.READ`.** Matches what `check_and_invoke` will require at `:310` anyway, so an offered agent is an invoking agent — no tool that appears in the list then denies on use.

### DD-3 — Browser-specific output bounds, applied in the same guard, independent of `tool_result_max_chars`

`tool_result_max_chars` ships at 0 and a single `extract_text` on a long page can exceed any working-context budget on its own. AD-1148's bound is the right *outer* mechanism and is not changed here; this is an inner cap that holds on shipped defaults.

| Bound | Value | Justification |
|---|---|---|
| `_BROWSER_TEXT_MAX_CHARS` | `8000` | Head-truncate `output["text"]`. Sits between AD-1148's `TOOL_RESULT_HEAD_CHARS + TAIL` (4000 + 2000) and `TOOL_TRACE_OUTPUT_MAX_CHARS = 8192` (`agentic_loop.py:38-56`), so a bounded page read survives the durable trace intact. |
| `_BROWSER_MAX_ELEMENTS` | `100` | Cap `output["elements"]`. The element list exists so the model can name an index; a hundred is past the point of usefulness and the surplus is pure token cost. |

Truncation is **visible**, per AD-1148/DD-3 — a marker stating that content was elided and how much, so the agent re-queries with a narrower selector instead of reasoning on a silent prefix. Apply to the `ToolResult.output` dict before returning it, so both the loop transcript and the AD-1151 durable trace see the bounded value.

### DD-4 — Framing travels inline

`AgenticLoop` renders tool results as bare content with no consumer-side wrapper, so provenance rides in the result — the parenthetical shape of `_ORACLE_DISPOSITION` (`oracle_query_tool.py:87`) and `_VISUAL_DISPOSITION` (`working_memory.py:28`). A page read is a **live observation with a timestamp**, not a durable fact, and the framing must say so or the agent will treat a scraped price as ground truth.

**Gap-regex constraint.** No authored string may match `_CAPABILITY_GAP_RE` (`decomposer.py:33-41`, `re.IGNORECASE`). Read off the live pattern, the forbidden set is: `don't have` · `can't` · `cannot` · `unable to` · `no {capability|ability|support|way|mechanism|tool}` (also with `built-in ` / `native ` interposed) · `not {available|supported|possible}` · **`lack` / `lacks` / `lacking`** · `doesn't {have|support}` · `beyond {my|current} {capabilities|abilities}` · `outside {my|the} {scope|capabilities}`. `lack` is a bare substring — "black hole", "slack" and "blackhole" all trip it, and AD-1140 hit this for real. The refusal string in particular is the dangerous one, because the natural English for it is "cannot".

**All five strings below were run against the live `_CAPABILITY_GAP_RE` at HEAD `d0b36061` and are clean.** The Builder may improve the wording; the constraints are not negotiable, and **any reword must be re-run against the real imported regex**, not a re-typed copy.

- disposition — `"(This is live page content read from the open browser session. Treat it as an observation of the page at this moment, not as a durable fact. Cite the URL when you build on it.)"`
- refusal — `"The browser is offered in read-only mode for this session. Available actions: goto, state, extract_text, back, forward, wait. To act on the page itself, hand that step to the Captain."`
- text elision — `"\n\n... [truncated: {omitted} characters elided from this page read. Re-run extract_text with a narrower selector to retrieve the elided region.] ...\n\n"`
- element elision — `"[truncated: {omitted} further page elements elided. Narrow the page or re-run state after navigating.]"`
- egress warning — `"AD-1153: the loop browser offer is enabled while domain_allowlist is None; the agent may navigate to any host absent from domain_denylist. Set browser_tool.domain_allowlist to bound egress."`

### DD-5 — `PARALLEL_SAFE_TOOL_IDS` is not extended, and that is a decision

`browser` stays out of the AD-1147 allowlist (`agentic_loop.py:70-78`), so it runs sequentially with **no code change**. Read-only is not the same as parallel-safe: all six actions share one `BrowserSession`, `state()` writes the index map that a later call resolves against (`actions.py:86-93`), and two concurrent `goto`s on one page race. AD-1147's partition is fail-safe by default, so the correct action is *none* — but record it, because "it is read-only, add it to the allowlist" is the obvious wrong next move. Pin it with a membership assertion.

### DD-6 — Default-OFF, byte-identical

`agentic_tools.browser_enabled: bool = False` on `AgenticToolsConfig` (`config.py:6036`), beside `oracle_query_enabled` (`:6096`). Off ⇒ the offer block is skipped, `restrict_browser_actions` is never called, and both `tool_ids` and `DispatchToolExecutor.invoke` are byte-identical to today. Not a Σ flag; **do not touch `tests/ablation/sigma_flags.py`**.

The offer is gated on **both** `agentic_tools.browser_enabled` and `registry.get("browser") is not None` — the latter already carries `browser_tool.enabled` and the Playwright-import check from `_wire_browser_tool` (`finalize.py:294-310`). Two flags, one AND, no re-derivation of the availability logic.

### DD-7 — Egress is warned about, not forced

`_check_domain` runs only for `goto` (`tool.py:253`), which is the only navigation verb in the allowlist, so allow/denylist binds every navigation on this path. But `domain_allowlist` defaults to `None` = allow-all (`config.py:1572`), so on shipped defaults the agent may reach any host absent from the denylist.

Requiring a non-empty allowlist would make the feature useless for the research tasks that motivate it, so: **emit a one-shot WARNING at first offer** when `browser_enabled` is on and `domain_allowlist is None` (string in DD-4), and state the same in the config field description. Log-and-degrade, per the three-tier table. This lowers no existing guardrail and adds no new gate — it makes an existing default visible at the moment it starts mattering.

### DD-8 — The confirmation token leaks into the event log. Unreachable in v1. File **BF-682**; do not fix here

`tool.py:284-292` emits `TOOL_INTERVENTION_REQUIRED` with the raw `confirmation_token` in the payload. `event_log_query` (AD-1129) returns each row's `data` through `_wire_json` (`event_log_query_tool.py:193-198`, `:215`), which recurses dicts **without redaction**, and `event` is a free-text filter with no event-type allowlist (`:48-53`). `_consume_confirmation_token` accepts the token straight from `params` (`tool.py:718`). Chain: agent triggers a tier-3 gate → queries its own event log → reads the token → replays it → the gate is consumed and the destructive action executes unattended.

Two of the three links are proven by grep; the middle one (does the event reach the queryable EventLog with `data` intact?) needs a probe — see Builder check 2.

**It is unreachable in v1 by construction:** no action in `_BROWSER_LOOP_ACTIONS` can classify as tier 3 (DD-1), so no token is ever minted on this path. It becomes live the moment AD-1154 admits `click`/`type`.

**Do not fix it here.** The fix is to stop putting the secret in the payload — emit a non-secret `confirmation_id` and keep the token only in `_pending_confirmations`. No production code reads the token from the event (grepped: the sole consumer is `_consume_confirmation_token`, from `params`), but `tests/test_ad706_browser_tool.py:279` **asserts the token is in the payload**, so the fix has a known blast radius into an existing suite. That is a BF-shaped change, not a line inside this one. File **BF-682** and add a comment at the offer block naming it as an AD-1154 precondition.

---

## Build

1. **`src/probos/cognitive/agentic_dispatch.py`**
   - Module constants near `_GATED_TOOL_IDS` (`:79`): `_BROWSER_LOOP_ACTIONS`, `_BROWSER_TEXT_MAX_CHARS`, `_BROWSER_MAX_ELEMENTS`, `_BROWSER_DISPOSITION`, `_BROWSER_READ_ONLY_REFUSAL`, `_BROWSER_TEXT_ELISION`, `_BROWSER_ELEMENTS_ELISION`. Comment block explaining the fail-safe direction and citing AD-1147/DD-1 as the precedent.
   - `DispatchToolExecutor` (`:221`): add `self._browser_actions: frozenset[str] | None = None` in `__init__`, a public `restrict_browser_actions(actions)` method, and a guard at the top of `invoke` — when `_browser_actions is not None and tool_id == "browser"`, refuse any `params.get("action")` outside the set with a framed `ToolResult(error=...)` and no `super().invoke`. Bound and frame the output dict on the success path.
   - `browser_ids` block after `publish_ids` (`:953-962`), gated on `agentic_tools.browser_enabled` **and** `registry.get("browser") is not None`, permission-checked with `ToolPermission.READ` and the resolved `department`/`rank`. Silent honest-degrade when denied. One-shot egress warning per DD-7.
   - `*browser_ids` in the dedup list (`:964-969`).
   - `executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)` when `browser_ids` is non-empty **and** `"browser" not in granted_ids`.
2. **`src/probos/config.py`** — `browser_enabled: bool = False` on `AgenticToolsConfig` (`:6036`), placed after `publish_finding_*`. Extend the class docstring the way AD-1139/AD-1140 did; the description must state the `domain_allowlist is None` consequence and that v1 is read-only.
3. **Tests** — `tests/test_ad1153_browser_agentic_loop.py` (NEW), ≈26 tests. Reuse the `_FakePage` / `_FakeContext` / `_FakeBrowser` / `_make_session_factory` stubs from `tests/test_ad706_browser_tool.py:29-120` — **no live network, no real Chromium.** The `_CaptureLoop` monkeypatch shape for asserting the offered set is `tests/test_ad1007_capability_gate.py:281-330`.

No new files under `src/`. No edit to `src/probos/tools/browser/`, `src/probos/startup/finalize.py`, or `src/probos/tools/registry.py`.

---

## Acceptance

**Headline — a real navigate → enumerate → extract sequence against a local fixture page, with no network.**

> A `lieutenant` agent with `browser_enabled=True` is offered `browser`, calls `goto` against a `file://` fixture page (or the `_FakePage` stub), then `state`, then `extract_text`, and receives the page text carrying `_BROWSER_DISPOSITION`. The same agent's `click` is refused with `is_error=True` and the framed refusal, and `BrowserTool.invoke` is never entered for that call (assert on the fake page's recorded calls, not on the result alone).

**Offer (DD-2, DD-6):**
- Flag on + tool registered + `rank="lieutenant"` ⇒ `"browser" in tool_ids`.
- `rank="ensign"` ⇒ absent, silently, with no error and no capability-gap phrasing anywhere in the loop input.
- `rank` in `{commander, senior_officer}` ⇒ present.
- Flag on but `registry.get("browser") is None` ⇒ absent.
- Flag off ⇒ absent, and `tool_ids` is byte-identical to the AD-1140 set (assert against a literal recomputation).
- `"browser" not in _GATED_TOOL_IDS`, and a Captain grant of `read` to an **ensign** still surfaces the tool — the escape hatch is intact.
- Real `ToolRegistry` + real `ToolPermissionStore` throughout, per BF-287. No mock at the registry boundary; the rank gate is exactly what a mock would paper over.

**Action allowlist (DD-1):**
- Each of the six is admitted and reaches `BrowserTool.invoke`.
- Each of `click`, `type`, `scroll`, `screenshot`, `verify` is refused: `is_error=True`, framed text, `super().invoke` not called, no session created.
- An action absent from the tool's own enum (`"eval_js"`, `"fill_credential"`, `"teleport"`) is refused by the allowlist **before** reaching the tool — proving the fail-safe direction.
- **Tier proof:** for all six, `classify_action(session, action, params)` returns ≤ 2 against the real classifier, including a `goto` to `https://bank.example.com/checkout` and a `state` on a page whose `last_url` path is `/payment`. No path in the set mints a confirmation token — assert `tool._pending_confirmations == {}` after the sequence.
- Unarmed executor (`restrict_browser_actions` never called) ⇒ `click` passes through, byte-identical to today.
- Armed **only** when the offer came from `browser_ids`: an agent holding `browser` through `granted_ids` gets the unrestricted surface even with the flag on.

**Bounds (DD-3):**
- `extract_text` returning 20 000 chars ⇒ `output["text"]` is ≤ `_BROWSER_TEXT_MAX_CHARS` plus the marker, and the marker reports the elided count.
- `state` returning 250 elements ⇒ `output["elements"]` has 100 entries plus the element marker.
- Under-limit values are returned **unmodified** — assert object equality against the tool's raw output, so the bound cannot silently rewrite a small page.
- The bounded value is what the AD-1151 durable trace records (assert the trace, not just the transcript).

**Framing (DD-4):**
- Every module-level authored string is clean under the **real imported** `_CAPABILITY_GAP_RE` — import it, do not re-type it.
- Every rendered `ToolResult` across success / refusal / both elisions / the egress warning is clean under the same regex.
- A successful `extract_text` output carries the disposition; the refusal does not (it is a refusal, not an observation).

**Guardrails still bind (issue acceptance):**
- `domain_denylist` still blocks a `goto` on the loop path — same `error` string as the direct-invoke path.
- `domain_allowlist` still blocks an off-list `goto` on the loop path.
- Per-domain rate limiting and `session_max_duration_seconds` are untouched — assert `BrowserToolConfig` is not mutated anywhere in the new code.
- **Negative guard:** `destructive_url_patterns` is *not* consulted by `BrowserTool.invoke`. Pin it — `goto` to `https://x.example/checkout` executes and classifies tier 2. This test documents why DD-1 is read-only; if a future AD moves that check into the tool, the test goes red and forces the DD to be revisited.

**Parallelism (DD-5):**
- `"browser" not in PARALLEL_SAFE_TOOL_IDS`, and `partition_tool_uses` places a `browser` use on the sequential side.

**Egress warning (DD-7):**
- Flag on + `domain_allowlist is None` ⇒ WARNING emitted once, not once per offer (assert on a caplog across two `run` calls).
- Flag on + a non-empty allowlist ⇒ no warning.

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Validation plan — targeted only

**The full suite takes ~21 minutes and must NOT be run.**

- **Focused:** `tests/test_ad1153_browser_agentic_loop.py -q -n 0`
- **Adjacent, ONCE, after the focused gate is green:**
  `tests/test_ad706_browser_tool.py tests/test_ad706e_action_vocab_v2.py tests/test_ad745_pipeline_dispatch.py tests/test_ad856_agentic_dispatch.py tests/test_ad1007_capability_gate.py tests/test_ad1066_code_execution_tool.py tests/test_ad1072_agentic_tools.py tests/test_ad1129_eventlog_query_tool.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1140_publish_finding.py tests/test_ad1147_parallel_tools.py tests/test_ad1148_tool_result_bounds.py -q -n 0`

Why these exactly (each path confirmed to exist on disk):

| Suite | What it pins |
|---|---|
| `test_ad706_browser_tool.py` | `BrowserTool.invoke`, the tier-3 gate, domain policy, the `_FakePage` fixtures this AD reuses. **Must stay green untouched** — a red here means `src/probos/tools/browser/` was edited, which DD-1 forbids. |
| `test_ad706e_action_vocab_v2.py` | `classify_action`'s always-tier-3 verbs and the tier ladder DD-1's proof depends on. |
| `test_ad745_pipeline_dispatch.py` | The DM dispatch path and `destructive_url_patterns`. Must be byte-identical. |
| `test_ad856_agentic_dispatch.py` | `DispatchToolExecutor`, `denied_tools`, and the executor contract this AD extends. |
| `test_ad1007_capability_gate.py` | The `tool_ids` assembly and the `_CaptureLoop` pattern. |
| `test_ad1066` / `test_ad1072` / `test_ad1129` / `test_ad1139` / `test_ad1140` | The five sibling offer blocks whose `tool_ids` ordering must not shift. |
| `test_ad1147_parallel_tools.py` | The `PARALLEL_SAFE_TOOL_IDS` membership assertion at `:748-749`, which DD-5 must not disturb. |
| `test_ad1148_tool_result_bounds.py` | `truncate_tool_output` + the elision marker's gap-regex contract, which DD-3's markers mirror. |

If `test_ad706_browser_tool.py` or `test_ad745_pipeline_dispatch.py` goes red, **stop and surface it** — either means a shared browser surface moved, which DD-1 and DD-6 both forbid.

---

## Do NOT build here

❌ **`click` / `type` / `scroll` — they wait on AD-1154 (#1081).** ❌ Fixing the tier-3 confirmation flow, the `intervention_required` success shape, or the `_pending_confirmations` growth (all AD-1154). ❌ Fixing the DD-8 token leak — file BF-682, leave the code. ❌ Any edit under `src/probos/tools/browser/` — engine, action set, `classify_action`, tiers, credential vault, streaming, recording, session lifecycle. ❌ `action_dispatch_enabled` / `bridge_enabled` / `reply_pipeline.py` / `action_dispatcher.py`. ❌ Moving `destructive_url_patterns` or the consecutive-autonomous cap into `BrowserTool`. ❌ Editing `_wire_browser_tool` or the registered `default_permissions` matrix. ❌ Adding `browser` to `_GATED_TOOL_IDS` or to `PARALLEL_SAFE_TOOL_IDS`. ❌ A `browser_allowed_actions` config field, or any other way to widen the allowlist from config. ❌ Changing `tool_result_max_chars`' default, `truncate_tool_output`, or any AD-1148/AD-1151 bound. ❌ A screenshot/vision path, `AttachmentStore` refs, or anything that makes `verify` reachable. ❌ Passing `required=` from `AgenticLoop._run_one_tool_call`, or adding an action dimension to `check_permission`. ❌ `tests/ablation/sigma_flags.py` — this is not a Σ flag. ❌ Editing `config/system.yaml` (skip-worktree `S`, Captain-local). ❌ A second Playwright wrapper, a read-only façade tool id, or any new `tool_id`. ❌ A new AD; exactly one new BF (BF-682), file-only.

---

## Files (verify each at build)

- `src/probos/cognitive/agentic_dispatch.py` — constants, `DispatchToolExecutor`, the `browser_ids` block, the dedup list.
- `src/probos/config.py` — one `AgenticToolsConfig` field + docstring.
- `tests/test_ad1153_browser_agentic_loop.py` (NEW).

---

## Builder checks (unverifiable from the spec — confirm before relying on them)

1. **Does `add_post_hook`'s `_record_tool_result` see the bounded or the raw output?** It is registered at `agentic_dispatch.py:728` and fires inside `ToolExecutor.invoke` (`executor.py:128-137`) — i.e. **inside** `super().invoke()`, therefore **before** the DD-3 bound if the bound is applied after the `super()` call. AD-1151's durable trace must record the bounded value. Confirm the ordering empirically and place the bound so both the transcript and the trace see it; if the hook fires first, bound inside a pre-return step rather than after `super()`.
2. **Does `TOOL_INTERVENTION_REQUIRED` actually reach the queryable EventLog with `data` intact?** DD-8's chain needs this link. Probe it: emit the event through a real runtime, then run `event_log_query(event="tool_intervention_required")` and inspect `data`. If the token is present, BF-682 is confirmed and its severity is high; if the event is not persisted, downgrade BF-682 to a hardening note. Either way, **do not fix it in this AD** — record the finding in the build report.
3. **Is `params.get("action")` reliably a `str` at the `DispatchToolExecutor` boundary?** `use.tool_call.arguments` is LLM-produced JSON, so `action` can be absent, `None`, an int, or a dict. The guard must use `type(x) is str` strictness (the `oracle_query_tool.py:239` style) and refuse anything else through the same framed path — never `KeyError`, never a truthiness check.
4. **Does the fixture page need a real `file://` load?** `_FakePage.goto` records the URL without navigating (`test_ad706_browser_tool.py:46-49`), which is sufficient for every assertion here. Prefer it. If a genuine DOM is wanted for `extract_text`, gate it behind `PROBOS_PLAYWRIGHT_REAL=1` exactly as `test_ad706_browser_tool.py:365-369` does, so the default suite stays offline and fast.
5. **Where does the one-shot egress warning live so it fires once?** A module-level `bool` is process-global and will not reset between tests. Prefer an instance attribute on `WorkItemAgenticExecutor`, and assert the once-only behaviour across two `run` calls on the same executor instance rather than across two executors.
6. **Does `_BROWSER_LOOP_ACTIONS` still match the tool's enum?** Add a drift guard asserting `_BROWSER_LOOP_ACTIONS <= set(BrowserTool.input_schema["properties"]["action"]["enum"])`, so a future rename in `browser/tool.py` fails loudly here instead of silently refusing a valid verb. Note while you are there: the tool's `description` says "10-action vocabulary" while the enum holds 11 (`tool.py:113-131`) — cosmetic, pre-existing, **do not fix**.

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` (row for AD-1153; Bug Tracker row for BF-682) · `DECISIONS.md`.

The AD-1153 entry must record: that v1 is read-only **because the six offered actions provably cannot reach tier 3**, and that the tier-3 gate returns a success-shaped no-op for an unattended caller; that `goto` is unconditionally tier 2 so navigation to a payment URL is ungated; that `destructive_url_patterns` is a DM-path guardrail and not a `BrowserTool` one; that a per-action permission split is not expressible through `check_permission` because it is keyed by `tool_id` and the loop invokes at READ; that `ensign: none` is retained because rank is trust-derived and the Captain grant-up path already works; and BF-682 as an open observation that becomes load-bearing at AD-1154.

---

## Done-when

Headline navigate → enumerate → extract green against the offline fixture; all five mutating actions refused with `is_error=True` and no session created; the tier proof green (every offered action ≤ tier 2, zero tokens minted); the allowlist proven fail-safe against an unknown verb; Captain-grant path proven unrestricted; rank gate proven at all four ranks against a real registry; both bounds proven with under-limit pass-through; every authored string clean under the real `_CAPABILITY_GAP_RE`; domain allow/denylist proven still binding on the loop path; the `destructive_url_patterns` negative guard green; `PARALLEL_SAFE_TOOL_IDS` membership unchanged; egress warning proven once-only; default-OFF byte-identity proven for both `tool_ids` and `DispatchToolExecutor.invoke`; focused + adjacent gates green with `test_ad706_browser_tool.py` and `test_ad745_pipeline_dispatch.py` untouched; BF-682 filed; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-26, HEAD `d0b36061`)

```
src/probos/tools/browser/tool.py
   98:         return "browser"                              # tool_id
  113:         "Drive a Chromium browser. 10-action vocabulary: "   # says 10, enum has 11
  122:                     "enum": [                                # 11 actions
  225:         if action not in {                           # invoke guard — the REAL surface
  253:         if action == "goto":                         # _check_domain runs for goto ONLY
  272:         tier = classify_action(session, action, params)
  277:             tier == 3 and self._config.require_confirmation_for_tier_3
  282:             token = self._generate_confirmation_token(...)
  284:                 EventType.TOOL_INTERVENTION_REQUIRED,
  290:                     "confirmation_token": token,      # DD-8: raw secret in event payload
  305:             return ToolResult(                        # NOTE: error=None -> reads as SUCCESS
  307:                     "intervention_required": True,
  378:             elif action == "compute_use_click":        # dead behind the :225 guard
  386:             elif action == "fill_credential":          # dead behind the :225 guard
  696:     def _generate_confirmation_token(
  712:     def _consume_confirmation_token(
  718:         token = params.get("confirmation_token")       # read from PARAMS, replayable

src/probos/tools/browser/actions.py
   36: _TIER_3_PATH_TOKENS = ("checkout","payment","transfer","subscribe","signup","register")
  257:         "screenshot_b64": b64,                        # base64 PNG in the output dict
  325: async def _action_extract_text(...)                   # inner_text("body"), UNBOUNDED
  337:     return {"session_id": ..., "text": text or ""}
  553: _HANDLERS: dict[str, Any] = {
  778-795: _HANDLERS["compute_use_click"|"drag"|"key_combo"|"mouse_move"|"mouse_button"|
           "upload_file"|"download"|"eval_js"|"fill_credential"]   # ALL unreachable via invoke
  798: def classify_action(
  830:     silent = {"state","screenshot","wait","extract_text","scroll","back","forward",...}  # ->1
  833:     if action == "goto": return 2                     # UNCONDITIONAL — no URL inspection
  851:     if action not in {"click","type","drag","mouse_button"}: return 2
  855-876:                                                    # tier-3 host/path/text checks: click/type ONLY

src/probos/startup/finalize.py
  289: def _wire_browser_tool(*, runtime, config) -> bool:
  296:     cfg = getattr(config, "browser_tool", None)        # gated on browser_tool.enabled
  306:         from playwright.async_api import async_playwright
  322:     runtime.tool_registry.register(                    # NOTE: no allowed_departments
  328:         default_permissions={"ensign":"none","lieutenant":"read",
                                   "commander":"write","senior_officer":"full"},

src/probos/cognitive/agentic_dispatch.py
   79: _GATED_TOOL_IDS = frozenset({"event_log_query","oracle_query","publish_finding"})  # no browser
  127:         resolved_rank = Rank.from_trust(trust_network.get_score(registered_id)).value
  221: class DispatchToolExecutor(ToolExecutor):             # the enforcement seam
  235:     async def invoke(self, agent_id, tool_id, params, **kwargs) -> ToolResult:
  720:         executor = DispatchToolExecutor(registry=registry)
  728:         executor.add_post_hook(_record_tool_result)
  756:         granted_ids: list[str] = []                    # browser reaches the loop HERE today
  953:         publish_ids: list[str] = []                    # the block to mirror
  958:                 ToolPermission.WRITE,
  964:         tool_ids = list(dict.fromkeys([ ... *publish_ids, ]))
 1025:         _context.update({... "rank": rank ...})        # resolved rank reaches invoke

src/probos/tools/registry.py
  218:     def resolve_permission(
  244:         if reg.allowed_departments is not None:        # browser has none -> layer inert
  259:         if reg.default_permissions:                    # layer 3: the rank matrix
  359:             for grant in grants:                       # layer 4: Captain grant UP over rank
  285:     def check_permission(self, agent_id, tool_id, required, *, ...)   # NO action dimension
  310:         required: ToolPermission = ToolPermission.READ  # the loop's effective level

src/probos/cognitive/swe_harness/agentic_loop.py
   70: PARALLEL_SAFE_TOOL_IDS = frozenset({"web_search","read_page","http_fetch",
                                          "search_capabilities","event_log_query"})
 1200:             raw_result = await self._executor.invoke(   # no required= -> READ default
 1205:                 agent_rank=context.get("rank", "ensign"),
 1239:     def _bound_tool_output(self, output: str) -> str:  # no-op while max_chars == 0

src/probos/cognitive/swe_harness/tool_call.py
   51:         if tool_result.error is not None:              # is_error branches on error ONLY
   59:         out = raw if isinstance(raw, str) else str(raw) if raw is not None else ""

src/probos/cognitive/dm/reply_pipeline.py
  684:         destructive_patterns = list(getattr(browser_cfg,"destructive_url_patterns",[]))
  704:             if destructive_match: tier = 3             # DM path ONLY
  752:                     result = await browser_tool.invoke(params, context={"agent_id": ...})

src/probos/tools/event_log_query_tool.py
   48: _FILTER_FIELDS = (("category",128),("event",128),...)  # no event-type allowlist
  193: def _wire_json(value):                                 # recurses dicts, NO redaction
  215:         "data": _wire_json(row.data),

src/probos/config.py
   22: TRUST_LIEUTENANT = 0.5
 1546: class BrowserToolConfig(BaseModel):
 1572:     domain_allowlist: list[str] | None = None          # None = ALL hosts allowed
 1580:     require_confirmation_for_tier_3: bool = True
 1761:     action_dispatch_enabled: bool = Field(             # False; out of scope
 1791:     destructive_url_patterns: list[str] = Field(
 4406:     tool_result_max_chars: int = Field(                # ships at 0 -> UNBOUNDED
 6036: class AgenticToolsConfig(BaseModel):  # AD-1072
 6096:     oracle_query_enabled: bool = False   # AD-1139
 6097:     publish_finding_enabled: bool = False  # AD-1140

src/probos/crew_profile.py
   32:     ENSIGN = "ensign"           # Trust < 0.5, new or unproven
   38:     def from_trust(cls, trust_score: float) -> "Rank":

src/probos/cognitive/decomposer.py
   33: _CAPABILITY_GAP_RE = re.compile(                       # bare lack(?:s|ing)?

tests/
  test_ad706_browser_tool.py:29-120                          # _FakePage/_FakeSession stubs to reuse
  test_ad706_browser_tool.py:279                             # asserts token IS in the event payload
  test_ad706_browser_tool.py:365                             # PROBOS_PLAYWRIGHT_REAL=1 gate pattern
  test_ad1007_capability_gate.py:281-330                     # _CaptureLoop tool_ids capture pattern
  test_ad1147_parallel_tools.py:748                           # PARALLEL_SAFE_TOOL_IDS membership guard
```

**Authored-string gap-regex check** — all five DD-4 strings executed against the live imported `_CAPABILITY_GAP_RE` at HEAD `d0b36061`: `disposition clean · refusal clean · elision clean · elements clean · warn clean`.
