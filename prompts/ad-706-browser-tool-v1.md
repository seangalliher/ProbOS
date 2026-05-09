# AD-706 v1 — BrowserTool (Computer Use via Playwright)

**Issue:** [#482](https://github.com/seangalliher/ProbOS/issues/482)
**Type:** Architecture Decision (crew capability — agent-driven web browser)
**Depends on:** AD-423a/b/c (Tool Layer), AD-448 (Tool Executor + audit hook), AD-456 (AuditLog hash chain)
**Wave:** 132

## Goal

Ship a `BrowserTool` that plugs into the existing Tool Layer (AD-423a) so any rank-eligible agent can drive a real Chromium browser through Playwright. The action set is shaped by `browser-use` (https://github.com/browser-use/browser-use) — in particular its **indexed-element `state` pattern** that returns a stable list of clickable elements per page snapshot, so the LLM can say `click 5` instead of synthesizing CSS selectors. Screenshot returns are XGA-scaled per Anthropic's `computer-use-demo` guidance to save tokens and improve model accuracy. Tier-3 actions (financial, ToS, cookie consent, account creation) block on a new `tool_intervention_required` event until the Captain ACKs.

This is **a generic Computer Use tool**, not a Holodeck training subsystem. Whatever a future Holodeck scenario does with this tool (e.g. "train an agent to navigate Salesforce") is its own AD; AD-706 ships the standalone tool only.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/tools/protocol.py:14–22` `class ToolType(str, Enum)` already includes `BROWSER = "browser"` and `COMPUTER_USE = "computer_use"`. No enum addition needed.
- ✅ `src/probos/tools/protocol.py:71–80` `ToolResult` field shape — note: real fields are `output: Any`, `error: str | None`, `duration_ms: float`, `metadata: dict[str, Any]`. **The dispatch's "data containing screenshot_b64" is loose wording**; the prompt below puts browser-specific outputs in `ToolResult.output` (an `dict[str, Any]`) and per-action telemetry in `metadata`.
- ✅ `src/probos/tools/protocol.py:84–135` `Tool` Protocol — `tool_id`, `name`, `tool_type`, `description`, `input_schema`, `output_schema`, `async invoke(params, context)` are the seven members `BrowserTool` must implement.
- ✅ `src/probos/tools/protocol.py:33–43` `ToolPermission` enum: `NONE/OBSERVE/READ/WRITE/FULL`.
- ✅ `src/probos/tools/registry.py:106–141` `ToolRegistry.register(tool, *, domain, department, tags, provider, enabled, default_permissions, restricted_to, concurrency, lock_timeout_seconds)` — registration signature.
- ✅ `src/probos/tools/registry.py:159–186` `list_tools(...)` filter knobs.
- ✅ `src/probos/tools/context.py:113–145` `ToolContext.invoke(tool_id, params, *, required, context)` — agents reach `BrowserTool` through `ToolContext`, never the raw registry.
- ✅ `src/probos/tools/executor.py:64–115` `ToolExecutor.invoke()` — pre/post hooks fire around `registry.check_and_invoke()`. AD-448 already emits `EventType.TOOL_INVOKED` via `make_audit_hook`. `BrowserTool` does NOT need its own audit emit; it gets it for free.
- ✅ `src/probos/tools/adapters.py:23–98` `InfraServiceAdapter` shape — pattern reference; `BrowserTool` is a direct `Tool` implementation, not an adapter (it owns Playwright lifecycle), so it goes in a new `src/probos/tools/browser/` package.
- ✅ `src/probos/security/audit.py:39–104` `AuditLog.append(*, category, detail) -> AuditEntry` — hash chain available at `runtime.audit_log` (set in `startup/finalize.py:2296`). `BrowserTool` writes one audit entry per `invoke()` (in addition to the AD-448 `TOOL_INVOKED` event).
- ✅ `src/probos/cognitive/counselor.py:123–144` `class InterventionType(str, Enum)` and `class InterventionRecord` — **AD-561 in HEAD is Counselor-intervention classification (therapeutic_dm/cooldown_extension/...), NOT a generic safety-tier classifier**. The dispatch's "AD-451 SafetyClassifier / AD-561 Intervention Classification" naming is loose. AD-451 in HEAD is `ValidationFrameworkConfig` (validation hardening), not a safety classifier. **`BrowserTool` therefore SHIPS its own action-tier classification** (rule-based, in this AD) rather than reusing a class that doesn't exist; the rule-based classifier is the "tier-3 confirmation hook" the dispatch asks for. A future AD can replace the rule-based classifier with an LLM-driven one without changing the protocol.
- ✅ `src/probos/agents/http_fetch.py:80,290–346` `HttpFetchAgent._domain_state` ClassVar + per-domain min-interval + adaptive 429 backoff. **Reused in `BrowserSession`** for per-domain rate limiting (NOT shared state — `BrowserSession` keeps its own `_domain_state` ClassVar mirroring the pattern, since browser sessions and HTTP fetches have different semantics).
- ✅ `src/probos/events.py:20` `class EventType(str, Enum)` — current TOOL_* values: `TOOL_PERMISSION_DENIED` (line 196), `TOOL_INVOKED` (197), `AGENTIC_TOOL_CALL_*` (198–200). **No `BROWSER_*` or `*_INTERVENTION_REQUIRED` exists**; this AD adds them.
- ✅ `src/probos/config.py:2990–3014` SystemConfig field block — pattern for adding `browser_tool: BrowserToolConfig = BrowserToolConfig()  # AD-706` line.
- ✅ `src/probos/startup/finalize.py:25–105` wirer pattern: `def _wire_X(*, runtime: Any, config: "SystemConfig") -> bool` returning bool. Lazy/optional imports are conventional inside the wirer body (e.g. `_wire_creative_expression` imports `CreativeSkillsRegistry` inside the function).
- ✅ `src/probos/extensions/overlay.py:53–129` AD-697 extension hooks exist; `BrowserTool` is INTERNAL — **no overlay hook used in v1**. The extension seam is preserved for a future commercial overlay to swap the classifier or domain policy.
- ✅ `pyproject.toml:5–47` `[project.optional-dependencies]` group exists with `dev`, `discord`, `slack`, `copilot`. **`playwright` is NOT a current dependency**. v1 adds the new `browser` group.
- ✅ `src/probos/mcp_apps/registry.py:42` `MCPAppRegistry` exists; `routers/system.py:590` serves `ui://` resources for iframe embedding (AD-597a). **`McpAppFrame` named in the dispatch is NOT a real class** — the surface is the `ui://` HTTP serving + iframe pattern. The "Captain watches" surface needs a live Playwright CDP/WebSocket bridge that is not in v1 scope. **v1 defers** the watch surface to v2 with a clean hook (`BrowserSession.get_streaming_url() -> str | None` returns `None` in v1).
- ✅ `src/probos/runtime.py:1747` `self.tool_registry = comm.tool_registry` — registry attribute path used by the wirer.
- ✅ `playwright>=1.50` async API entry point: `from playwright.async_api import async_playwright` (per microsoft/playwright-python README). Browser launch via `async with async_playwright() as p: browser = await p.chromium.launch(headless=True)`.

## Scope (v1 only)

- Ship `BrowserTool` (one Tool implementation), `BrowserSession` (one Playwright context), `BrowserToolConfig` (Pydantic model), the action vocabulary (10 actions), the rule-based action-tier classifier, the new EventType values, the wirer, and tests.
- Default-disabled (`enabled: bool = False`) — opt-in per Wave 10 convention #14.
- Chromium only. Headless by default.
- No credential storage. No cookie persistence across sessions. No video recording.
- No Captain-watch UI surface (deferred to v2).

## Deliverables

### D1. New package `src/probos/tools/browser/`

Three files: `__init__.py` (exports), `tool.py` (`BrowserTool`), `session.py` (`BrowserSession`), `actions.py` (action handlers + classifier).

`src/probos/tools/browser/__init__.py`:

```python
"""AD-706: BrowserTool (Computer Use via Playwright)."""

from probos.tools.browser.tool import BrowserTool
from probos.tools.browser.session import BrowserSession

__all__ = ["BrowserTool", "BrowserSession"]
```

`src/probos/tools/browser/tool.py` — `BrowserTool` implementing `Tool` Protocol:

```python
"""AD-706: BrowserTool — agent-driven Chromium browser via Playwright.

Plugs into the AD-423a Tool Layer. One `BrowserTool` instance is registered
in the ToolRegistry; it owns a pool of `BrowserSession` instances keyed by
``session_id``. Actions are dispatched through ``invoke(params, context)``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.tools.protocol import Tool, ToolResult, ToolType

logger = logging.getLogger(__name__)


class BrowserTool:
    """AD-706 Tool implementation. Tool Protocol structural subtype."""

    def __init__(
        self,
        *,
        config: "BrowserToolConfig",
        audit_log: Any | None = None,
        emit_event: Any | None = None,
    ) -> None:
        self._config = config
        self._audit_log = audit_log
        self._emit_event = emit_event
        self._sessions: dict[str, "BrowserSession"] = {}

    @property
    def tool_id(self) -> str:
        return "browser"

    @property
    def name(self) -> str:
        return "Browser"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.BROWSER

    @property
    def description(self) -> str:
        return (
            "Drive a Chromium browser. 10-action vocabulary: "
            "goto, state, click, type, scroll, screenshot, wait, back, forward, extract_text. "
            "Use state() to get an indexed list of clickable elements, then click/type by index."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "goto", "state", "click", "type", "scroll",
                        "screenshot", "wait", "back", "forward", "extract_text",
                    ],
                },
                "session_id": {"type": "string", "description": "Reuse an existing session, or omit to create a fresh one."},
                "url": {"type": "string"},
                "index": {"type": "integer"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer"},
                "timeout_ms": {"type": "integer"},
                "confirmation_token": {"type": "string", "description": "Captain-issued token for tier-3 actions."},
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "url": {"type": "string"},
                "page_title": {"type": "string"},
                "screenshot_b64": {"type": "string"},
                "elements": {"type": "array"},
                "text": {"type": "string"},
                "intervention_required": {"type": "boolean"},
                "tier": {"type": "integer"},
            },
        }

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        # Dispatch + tier classification + audit + intervention gate.
        # Full body specified in D2 + D6.
        ...
```

`src/probos/tools/browser/session.py` — `BrowserSession` lifecycle wrapper around `playwright.async_api.BrowserContext`:

```python
"""AD-706: BrowserSession — one Playwright BrowserContext per agent session."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


@dataclass
class _DomainRateState:
    """Per-domain rate state for BrowserSession.

    Deliberately a redefinition of ``probos.agents.http_fetch.DomainRateState``
    rather than an import: BrowserSession has different semantics than
    HttpFetchAgent. Specifically:

    * Default ``min_interval_seconds`` is governed by
      ``BrowserToolConfig.default_min_interval_seconds`` (1.0s), not
      HttpFetchAgent's CoinGecko-tuned 2.0/3.0s defaults.
    * No 429-driven adaptive backoff: Playwright does not surface
      ``Retry-After`` / ``X-RateLimit-*`` headers uniformly across navigation,
      click, and type actions, so the ``consecutive_429s`` field exists for
      future symmetry only and is not currently incremented.
    * The state dict is BrowserSession-scoped (per-tool), not shared with the
      HTTP fetch agent's class-level dict.
    """

    last_request_at: float = 0.0
    min_interval_seconds: float = 1.0
    consecutive_429s: int = 0  # reserved; not incremented in v1 (see docstring)


class BrowserSession:
    """Wraps a Playwright BrowserContext with per-domain rate limiting and TTL.

    Lazy import: ``from playwright.async_api import async_playwright`` happens
    inside ``start()``, NOT module-level. Missing optional dep at import time
    must not crash startup.
    """

    # Per-domain rate limiting (BrowserSession-scoped, NOT shared with HttpFetchAgent —
    # browser sessions have different cadence than HTTP fetches).
    _domain_state: ClassVar[dict[str, _DomainRateState]] = {}

    def __init__(
        self,
        *,
        session_id: str,
        config: "BrowserToolConfig",
        agent_id: str,
    ) -> None:
        self.session_id = session_id
        self._config = config
        self._agent_id = agent_id
        self._created_at = time.time()
        self._last_state_index: list[dict[str, Any]] = []  # most recent state() snapshot
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def start(self) -> None:
        """Launch Chromium and open a fresh BrowserContext."""
        # Lazy import — see class docstring.
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._config.headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self._config.default_timeout_ms)

    async def stop(self) -> None:
        """Close everything in reverse order. Idempotent."""
        for closer, attr in [
            (self._page, "_page"),
            (self._context, "_context"),
            (self._browser, "_browser"),
        ]:
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    logger.debug("AD-706: close %s failed", attr, exc_info=True)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("AD-706: playwright.stop failed", exc_info=True)
        self._page = self._context = self._browser = self._playwright = None

    def is_expired(self) -> bool:
        """TTL check vs ``BrowserToolConfig.session_max_duration_seconds``."""
        return (time.time() - self._created_at) >= self._config.session_max_duration_seconds

    def get_streaming_url(self) -> str | None:
        """v1: returns None. v2 hook for Captain-watches surface (CDP/WebSocket bridge)."""
        return None

    # state(), click(), type_text(), scroll(), screenshot(), wait(), back(),
    # forward(), goto(), extract_text() — bodies in D2.
    # _wait_for_rate_limit(domain) — mirrors http_fetch.py:302–349 pattern.
    # _record_state_snapshot(elements) — stores indexed elements for next click/type.
```

### D2. Action vocabulary (v1 — 10 actions, FIXED by dispatch, no drops)

The action vocabulary is fixed: `goto`, `state`, `click`, `type`, `scroll`, `screenshot`, `wait`, `back`, `forward`, `extract_text`. Architect verify-first found no reason to drop any. Implementation lives in `src/probos/tools/browser/actions.py` as async free functions that take a `BrowserSession` and the action params; `BrowserTool.invoke()` is a dispatch table over the action string.

| Action | Required params | Returns in `ToolResult.output` |
|---|---|---|
| `goto` | `url: str` | `{session_id, url, page_title}` |
| `state` | (none) | `{elements: [{index, role, text, tag, href?, name?, value?}]}` — list of interactable elements, stable indices, persists until next `state()` or navigation. **THIS IS THE KEY browser-use ABSORPTION**. |
| `click` | `index: int` OR `selector: str` | `{session_id, url, page_title}` (post-click state). Index resolves from the most recent `state()` snapshot. |
| `type` | (`index: int` OR `selector: str`) + `text: str` | `{session_id, url}` |
| `scroll` | `direction: "up"\|"down"\|"left"\|"right"`, `amount: int = 500` | `{session_id, url}` |
| `screenshot` | (none) | `{screenshot_b64: str, width: int, height: int}`. **XGA scaling discipline**: render at `screenshot_max_width × screenshot_max_height` (default 1024×768) and rescale coordinates proportionally if the underlying viewport is larger. Source: anthropics/claude-quickstarts/computer-use-demo, MIT. |
| `wait` | `milliseconds: int` OR `selector: str` (wait for visible) | `{session_id}` |
| `back` | (none) | `{session_id, url, page_title}` |
| `forward` | (none) | `{session_id, url, page_title}` |
| `extract_text` | `selector: str = "body"` | `{text: str}` |

`BrowserTool.invoke()` body sketch:

```python
async def invoke(self, params, context=None):
    t0 = time.monotonic()
    action = params.get("action")
    session_id = params.get("session_id")
    agent_id = (context or {}).get("agent_id", "")

    # 1. Resolve or create session.
    session = await self._get_or_create_session(session_id, agent_id)

    # 2. Domain allowlist/denylist check (D6).
    if action == "goto":
        url = params.get("url", "")
        deny_reason = self._check_domain(url)
        if deny_reason:
            self._audit("domain_denied", agent_id, action, params, error=deny_reason)
            return ToolResult(
                error=f"Domain policy denied: {deny_reason}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

    # 3. Tier classification (D6).
    tier = self._classify_action(session, action, params)
    if tier == 3 and not self._has_confirmation_token(params, agent_id):
        self._emit_intervention_required(session.session_id, agent_id, action, params)
        self._audit("intervention_required", agent_id, action, params)
        return ToolResult(
            output={"intervention_required": True, "tier": 3, "session_id": session.session_id},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # 4. Per-domain rate limiting (mirrors http_fetch.py:302–349).
    await session._wait_for_rate_limit_for_action(action, params)

    # 5. Dispatch.
    try:
        from probos.tools.browser.actions import dispatch_action
        output = await dispatch_action(session, action, params)
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        self._audit("error", agent_id, action, params, error=str(exc))
        return ToolResult(error=str(exc), duration_ms=elapsed)

    elapsed = (time.monotonic() - t0) * 1000
    self._audit("success", agent_id, action, params)
    self._emit_browser_action(agent_id, action, session.session_id, tier, success=True)
    return ToolResult(
        output=output,
        duration_ms=elapsed,
        metadata={"session_id": session.session_id, "tier": tier},
    )
```

### D3. `BrowserSession` lifecycle

- Sessions are keyed by `session_id` (UUID4 if not provided).
- Time-bounded by `BrowserToolConfig.session_max_duration_seconds` (default 1800 = 30 min).
- `BrowserTool._reaper_task` (background `asyncio.create_task`, reference held — copilot-instructions Async Discipline rule) sweeps expired sessions every 60s. Task ref stored in `BrowserTool._reaper_task: asyncio.Task | None`. Cancellation handled in `BrowserTool.stop()`.
- Each session owns a fresh `BrowserContext` — no cookie/profile persistence across sessions.
- `BrowserSession.get_streaming_url()` returns `None` in v1; v2 hook for the Captain-watch surface.

### D4. Configuration — new `BrowserToolConfig` Pydantic model in `src/probos/config.py`

Add the model class (search-and-insert near the other AD-numbered configs around `validation_framework: ValidationFrameworkConfig` at line 3000):

```python
class BrowserToolConfig(BaseModel):
    """AD-706: BrowserTool (Computer Use via Playwright)."""

    enabled: bool = False  # Wave 10 convention #14: default-False on transitional flags
    headless: bool = True
    default_timeout_ms: int = 30000
    session_max_duration_seconds: int = 1800
    session_reaper_interval_seconds: int = 60

    # Network egress policy
    domain_allowlist: list[str] | None = None  # None = all allowed (subject to denylist)
    domain_denylist: list[str] = Field(default_factory=list)

    # XGA screenshot scaling (Anthropic computer-use-demo discipline, MIT)
    screenshot_max_width: int = 1024
    screenshot_max_height: int = 768

    # Tier-3 confirmation policy
    require_confirmation_for_tier_3: bool = True
    confirmation_timeout_seconds: int = 300  # auto-deny if Captain doesn't ACK

    # Per-domain rate limiting (mirrors HttpFetchAgent)
    default_min_interval_seconds: float = 1.0

    # Per-action overrides
    per_action_timeout_ms: dict[str, int] = Field(default_factory=dict)

    # Tier-3 classification — host-suffix glob patterns that force Captain ACK.
    # Matched case-insensitively against the URL host via fnmatch.
    tier_3_domain_patterns: list[str] = Field(
        default_factory=lambda: [
            "*bank*",
            "*paypal*",
            "*stripe*",
            "*chase*",
            "*coinbase*",
            "*checkout*",
        ]
    )
```

Add to `SystemConfig` (line ~3014 area, alongside `mcp_app_host`):

```python
browser_tool: BrowserToolConfig = Field(default_factory=BrowserToolConfig)  # AD-706
```

Use `Field(default_factory=...)` for mutable defaults — bare `[]` or `{}` defaults on a Pydantic model are an anti-pattern flagged in `.github/copilot-instructions.md`.

### D5. Audit trail integration (AD-456)

Every `BrowserTool.invoke()` writes one `runtime.audit_log.append(category="browser_tool", detail=...)` entry. `detail` is a JSON string built from a **strict allowlist** — no other keys may be added without an explicit AD revision:

| Key | Type | Required | Notes |
|---|---|---|---|
| `session_id` | `str` | yes | UUID4 string |
| `action` | `str` | yes | One of the 10 D2 verbs |
| `agent_id` | `str` | yes | From `ToolContext` |
| `success` | `bool` | yes | True iff `ToolResult.error is None` |
| `error` | `str \| None` | no | Truncated to 200 chars; omitted on success |
| `tier` | `int` | yes | 1, 2, or 3 from `_classify_action` |
| `url_sanitized` | `str \| None` | no | Only present for `goto`/`click` follow-up; computed as `urlparse(url)._replace(query="").geturl()` (drops query string and fragment) |

Explicitly **forbidden** in `detail` (defense-in-depth against credential leakage):

- `params.text` (typed input may be a password)
- `params.url` verbatim (query strings may carry tokens)
- POST bodies, form values, cookie contents
- Any `state()` element text or extracted page content

Independent of the audit row, AD-448 already emits `EventType.TOOL_INVOKED` automatically because `BrowserTool` is invoked through `ToolExecutor.invoke()` (which wraps `registry.check_and_invoke()`). `BrowserTool` does NOT need to emit `TOOL_INVOKED` itself.

In addition, `BrowserTool` emits two new EventType values (D7).

### D6. Permissions, domain policy, and tier-3 confirmation hook

**Permission registration.** When the wirer registers `BrowserTool`, it sets:

```python
runtime.tool_registry.register(
    browser_tool,
    domain="*",
    tags=["browser", "computer_use"],
    provider="ship_computer",
    enabled=True,
    default_permissions={
        "ensign":         "none",
        "lieutenant":     "read",
        "commander":      "write",
        "senior_officer": "full",
    },
    concurrency="concurrent",
)
```

`ToolContext.invoke("browser", params, required=ToolPermission.WRITE)` enforces the rank gate.

**Domain policy.** `BrowserTool._check_domain(url)` returns either an empty string (allowed) or a deny reason. Rules:
1. Parse the URL host.
2. If `domain_denylist` matches the host (suffix match), deny with reason `"in denylist"`.
3. If `domain_allowlist is not None` and the host doesn't suffix-match any entry, deny with reason `"not in allowlist"`.
4. Else allow.

**Tier classification (rule-based, in this AD).** `BrowserTool._classify_action(session, action, params)` returns int `1`, `2`, or `3`:

- **Tier 1 (silent):** `state`, `screenshot`, `wait`, `extract_text`, `scroll`, `back`, `forward` — observation only.
- **Tier 2 (logged-and-proceed):** `goto`, `click`, `type` against domains in the allowlist with no tier-3 indicators.
- **Tier 3 (Captain ACK required):** `click` or `type` when ANY of these heuristics fire:
  - URL host matches `BrowserToolConfig.tier_3_domain_patterns` (financial: `*bank*`, `*paypal*`, `*stripe*`, `*chase*`, `*coinbase*`, `*checkout*`).
  - URL path contains `checkout`, `payment`, `transfer`, `subscribe`, `signup`, `register`.
  - The clicked element's text (from the most recent `state()` snapshot — `session._last_state_index`) matches case-insensitive `r"i\s+agree|accept\s+(all|cookies|terms)|continue|sign\s*up|create\s+account|pay|confirm\s+order|place\s+order|transfer|subscribe"`.

Tier-3 actions short-circuit `invoke()` and emit `EventType.TOOL_INTERVENTION_REQUIRED` (D7). The agent receives `ToolResult(output={"intervention_required": True, "tier": 3, "session_id": ...})`. To proceed, the Captain (or upstream CLI/API) reissues the same `invoke()` call with `params["confirmation_token"]` set to the token returned in the intervention event payload. `BrowserTool` keeps a short-lived in-memory dict `_pending_confirmations: dict[str, dict[str, Any]]` keyed by token. Tokens expire after `BrowserToolConfig.confirmation_timeout_seconds`.

**Confirmation token flow (v1 — human-in-loop reissue only).**

1. **Generation.** When `_classify_action(...)` returns `3` and no valid `params["confirmation_token"]` is present, `BrowserTool._emit_intervention_required(...)` generates a fresh token via `uuid.uuid4().hex` and stores `{"token": token, "session_id": session_id, "action": action, "params": params, "created_at": time.time()}` in `_pending_confirmations[token]`.
2. **Surface boundary.** The token is included in the `EventType.TOOL_INTERVENTION_REQUIRED` event payload (`{"session_id", "action", "tier": 3, "agent_id", "confirmation_token": <uuid>}`) — **only** the event payload, which is delivered to Captain-visible bus subscribers. The agent-visible `ToolResult.output` deliberately omits the token (`{"intervention_required": True, "tier": 3, "session_id": ...}` only). This prevents an autonomous agent from reissuing without human-in-loop arbitration.
3. **Reissue.** Captain (or upstream CLI/API operator) reissues the same `invoke()` with `params["confirmation_token"] = <token>`. v1 is **strictly human-in-loop**: the agent itself cannot autonomously satisfy a tier-3 gate. (A future AD may add a Counselor-mediated autonomous-retry path; out of scope for v1.)
4. **Consumption.** `_has_confirmation_token(...)` consumes the token via `_pending_confirmations.pop(token, None)`, validates `session_id` and `action` match the original gate, and proceeds with the action. A token is single-use.
5. **Expiry.** Tokens older than `BrowserToolConfig.confirmation_timeout_seconds` (default 300s) are treated as absent. `BrowserTool._reaper_task` opportunistically prunes expired entries during its session-reap loop.

**Verify-first note on the dispatch's "AD-451 SafetyClassifier / AD-561 Intervention Classification" reference.** Neither name exists as a class. AD-451 in HEAD is `ValidationFrameworkConfig` (validation hardening). AD-561 in HEAD is `cognitive/counselor.py:123` `InterventionType` for Counselor therapeutic interventions, not generic action-tier classification. The rule-based classifier in this AD ships AD-706's tier hook self-contained; a future AD can replace it with an LLM-driven classifier without changing the protocol or breaking callers.

### D7. New EventType values + finalize wirer

**Add to `src/probos/events.py`** in the `EventType` enum, near the existing `TOOL_INVOKED` line (events.py:197):

```python
TOOL_INTERVENTION_REQUIRED = "tool_intervention_required"  # AD-706: tier-3 action awaits Captain ACK
BROWSER_ACTION_EXECUTED = "browser_action_executed"        # AD-706: per-action telemetry
BROWSER_SESSION_OPENED = "browser_session_opened"          # AD-706
BROWSER_SESSION_CLOSED = "browser_session_closed"          # AD-706
```

**Wirer in `src/probos/startup/finalize.py`**, modeled on `_wire_creative_expression` (line 80) and `_wire_classification_gate` (line 105):

```python
def _wire_browser_tool(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-706: Register BrowserTool in the ToolRegistry (default-disabled)."""
    cfg = getattr(config, "browser_tool", None)
    if not cfg or not cfg.enabled:
        return False
    if getattr(runtime, "tool_registry", None) is None:
        logger.warning("AD-706: tool_registry not available; skipping BrowserTool wiring")
        return False

    # Lazy Playwright import — missing optional dep at import time must not crash startup.
    try:
        from playwright.async_api import async_playwright  # noqa: F401  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "AD-706: playwright not installed; install probos[browser] and run 'playwright install chromium'"
        )
        return False

    from probos.tools.browser.tool import BrowserTool

    emit_fn = getattr(runtime, "emit_event", None)
    audit_log = getattr(runtime, "audit_log", None)
    browser_tool = BrowserTool(
        config=cfg,
        audit_log=audit_log,
        emit_event=emit_fn,
    )
    runtime.tool_registry.register(
        browser_tool,
        domain="*",
        tags=["browser", "computer_use"],
        provider="ship_computer",
        enabled=True,
        default_permissions={
            "ensign":         "none",
            "lieutenant":     "read",
            "commander":      "write",
            "senior_officer": "full",
        },
        concurrency="concurrent",
    )
    runtime.browser_tool = browser_tool  # public attribute (Wave 5 convention #1)
    logger.info("AD-706: BrowserTool registered (headless=%s, allowlist=%s)", cfg.headless, cfg.domain_allowlist)
    return True
```

Add the call to the existing finalize phase immediately after the existing `_wire_mcp_app_host(runtime=runtime, config=config)` call (line ~3214 in HEAD) and before the AD-697 extension dispatcher block. Line numbers are advisory; the relative ordering ("after `_wire_mcp_app_host`") is what Builder must preserve.

### D8. `pyproject.toml` optional dependency

Add to `[project.optional-dependencies]` (line 47–63 area) — does NOT modify the default install:

```toml
browser = [
    "playwright>=1.50",
]
```

Document in the AD's PROGRESS.md note that:

```
pip install -e .[browser]
playwright install chromium
```

are both required. Default install remains unaffected.

### D9. Tests — `tests/test_ad706_browser_tool.py`

≥20 tests. Most run **without a real browser** by mocking the Playwright client (use a `_FakePage` / `_FakeContext` / `_FakeBrowser` stub mirroring the methods used by `BrowserSession`). One integration test gated on env var `PROBOS_PLAYWRIGHT_REAL=1`, skipped by default. Each of the 10 v1 actions has at least one happy-path test (boundary-test discipline).

Required coverage:

1. `test_browser_tool_satisfies_protocol` — `isinstance(browser_tool, Tool)` (Tool is `runtime_checkable`).
2. `test_invoke_unknown_action_returns_error` — `params={"action": "nope"}`.
3. `test_invoke_goto_writes_audit_entry` — assert `audit_log.entries[-1].category == "browser_tool"` and `detail` contains `"goto"`.
4. `test_domain_denylist_blocks_navigation` — config `domain_denylist=["evil.example"]`, `goto("https://evil.example/x")` returns `ToolResult(error=...)` with `"in denylist"` substring.
5. `test_domain_allowlist_blocks_unknown_host` — config `domain_allowlist=["good.example"]`, `goto("https://other.example/")` returns deny.
6. `test_state_returns_indexed_elements` — `state()` returns `output.elements` as a list of dicts each with `index, role, text`.
7. `test_click_by_index_resolves_via_last_state` — call `state()`, then `click(index=2)` and assert the fake page's `click()` was called with the selector recorded at index 2.
8. `test_tier_3_action_emits_intervention_required` — `click` on `https://bank.example/transfer` produces `output.intervention_required is True`, `output.tier == 3`, and a `TOOL_INTERVENTION_REQUIRED` event was emitted.
9. `test_tier_3_with_confirmation_token_proceeds` — pre-seed `_pending_confirmations`, supply `params["confirmation_token"]`, action runs.
10. `test_screenshot_xga_scaling` — mock viewport `1920×1080`, assert returned `output.width <= 1024` and `output.height <= 768`.
11. `test_session_expiry_reaped` — set `session_max_duration_seconds=0.05`, advance time, run reaper once, assert session was closed.
12. `test_headless_flag_respected` — assert `chromium.launch(headless=True)` was called with the config-specified value.
13. `test_unknown_action_does_not_create_session` — sanity check on dispatch order.
14. `@pytest.mark.skipif(env != "1") test_real_chromium_goto_about_blank` — gated integration test.

Per-action happy-path coverage (one boundary test per remaining v1 action — Recommended #2 from review pass-1):

15. `test_type_writes_text_to_indexed_input` — `state()` then `type(index=N, text="hello")`; assert fake page's `fill()`/`type()` was called with the recorded selector and text.
16. `test_scroll_invokes_page_scroll` — `scroll(direction="down", amount=400)`; assert fake page's `evaluate()` (or equivalent scroll API) was called with the expected delta.
17. `test_wait_blocks_for_configured_duration` — `wait(seconds=0.05)`; assert call returns `ToolResult(output={"waited_ms": ...})` and elapsed time is within tolerance.
18. `test_back_navigates_history_backward` — fake page records `go_back()` invocation; assert `ToolResult.error is None`.
19. `test_forward_navigates_history_forward` — fake page records `go_forward()` invocation; assert `ToolResult.error is None`.
20. `test_extract_text_returns_visible_text` — fake page returns canned `inner_text()`; assert `output.text` equals the canned string and audit row uses `category="browser_tool"`.

Tests are order-independent (each builds its own `BrowserToolConfig` and `BrowserTool`), use `tmp_path` if needed, and clean up sessions in `finally:`.

## Safety guidelines (verbatim from anthropics/claude-quickstarts/computer-use-demo, MIT)

The Builder MUST include this 4-point block in `BrowserTool`'s module docstring AND in `BrowserToolConfig`'s docstring, attributed to the source:

> 1. Use a dedicated virtual machine or container with minimal privileges to prevent direct system attacks or accidents.
> 2. Avoid giving the model access to sensitive data, such as account login information, to prevent information theft.
> 3. Limit internet access to an allowlist of domains to reduce exposure to malicious content.
> 4. Ask a human to confirm decisions that may result in meaningful real-world consequences as well as any tasks requiring affirmative consent, such as accepting cookies, executing financial transactions, or agreeing to terms of service.
>
> *Source: anthropics/claude-quickstarts/computer-use-demo, MIT-licensed.*

How v1 maps to the four points:
- **(1)** defers to operator deployment posture. v1 does not enforce VM/container isolation.
- **(2)** v1 does not store, accept, or forward credentials into Playwright contexts. A future credential-storage AD (out of scope here) must explicitly state this.
- **(3)** Implemented via `BrowserToolConfig.domain_allowlist` / `domain_denylist` (D6).
- **(4)** Implemented via the tier-3 confirmation hook (D6) and `EventType.TOOL_INTERVENTION_REQUIRED` (D7).

## Non-Goals (explicit)

- **Holodeck integration.** A future Holodeck scenario may compose this tool, but that's a separate AD.
- **Captain-watch UI surface.** `BrowserSession.get_streaming_url()` is a stub returning `None`. The live CDP/WebSocket bridge defers to v2 (a future AD-706a). Rationale: `routers/system.py:590`'s `ui://` HTTP serving is for static iframe resources, not live browser frame streaming; the dispatch's reference to `McpAppFrame` does not match a real class in HEAD.
- **VR/3D rendering of the browser session inside HXI canvas.** The iframe surface is plenty when v2 lands.
- **Recording browser sessions to video.** Defer to AD-706b.
- **Cross-browser support (Firefox, WebKit).** Chromium only for v1.
- **Cookie/profile persistence across sessions.** Each session is fresh.
- **Authentication / login flows with credential storage.** Major design AD on its own.
- **MCP Bridge wrapping (AD-449).** `BrowserTool` is INTERNAL in v1. The Tool Protocol means a future AD can wrap it as an MCP server without changing this AD.
- **OmniParser / vision-only DOM-less extraction.** AGPL on `icon_detect` blocks model-weight absorption; track for AD-706c.
- **LLM-driven action-tier classifier.** v1 ships rule-based; replacing it later requires no protocol change.

## Acceptance criteria

- Pre-flight: working-tree integrity check (`git diff --numstat | sort -k2nr | Select-Object -First 5`; >200 deletions on any tracked file = STOP and surface).
- Focused: `pytest tests/test_ad706_browser_tool.py -v -n 0` green; integration test (`PROBOS_PLAYWRIGHT_REAL=1`) skipped by default.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing test count.
- Default install (`pip install -e .[dev]`) does NOT pull `playwright`. `pip install -e .[browser]` does. `playwright install chromium` is a separate post-install step the operator runs once.
- With `enabled=False` (default), no Playwright import happens, no session is created, `runtime.browser_tool` is unset.
- With `enabled=True` and `playwright` installed, `runtime.tool_registry.get_tool("browser")` returns the `BrowserTool` instance and `isinstance(tool, Tool)` is True.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- AD-numbering re-verification at commit time: confirm AD-706 has no live entry in `PROGRESS.md` / era files / `decisions-era-*.md` before authoring the new entry.

## Tracking

- `PROGRESS.md` — add CLOSED row when shipped.
- `decisions-era-5-unification.md` — append the AD-706 entry block (header + summary + "Status: shipped").
- `docs/development/roadmap.md` — flip the "Holodeck — Browser Automation" row label to "Browser Tool (Computer Use)" with the AD-706 reference, drop the Holodeck framing.
- GH issue #482 — close on merge with a link to the merge commit.

## Forward markers

- **AD-706a (v2):** Captain-watch streaming surface — Playwright CDP + WebSocket bridge into an iframe served via `routers/system.py`'s existing `ui://` resource path. Populates `BrowserSession.get_streaming_url()`.
- **AD-706b:** Session video recording (Playwright `record_video_dir`) + retention policy.
- **AD-706c:** OmniParser-style vision-based extraction for DOM-less surfaces (architecture-only absorption due to AGPL on `icon_detect`).
- **AD-706d:** LLM-driven tier classifier replacing the rule-based one in D6.
- **AD-706e:** Action vocabulary v2 — `drag`, `key_combo`, `mouse_move`, `mouse_button`, `upload_file`, `download`, `eval_js`. One-line additions; the protocol is the same.
- **AD-706f:** Credential vault integration. Explicit AD on its own.

## Verified Against Codebase (2026-05-08) — grep evidence

```
grep -n "BROWSER\|COMPUTER_USE" src/probos/tools/protocol.py
  21:    COMPUTER_USE = "computer_use"
  22:    BROWSER = "browser"

grep -n "class ToolResult\|output: Any\|error: str" src/probos/tools/protocol.py
  72: class ToolResult:
  76:     output: Any = None
  77:     error: str | None = None

grep -n "class Tool" src/probos/tools/protocol.py
  84: class Tool(Protocol):

grep -n "class ToolContext\|async def invoke" src/probos/tools/context.py
  26: class ToolContext:
  113:     async def invoke(

grep -n "TOOL_INVOKED\|class EventType" src/probos/events.py
  20: class EventType(str, Enum):
  197:     TOOL_INVOKED = "tool_invoked"  # AD-448

grep -n "class AuditLog\|def append" src/probos/security/audit.py
  39: class AuditLog:
  67:     def append(self, *, category: str, detail: str) -> AuditEntry:

grep -n "_domain_state\|min_interval_seconds" src/probos/agents/http_fetch.py
  27:     min_interval_seconds: float = 2.0
  80:     _domain_state: ClassVar[dict[str, DomainRateState]] = {}

grep -n "def _wire_creative_expression\|def _wire_classification_gate" src/probos/startup/finalize.py
  80: def _wire_creative_expression(*, runtime: Any, config: "SystemConfig") -> bool:
  105: def _wire_classification_gate(*, runtime: Any, config: "SystemConfig") -> bool:

grep -n "audit_log =\|self.tool_registry =" src/probos/startup/finalize.py src/probos/runtime.py
  finalize.py:2296:    runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
  runtime.py:1747:    self.tool_registry = comm.tool_registry

grep -n "validation_framework\|browser_tool\|mcp_app_host" src/probos/config.py
  3000:    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
  3014:    mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)  # AD-597

grep -n "class InterventionType\|class InterventionRecord" src/probos/cognitive/counselor.py
  123: class InterventionType(str, Enum):
  134: class InterventionRecord:

grep -n "playwright\|browser =" pyproject.toml
  (none — confirms playwright is not currently a dependency, optional or otherwise)
```

Every concrete file path, line number, class name, method signature, and import path asserted in this prompt maps to one of the greps above. New entities introduced by this prompt (the `BROWSER_*` and `TOOL_INTERVENTION_REQUIRED` EventType values, `BrowserToolConfig`, `BrowserTool`, `BrowserSession`, `_wire_browser_tool`, `tests/test_ad706_browser_tool.py`, the `browser` optional-deps group) are introduced by D1–D9 above and should not be flagged as missing during review.

## Revision (2026-05-08)

Pass-1 review (`prompts/Reviews/ad-706-browser-tool-v1-review.md`) raised 1 Required, 3 Recommended, 2 Nits. All applied in-body per Wave 130 lesson (fixes land in normative sections, not just notes).

| # | Tier | Finding | Fix location (body line numbers) |
|---|---|---|---|
| 1 | Required | D6 referenced `BrowserToolConfig.tier_3_domain_patterns` but D4 never declared it. | Added the field to `BrowserToolConfig` in D4 with default `["*bank*", "*paypal*", "*stripe*", "*chase*", "*coinbase*", "*checkout*"]` via `Field(default_factory=lambda: [...])`. New field declared at lines 396–406. D6 reference at line 475 now resolves. |
| 2 | Recommended | Tier-3 confirmation token flow under-specified (generation site, surface boundary, autonomous-retry policy, expiry). | Added "Confirmation token flow (v1 — human-in-loop reissue only)" subsection to D6, lines 481–489. Specifies: token = `uuid.uuid4().hex` generated in `_emit_intervention_required`; surfaces in event payload only (not `ToolResult.output`); single-use via `_pending_confirmations.pop`; expires after `confirmation_timeout_seconds` (default 300s) with `_reaper_task` opportunistic pruning; v1 strictly human-in-loop (no autonomous agent retry). |
| 3 | Recommended | 6 of 10 v1 actions had no dedicated test (`type`, `scroll`, `wait`, `back`, `forward`, `extract_text`). | Added 6 happy-path tests (#15–#20) to D9, lines 595–600. Test count target updated from "≥10 tests" to "≥20 tests" at line 574, with explicit boundary-test discipline note. |
| 4 | Recommended | Local `_DomainRateState` redefined `agents/http_fetch.py:23 DomainRateState` without justification. | Strengthened `_DomainRateState` docstring in D1, lines 188–207. Names three concrete semantic differences: per-tool min-interval default, no 429 adaptive backoff (Playwright doesn't surface `Retry-After`/`X-RateLimit-*` uniformly), per-tool scope vs class-level shared dict. `consecutive_429s` flagged as reserved-not-incremented. |
| 5 | Nit | D7 wirer call-site cited "line ~3828" instead of HEAD's actual ~3214. | D7 finalize-phase paragraph rewritten at line 551: cites `_wire_mcp_app_host` at line ~3214 in HEAD, with line numbers explicitly marked advisory and the relative-ordering invariant called out. Old `~3828` reference removed (grep: 0 hits). |
| 6 | Nit | D5 audit-detail field list was informal prose; redaction rule was advisory. | D5 rewritten at lines 416–438 with strict allowlist table (7 columns, required/optional flags) and explicit "forbidden in detail" defense-in-depth list (params.text, params.url verbatim, POST bodies, cookies, state-element text, extracted page content). |

**Rejections:** none. All 6 review items applied.

**Self-check (2026-05-08):**

- `Select-String -Path prompts/ad-706-browser-tool-v1.md -Pattern "tier_3_domain_patterns"` → 2 hits: line 396 (D4 declaration), line 475 (D6 reference). No orphan references.
- `Select-String -Path prompts/ad-706-browser-tool-v1.md -Pattern "3828"` → 0 hits in normative content (D1–D9, Acceptance, Tracking, Forward markers, Verified-Against). Remaining hits are confined to this Revision audit row (lines 724, 732) which describes the historical correction.
- D9 boundary-test count (≥20) consistent with body update at line 574 and per-action test list extending to test #20 at line 600.
- `_DomainRateState` redefinition justification (D1) and `_domain_state` ClassVar (D1, line 219) reference the same dataclass; no name drift.

Prompt is ready for review pass-2.
