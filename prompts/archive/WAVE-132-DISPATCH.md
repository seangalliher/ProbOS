# WAVE 132 DISPATCH — AD-706 Browser Tool (Computer Use via Playwright)

**Wave:** 132
**Mode:** main
**Depends on:** 131
**Builder required:** yes
**Issues to close:** #482
**Date:** 2026-05-08

## Captain's framing

Issue #482 was filed under the "Holodeck — Browser Automation" roadmap row. **The framing was wrong.** Holodeck simulations (AD-486/510/539b) are agent training environments. Browser automation is a **crew capability** — agents using a browser the way Claude Computer Use, Microsoft Copilot Cowork, and the new VS Code Integrated Browser do: the agent perceives a real web page, takes screenshots, fills forms, clicks links, scrapes content that lacks an MCP/SDK surface.

A future Holodeck scenario may *compose* this tool (e.g. "train an agent to navigate Salesforce") but the tool itself is generic Computer Use, not training-coupled.

The good news from verify-first: **the Tool Layer (AD-423a/b/c) is fully shipped** with `ToolType.BROWSER` and `ToolType.COMPUTER_USE` already in the enum. AD-706 plugs into the existing slot. There is no "Holodeck" subsystem to refactor.

## Architect must do this scoping research as part of drafting

1. **Existing surface to plug into:**
   - `src/probos/tools/protocol.py` — `Tool` Protocol, `ToolType` enum (already includes `BROWSER` and `COMPUTER_USE`), `ToolResult` dataclass.
   - `src/probos/tools/registry.py` — `ToolRegistry` service.
   - `src/probos/tools/permissions.py` — `ToolPermission` CRUD+O scoping (AD-423b).
   - `src/probos/tools/context.py` — `ToolContext` for role-based assignment (AD-423c).
   - `src/probos/tools/executor.py` — wrapped tool executor (AD-448 wrapping pattern; security intercept layer).
   - `src/probos/tools/adapters.py` — adapter pattern for tool-type implementations.
   - **Architect must read all six** before drafting; the prompt's deliverables must conform to the existing protocol exactly.

2. **External patterns to consider absorbing** (architect-curated 2026-05-08 OSS landscape sweep):

   **Primary references (high-confidence absorption — fetch these as part of drafting):**
   - **browser-use/browser-use** (93k stars, MIT, https://github.com/browser-use/browser-use): the highest-leverage OSS Computer Use project. Production-validated. Architect must read its CLI surface (`open`/`state`/`click N`/`type`/`screenshot`/`close`) and absorb the **indexed-element `state` pattern**. The agent calls `state` once, gets back a structured list of clickable elements with stable indices, then `click 5` instead of CSS-selector hell. **This is the killer pattern** — eliminates an entire class of brittleness in agent loops. Their `Agent`/`Browser`/`ChatBrowserUse` decomposition is also a useful template for our adapter shape.
   - **anthropics/claude-quickstarts/computer-use-demo** (parent 2.8k stars, MIT, https://github.com/anthropics/claude-quickstarts/tree/main/computer-use-demo): Anthropic's reference implementation. Architect must absorb (a) the **4 safety guidelines** verbatim into the AD's safety section: dedicated VM/container w/ minimal privileges, no sensitive credentials, domain allowlist, human confirmation for meaningful real-world consequences (financial txns, ToS, cookies); (b) the **XGA screenshot-scaling discipline** — scale screenshots to 1024x768 before sending to the model and map coordinates back proportionally. ~10x token savings + better model accuracy than letting the API do the resize.
   - **microsoft/playwright-python** (14.6k stars, Apache-2.0, https://github.com/microsoft/playwright-python): the chosen browser engine. Use the async API (`async_playwright()` context manager). Auto-wait + auto-retry on `page.click(selector)` eliminates most race-condition handling at the agent layer. Built-in screenshot, network interception, console capture.

   **Secondary references (track only — defer absorption to AD-706b/c):**
   - **microsoft/OmniParser** (24.7k stars, mixed CC-BY-4.0 + AGPL on icon_detect, https://github.com/microsoft/OmniParser): vision-only structured-element extraction from screenshots without DOM access. Useful for non-DOM surfaces (Flash, Canvas-heavy SPAs, embedded VNC). **AGPL license on icon_detect blocks direct model-weight absorption.** Architecture-level absorption only; defer to AD-706b once DOM-based v1 is shipping.
   - **bytedance/UI-TARS**: vision-language-action open model. Track for future LLM-tier registration; no code-absorption target.

   **Internal references**:
   - **Microsoft Copilot Cowork (March 2026)**: locked to M365 surface. Per the (private research) `copilot-cowork-analysis-2026-03-30.md`, ProbOS's positioning is "Computer Use on **everything else**". Architect should reference this positioning without crossing the OSS/commercial boundary in the prompt itself.
   - **VS Code Integrated Browser** (https://code.visualstudio.com/docs/debugtest/integrated-browser): the user-facing pattern of an iframe-embedded browser inside the IDE so agents can observe and act in the same surface the human sees. ProbOS already has `McpAppFrame` (iframe-based, AD-597a) — architect should evaluate whether the browser tool can render its session in `McpAppFrame` so the Captain can watch the agent operate.

3. **Internal cross-references the architect should evaluate:**
   - **AD-456 AuditLog hash chain**: every browser action should land in AuditLog (security tier). Verify the hook surface.
   - **AD-451 SafetyClassifier / AD-561 Intervention Classification**: tier-classify the browser action set. Things like "click button" are tier-1; "submit form on a banking site" is tier-3. The tool's `ToolPermission` scope should align.
   - **AD-449 MCP Bridge**: external MCP tools become ProbOS tools. The browser tool is INTERNAL — no MCP wrapping required for v1, but the design should not preclude wrapping later.
   - **HttpFetchAgent (AD-270 rate limiter)**: per-domain rate limiting already exists for HTTP. The browser tool should reuse the per-domain rate-limiting policy (a browser session that hits the same domain 100 times in a minute is hostile).
   - **Egress policy** (per the issue body): network egress must be policy-enforced. Verify whether there's an existing network-egress allowlist/denylist mechanism.

## Subagent Prompt — Architect (drafting + research pass)

Draft `prompts/ad-706-browser-tool-v1.md` matching the format of `prompts/archive/ad-697-extension-registry-v1.md` and the recently-shipped `prompts/archive/ad-490-eventlog-hash-chain-v1.md`. Required sections: Issue / Type / Depends-on / Wave (132); Goal; Verified Against Codebase (2026-05-08) with file:line citations; Scope; Deliverables (D1, D2, ...); Non-Goals; Acceptance; Tracking.

### Recommended scope for v1 (architect may adjust based on verify-first)

- **D1: `BrowserTool` plugs into `tools/protocol.py:Tool`.** `tool_type = ToolType.BROWSER`. Implements `invoke(params, context)` taking an `action` string from a defined action vocabulary + per-action params. Returns `ToolResult` with `data` containing `screenshot_b64`, `page_title`, `url`, plus action-specific outputs.

- **D2: Action vocabulary (v1 minimum, 10 actions absorbing browser-use's surface).**
  - `goto(url)` — navigate.
  - `state()` — **THE KEY ABSORPTION FROM browser-use**. Returns structured list of interactable elements (links, buttons, inputs, role+text+stable-index) so the LLM can reference elements by index instead of CSS selectors. Stable index is per-page-snapshot; persists until next navigation/`state()` call.
  - `click(index_or_selector)` — accepts an integer index (resolves via the most recent `state()` result) OR a CSS selector. Index is preferred per browser-use guidance.
  - `type(index_or_selector, text)` — same dual-mode lookup.
  - `scroll(direction, amount=...)` — up/down/left/right.
  - `screenshot()` — returns base64 PNG. **Apply XGA scaling per Anthropic discipline**: render at 1024x768 max, scale-back coordinates proportionally if larger. Configurable via `screenshot_max_width`/`screenshot_max_height` in `BrowserToolConfig`.
  - `wait(milliseconds | selector | condition)` — explicit synchronization point.
  - `back()` / `forward()` — history navigation.
  - `extract_text(selector?)` — returns text content of element (or whole `<body>` if omitted). Used for scraping flows.

  Defer to v2: `drag`, `key_combo`, `mouse_move`, `mouse_button`, `upload_file`, `download`, `eval_js`. Each is a one-line addition in v2 — the protocol is the same.

- **D3: `BrowserSession` lifecycle.** A session = a Playwright browser context. Sessions identified by `session_id`. Time-bounded (default 30 min). Captain-watchable via the existing iframe path if architect determines that's wirable in v1; else defer the watching surface to v2 with a clean hook.

- **D4: Configuration.** New `BrowserToolConfig` Pydantic model in `config.py`: `enabled: bool = False` (Wave 10 #14: default-False on transitional), `headless: bool = True`, `default_timeout_ms: int = 30000`, `session_max_duration_seconds: int = 1800`, `domain_allowlist: list[str] | None = None` (None = all allowed), `domain_denylist: list[str] = []`.

- **D5: Audit trail.** Every action lands in `AuditLog` (AD-456 hash-chained). Per-action audit row: session_id, action, params (URL/selector), tool_caller (agent_id), timestamp, success. The `BrowserTool.invoke()` is the audit-write site.

- **D6: Permissions, egress policy, and Captain confirmation hook.** `BrowserTool` declares required permissions (`{ToolPermission.READ, ToolPermission.WRITE}` for navigation+input). Pre-call check: requested URL host matches `domain_allowlist`/`domain_denylist`. Reject with auditable failure if denied.

  **Tier-3 action confirmation hook (absorbed from Anthropic safety guidance):** classify each `BrowserTool.invoke()` against AD-451 SafetyClassifier + AD-561 Intervention Classification. Tier-3 actions — financial transactions (URL/form heuristics: "checkout", "payment", "transfer", "$" in nearby text), terms-of-service acceptance (button text matches "I agree"/"Accept"/"Continue" within ToS-classified context), cookie-consent dialogs, account-creation forms — must produce a `tool_intervention_required` event and block until the Captain confirms (or auto-resolves per the configured Earned-Agency rank policy). Default policy: ACK required from Captain for tier-3; tier-2 logged-and-proceed; tier-1 silent.

- **D7: Finalize wirer.** `_wire_browser_tool(*, runtime, config)` in `startup/finalize.py`. Default-disabled. Verify Playwright import lazy (`from playwright.async_api import async_playwright` inside the wirer body, not module-level), so missing optional dep at import time doesn't crash startup.

- **D8: `pyproject.toml` optional dependency.** `playwright>=1.50.0` under `[project.optional-dependencies]` group `browser`. NOT a default install — `pip install probos[browser]`. Document that `playwright install chromium` is a separate post-install step.

- **D9: Tests.** ≥10 tests in `tests/test_ad706_browser_tool.py`. Most must run **without a real browser** (mock the Playwright client). At least 1 integration test gated on env var `PROBOS_PLAYWRIGHT_REAL=1`, skipped by default. Coverage: action-dispatch, permission denial, domain allowlist/denylist, session expiry, audit row written, headless-flag respected, malformed params, unknown action.

### Safety guidelines (absorbed verbatim from Anthropic's computer-use-demo, MIT)

The Architect MUST include this 4-point safety section in the prompt, attributed to the Anthropic source:

> 1. Use a dedicated virtual machine or container with minimal privileges to prevent direct system attacks or accidents.
> 2. Avoid giving the model access to sensitive data, such as account login information, to prevent information theft.
> 3. Limit internet access to an allowlist of domains to reduce exposure to malicious content.
> 4. Ask a human to confirm decisions that may result in meaningful real-world consequences as well as any tasks requiring affirmative consent, such as accepting cookies, executing financial transactions, or agreeing to terms of service.

The `domain_allowlist` config (#3) and the tier-3 confirmation hook (#4) are AD-706 v1 deliverables. (#1) defers to operator deployment. (#2) defers to a future credential-storage AD that explicitly states no credentials are forwarded into Playwright contexts.

### Non-Goals (explicit)

- Holodeck integration. Whatever a future Holodeck scenario does with this tool is its own AD; AD-706 ships a standalone tool.
- VR/3D rendering of the browser session inside HXI canvas. Out of scope; the iframe is plenty.
- Recording browser sessions to video. Defer to AD-706b.
- Cross-browser support (Firefox, WebKit). Chromium only for v1.
- Cookie/profile persistence across sessions. Each session is fresh.
- Authentication (login flows with credential storage). Major design AD on its own.

### Risk classification expected

**MEDIUM** — async Playwright lifecycle, file I/O for screenshots, security-sensitive (network egress), but the protocol surface (Tool) is well-defined and the work composes additively.

### Acceptance bullets to include

- Pre-flight: working-tree integrity check (`git diff --numstat | sort -k2nr | head -5`; >200 deletions = STOP).
- Focused: `pytest tests/test_ad706_browser_tool.py -v -n 0` green; integration test skipped by default.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing.
- Comply with engineering principles in `.github/copilot-instructions.md`.
- AD-numbering re-verification: confirm at commit time that AD-706 has no live entry in DECISIONS.md before authoring the new entry (per the standing rule).

## Output

- One prompt file at `prompts/ad-706-browser-tool-v1.md`.
- Touch nothing else.

## Final report

After the prompt is written, return ONE message containing:
1. One-line summary (filename + scope).
2. Verify-first findings — anything in this dispatch that contradicts HEAD reality.
3. Risk classification (LOW / MEDIUM / HIGH).
4. The exact action vocabulary chosen for v1 (architect's pick from the suggested set, with rationale for any inclusions/exclusions).
5. Whether `McpAppFrame` integration ships in v1 or defers to v2.
6. Standing-convention concerns (especially: did the existing tools/ surface impose any constraints not anticipated above?).
7. Audit trail: upstream URLs / commercial-research-files / internal era files actually fetched/read.

Begin.
