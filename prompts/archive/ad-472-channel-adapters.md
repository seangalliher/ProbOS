# AD-472: Channel Adapters — Multi-Platform Communication (v1)

**Status:** Ready for builder
**Dependencies:** Builds on the existing `ChannelAdapter` ABC at `src/probos/channels/base.py:34` (verified) and `DiscordAdapter` at `src/probos/channels/discord_adapter.py:52` (verified). AD-472 EXTENDS the channels package; does NOT introduce a new ABC.
**Estimated tests:** ~12
**Risk:** MEDIUM — external-platform surface; per-adapter rate limits + auth secrets. Coordinator-then-dispatch convention applies (v1 ships 3 adapters; 4 deferred).

---

## Problem

The roadmap entry (line 4193) lists 7 channel surfaces (Discord enhancements + Slack + Telegram + WhatsApp + Matrix + Teams + Webhook). ProbOS currently ships ONE adapter (`DiscordAdapter`); there is no:

1. **Slack adapter** — existing crews on Slack can't reach the ship.
2. **Generic Webhook adapter** — `POST /api/webhook/{channel}` is the catch-all that lets unsupported platforms forward messages without a per-platform integration.
3. **Discord enhancements** — Message Content Intent verification at startup, fetch_messages reconnection recovery, sender allowlist enforcement.

`grep -rn "class SlackAdapter\|class WebhookAdapter" src/probos/` returns no matches.

`grep -rn "class DiscordAdapter" src/probos/channels/discord_adapter.py:52` confirms the existing pattern. The Discord adapter accepts `(runtime, config)` and inherits the `ChannelAdapter.handle_message` flow (verified at `channels/base.py:67`).

The dispatch directive (convention #14) instructs v1 to ship 3 adapters out of 7. Defer Telegram, WhatsApp, Matrix, Teams to AD-472b/c/d.

## Solution Overview

Three additions to `src/probos/channels/`:

1. **Discord enhancements** (modify `channels/discord_adapter.py`) — three small additive changes:
   - Verify `discord.Intents.message_content` at startup; warn if not set.
   - `fetch_messages` reconnection recovery: when Discord disconnects mid-poll, exponential-backoff retry up to 3 attempts before propagating.
   - Sender allowlist enforcement: when `allowed_user_ids` is non-empty, reject messages from non-listed senders BEFORE running through `handle_message` (currently the check is downstream).
2. **`SlackAdapter`** (new file `channels/slack_adapter.py`) — `slack-sdk` based bolt-style adapter. OPT-IN via `[project.optional-dependencies] slack`. Subclass of `ChannelAdapter`; implements `start`/`stop`/`send_response`. Slash commands and threaded replies routed through the inherited `handle_message`.
3. **`WebhookAdapter`** (new file `channels/webhook_adapter.py`) — `POST /api/webhook/{channel}` route. Stdlib-only (uses existing FastAPI). Verifies a configured shared secret (`X-ProbOS-Webhook-Secret` header) on every inbound. Routes the JSON payload through `handle_message`. Returns the response synchronously.

This is **policy + diagnostics layered on the existing AD-453/485 ChannelAdapter surface.** AD-472 does NOT modify the `ChannelAdapter` ABC, does NOT change message routing semantics, does NOT introduce new event ordering rules.

**v1 scope (no-theater discipline; convention #7 + #14):**

- **Discord enhancements** — 3 real fixes to the existing adapter.
- **SlackAdapter** — real Bolt-pattern adapter behind an opt-in extra.
- **WebhookAdapter** — real FastAPI route, real shared-secret check, real `handle_message` plumbing.

**Four wholesale-deferred to sub-ADs:**

- **Telegram** (python-telegram-bot) — AD-472b.
- **WhatsApp** (Business Cloud API) — AD-472c.
- **Matrix** (matrix-nio) — AD-472d.
- **Microsoft Teams** (Bot Framework SDK) — AD-472d.

Each deferred adapter is opt-in via a uv extra; no new HARD pyproject deps in v1.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
CHANNEL_MESSAGE_RECEIVED = "channel_message_received"  # AD-472
CHANNEL_DELIVERY_FAILED = "channel_delivery_failed"  # AD-472
```

Verified absent: `grep -n "CHANNEL_MESSAGE_RECEIVED\|CHANNEL_DELIVERY_FAILED" src/probos/events.py` returns no matches.

---

## Section 1: Discord enhancements

**File:** `src/probos/channels/discord_adapter.py` (existing)

Three additive changes inside the existing class.

### 1a. Sender allowlist enforcement at message ingress

The current adapter's `on_message` handler runs `handle_message` regardless of `allowed_user_ids`. Move the check before `handle_message`.

**SEARCH (in the on_message handler around the existing message-text extraction):**

```python
        # Allowed user filter
        if discord_cfg.allowed_user_ids and message.author.id not in discord_cfg.allowed_user_ids:
            return
```

This block already exists in the adapter — confirm position. If absent, add immediately after the `message.author.bot` skip and before the `handle_message` call. Builder must grep `allowed_user_ids` in the file before editing; if found in the right position, leave it; if not, insert.

### 1b. (deferred) fetch_messages reconnection recovery

Live grep at revision time:

```
grep -n "fetch_messages\|reconnection\|on_disconnect" src/probos/channels/discord_adapter.py
(no matches)
```

The current Discord adapter has no `fetch_messages` call, no reconnection-recovery surface, and no `on_disconnect` handler. The roadmap entry's "fetch_messages reconnection recovery" predates the current adapter code; there is no v1 work to do here. **Wholesale-deferred to AD-472b** alongside the deferred Telegram/WhatsApp/Matrix/Teams adapters. Per convention #7 (no-theater), this section is documented as deferred rather than shipped as a no-op.

### 1c. Message Content Intent verification at startup

Add to `DiscordAdapter.start()` before the existing connect call:

```python
        # AD-472: Discord enhancement -- warn if Message Content Intent not enabled
        try:
            intents_obj = getattr(self._client, "intents", None)
            if intents_obj is not None:
                if not getattr(intents_obj, "message_content", False):
                    logger.warning(
                        "AD-472: Discord Message Content Intent is not enabled; "
                        "the bot will receive empty message text. "
                        "Enable it in the Discord Developer Portal."
                    )
        except Exception:
            logger.debug(
                "AD-472: could not introspect Discord intents", exc_info=True,
            )
```

> Verify-first: `self._client` is the existing `discord.Client` instance (verified at `channels/discord_adapter.py:62`-ish constructor; Builder must locate exact attribute name; the `getattr(...)` defensive pattern handles renames). The intents attribute is a `discord.Intents` object exposing `message_content: bool` per the Discord API.

---

## Section 2: `SlackAdapter`

**File:** `src/probos/channels/slack_adapter.py` (new)

```python
"""AD-472: SlackAdapter -- ChannelAdapter implementation for Slack.

OPT-IN: requires `pip install probos[slack]` (slack-sdk dependency).

v1 supports:
  - Inbound: events_api callback handler via Slack's Events API
  - Outbound: chat.postMessage via slack-sdk WebClient
  - Threaded replies (thread_ts)
  - User identity mapping (slack user_id -> ProbOS callsign via slack_user_map config)
"""

from __future__ import annotations

import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.config import SlackConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack adapter using slack-sdk's AsyncWebClient.

    Requires `slack-sdk` (opt-in: `uv sync --extra slack`).
    """

    def __init__(self, runtime: Any, config: SlackConfig) -> None:
        super().__init__(runtime, config)
        self._slack_config = config
        self._web_client: Any = None  # slack_sdk.web.async_client.AsyncWebClient

    async def start(self) -> None:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            logger.error(
                "AD-472: slack-sdk not installed; run `uv sync --extra slack`. "
                "SlackAdapter disabled."
            )
            return

        token = self._slack_config.bot_token
        if not token:
            logger.warning(
                "AD-472: SlackAdapter has no bot_token; refusing to start"
            )
            return

        self._web_client = AsyncWebClient(token=token)
        # Verify auth (real-work check, not theater)
        try:
            response = await self._web_client.auth_test()
            if not response.get("ok"):
                logger.error("AD-472: Slack auth_test failed: %s", response)
                self._web_client = None
                return
        except Exception:
            logger.error("AD-472: Slack auth_test error", exc_info=True)
            self._web_client = None
            return

        self._started = True
        logger.info("AD-472: SlackAdapter started (auth_test ok)")

    async def stop(self) -> None:
        self._web_client = None
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        if self._web_client is None:
            self._emit_delivery_failed(channel_id, reason="not_started")
            return
        thread_ts = kwargs.get("thread_ts")
        try:
            await self._web_client.chat_postMessage(
                channel=channel_id,
                text=response,
                thread_ts=thread_ts if self._slack_config.default_thread_ts else None,
            )
        except Exception as exc:
            logger.warning(
                "AD-472: Slack chat_postMessage failed (channel=%s)", channel_id,
                exc_info=True,
            )
            self._emit_delivery_failed(channel_id, reason="api_error", detail=str(exc))

    async def receive(self, *, text: str, channel_id: str, user_id: str,
                      user_display_name: str = "", thread_ts: str | None = None) -> str:
        """Inbound entry point (called by Slack events_api callback handler).

        Verifies allowed_channel_ids / allowed_user_ids, emits
        CHANNEL_MESSAGE_RECEIVED, then routes through handle_message.
        """
        cfg = self._slack_config
        if cfg.allowed_channel_ids and channel_id not in cfg.allowed_channel_ids:
            return ""
        if cfg.allowed_user_ids and user_id not in cfg.allowed_user_ids:
            return ""

        self._emit_received(channel_id=channel_id, user_id=user_id, platform="slack")
        message = ChannelMessage(
            text=text,
            channel_id=channel_id,
            user_id=user_id,
            user_display_name=user_display_name,
            reply_to_message_id=thread_ts,
        )
        return await self.handle_message(message)

    def _emit_received(self, *, channel_id: str, user_id: str, platform: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {"platform": platform, "channel_id": channel_id, "user_id": user_id},
            )
        except Exception:
            logger.debug("AD-472: CHANNEL_MESSAGE_RECEIVED emit failed", exc_info=True)

    def _emit_delivery_failed(
        self, channel_id: str, *, reason: str, detail: str = "",
    ) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_DELIVERY_FAILED,
                {
                    "platform": "slack",
                    "channel_id": channel_id,
                    "reason": reason,
                    "detail": detail[:200] if detail else "",
                },
            )
        except Exception:
            logger.debug("AD-472: CHANNEL_DELIVERY_FAILED emit failed", exc_info=True)
```

---

## Section 3: `WebhookAdapter`

**File:** `src/probos/channels/webhook_adapter.py` (new)

```python
"""AD-472: WebhookAdapter -- catch-all POST /api/webhook/{channel}.

Lets unsupported platforms forward messages by POSTing JSON. Stdlib-only
(uses existing FastAPI). Verifies a shared secret header on every inbound.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.config import WebhookConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class WebhookAdapter(ChannelAdapter):
    """Generic webhook adapter -- inbound POST /api/webhook/{channel}.

    v1 outbound is a no-op: webhook is inbound-only; downstream consumers
    (Slack, Discord) own their own outbound paths. send_response is
    implemented as a logged no-op so the ABC contract is honored without
    pretending to deliver.
    """

    def __init__(self, runtime: Any, config: WebhookConfig) -> None:
        super().__init__(runtime, config)
        self._webhook_config = config

    async def start(self) -> None:
        # No persistent connection -- the API surface is the FastAPI route.
        if not self._webhook_config.shared_secret:
            logger.warning(
                "AD-472: WebhookAdapter starting WITHOUT shared_secret; "
                "any caller can post messages. Set PROBOS_WEBHOOK_SECRET."
            )
        self._started = True
        logger.info("AD-472: WebhookAdapter started")

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        # v1: webhook is inbound-only. The originating platform is responsible
        # for delivering its own response (synchronous return value from
        # the FastAPI route). No-op here, with an audit log line for honesty.
        logger.info(
            "AD-472: WebhookAdapter.send_response is a no-op in v1 "
            "(channel=%s, len=%d)", channel_id, len(response or ""),
        )

    async def receive(
        self, *, text: str, channel: str, user_id: str = "webhook",
        secret: str = "",
    ) -> str:
        """Inbound entry point (called by FastAPI route).

        Returns the runtime's response synchronously so the FastAPI route
        can echo it back to the caller.
        """
        cfg = self._webhook_config
        # Shared-secret check (real today; convention #7 no-theater)
        if cfg.shared_secret and secret != cfg.shared_secret:
            self._emit_delivery_failed(channel, reason="bad_secret")
            return ""
        if cfg.allowed_channels and channel not in cfg.allowed_channels:
            self._emit_delivery_failed(channel, reason="channel_not_allowed")
            return ""

        self._emit_received(channel=channel, user_id=user_id)
        message = ChannelMessage(
            text=text,
            channel_id=channel,
            user_id=user_id,
        )
        return await self.handle_message(message)

    def _emit_received(self, *, channel: str, user_id: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {"platform": "webhook", "channel_id": channel, "user_id": user_id},
            )
        except Exception:
            logger.debug("AD-472: emit failed", exc_info=True)

    def _emit_delivery_failed(self, channel: str, *, reason: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_DELIVERY_FAILED,
                {"platform": "webhook", "channel_id": channel, "reason": reason},
            )
        except Exception:
            logger.debug("AD-472: emit failed", exc_info=True)
```

> Note: the FastAPI route registration is NOT added to `api.py` in v1 — that requires a coordinator-then-dispatch handoff with the existing `routers/` structure. v1 ships the adapter class with `receive(...)` as the public entry point. AD-472b's Telegram/WhatsApp/Matrix work will pick up the FastAPI registration as a unified router. This honors convention #3.

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH (post-AD-449 MCP_BRIDGE):
```python
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
```

REPLACE:
```python
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
    CHANNEL_MESSAGE_RECEIVED = "channel_message_received"  # AD-472
    CHANNEL_DELIVERY_FAILED = "channel_delivery_failed"  # AD-472
```

> Anchor depends on AD-449 landing first within Wave 8. Fallback to `EPS_REALLOCATION = "eps_reallocation"  # AD-469` (post-AD-469) -> `MODEL_FALLBACK = "model_fallback"  # AD-463` (line 211).

---

## Section 5: Extend `ChannelsConfig`

**File:** `src/probos/config.py`

AD-472 defines `SlackConfig` and `WebhookConfig` ONCE in `config.py` (canonical Pydantic location, mirroring the existing `DiscordConfig` precedent at `config.py:1306`). Adapter modules in `src/probos/channels/` import these types -- they are NOT redefined in adapter source.

SEARCH (`config.py:1306-1322`, the existing DiscordConfig + ChannelsConfig block):
```python
class DiscordConfig(BaseModel):
    """Discord bot adapter configuration."""

    enabled: bool = False
    token: str = ""                          # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
    mention_required: bool = False           # Only respond when @mentioned
    scout_channel_id: int = 0                # Discord channel ID for scout reports (0 = disabled)


class ChannelsConfig(BaseModel):
    """Channel adapter configurations."""

    discord: DiscordConfig = DiscordConfig()
```

REPLACE (define SlackConfig + WebhookConfig BEFORE ChannelsConfig so direct defaults bind without forward refs):
```python
class DiscordConfig(BaseModel):
    """Discord bot adapter configuration."""

    enabled: bool = False
    token: str = ""                          # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
    mention_required: bool = False           # Only respond when @mentioned
    scout_channel_id: int = 0                # Discord channel ID for scout reports (0 = disabled)


class SlackConfig(BaseModel):
    """Slack adapter configuration (AD-472)."""

    enabled: bool = False
    bot_token: str = ""           # xoxb-... (prefer env var PROBOS_SLACK_BOT_TOKEN)
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    default_thread_ts: bool = True


class WebhookConfig(BaseModel):
    """Webhook adapter configuration (AD-472)."""

    enabled: bool = False
    shared_secret: str = ""       # set via env var PROBOS_WEBHOOK_SECRET
    allowed_channels: list[str] = []


class ChannelsConfig(BaseModel):
    """Channel adapter configurations."""

    discord: DiscordConfig = DiscordConfig()
    slack: SlackConfig = SlackConfig()
    webhook: WebhookConfig = WebhookConfig()
```

> Builder note: defining `SlackConfig` and `WebhookConfig` BEFORE `ChannelsConfig` lets us use direct `SlackConfig()` / `WebhookConfig()` defaults instead of forward-ref `None` defaults. This matches the existing `DiscordConfig` precedent and avoids `model_rebuild()`.

---

## Section 6: Wire into startup (CLI)

**File:** `src/probos/__main__.py`

The existing pattern at `__main__.py:438-452` instantiates `DiscordAdapter` when `--discord` or `config.channels.discord.enabled`. Mirror it for Slack and Webhook.

SEARCH (around `__main__.py:436-453`):
```python
    # Start channel adapters
    adapters: list = []
    if discord or config.channels.discord.enabled:
        from probos.channels.discord_adapter import DiscordAdapter
        discord_cfg = config.channels.discord
        token = os.environ.get("PROBOS_DISCORD_TOKEN", "") or discord_cfg.token
        if token:
            discord_cfg = discord_cfg.model_copy(update={"token": token})
            adapter = DiscordAdapter(runtime, discord_cfg)
            await adapter.start()
            if adapter._started:
                adapters.append(adapter)
                console.print("  [green]\u2713[/green] Discord bot adapter started")
            else:
                console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")
        else:
            console.print("  [yellow]![/yellow] Discord enabled but no token set (PROBOS_DISCORD_TOKEN)")
```

REPLACE:
```python
    # Start channel adapters
    adapters: list = []
    if discord or config.channels.discord.enabled:
        from probos.channels.discord_adapter import DiscordAdapter
        discord_cfg = config.channels.discord
        token = os.environ.get("PROBOS_DISCORD_TOKEN", "") or discord_cfg.token
        if token:
            discord_cfg = discord_cfg.model_copy(update={"token": token})
            adapter = DiscordAdapter(runtime, discord_cfg)
            await adapter.start()
            if adapter._started:
                adapters.append(adapter)
                console.print("  [green]\u2713[/green] Discord bot adapter started")
            else:
                console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")
        else:
            console.print("  [yellow]![/yellow] Discord enabled but no token set (PROBOS_DISCORD_TOKEN)")

    # AD-472: Slack adapter (opt-in via uv extras)
    if config.channels.slack.enabled:
        from probos.channels.slack_adapter import SlackAdapter
        slack_cfg = config.channels.slack
        token = os.environ.get("PROBOS_SLACK_BOT_TOKEN", "") or slack_cfg.bot_token
        if token:
            slack_cfg = slack_cfg.model_copy(update={"bot_token": token})
            adapter = SlackAdapter(runtime, slack_cfg)
            await adapter.start()
            if getattr(adapter, "_started", False):
                adapters.append(adapter)
                console.print("  [green]\u2713[/green] Slack adapter started")
            else:
                console.print("  [red]\u2717[/red] Slack adapter failed — run: uv sync --extra slack")

    # AD-472: Webhook adapter (no opt-in extra; uses existing FastAPI)
    if config.channels.webhook.enabled:
        from probos.channels.webhook_adapter import WebhookAdapter
        webhook_cfg = config.channels.webhook
        secret = os.environ.get("PROBOS_WEBHOOK_SECRET", "") or webhook_cfg.shared_secret
        if secret:
            webhook_cfg = webhook_cfg.model_copy(update={"shared_secret": secret})
        adapter = WebhookAdapter(runtime, webhook_cfg)
        await adapter.start()
        if getattr(adapter, "_started", False):
            adapters.append(adapter)
            console.print("  [green]\u2713[/green] Webhook adapter started")
```

> Builder note: the SEARCH and REPLACE blocks above use **em-dash `—`** (U+2014) to match the live source character at `__main__.py:450`. ASCII `--` would cause a SEARCH miss. Convention #9 (ASCII-only source comments) does NOT apply here — we are matching pre-existing source, not adding a new comment.

---

## Section 7: pyproject extras

**File:** `pyproject.toml`

SEARCH:
```toml
discord = [
    "discord.py>=2.0",
    "aiohttp>=3.9,<3.13",   # discord.py 2.x incompatible with aiohttp 3.13+ (ClientWebSocketResponse removed)
]
copilot = [
    "github-copilot-sdk>=0.1.30",
]
```

REPLACE:
```toml
discord = [
    "discord.py>=2.0",
    "aiohttp>=3.9,<3.13",   # discord.py 2.x incompatible with aiohttp 3.13+ (ClientWebSocketResponse removed)
]
slack = [
    "slack-sdk>=3.21,<4",
]
copilot = [
    "github-copilot-sdk>=0.1.30",
]
```

> No new HARD pyproject deps. `slack-sdk` is opt-in via `uv sync --extra slack`. `WebhookAdapter` reuses the existing FastAPI dependency.

---

## Tests

**File:** `tests/test_ad472_channel_adapters.py`

12 tests using fakes for `runtime.emit_event`. Slack tests skip when `slack-sdk` is not installed.

1. `test_event_type_channel_message_received_exists`
2. `test_event_type_channel_delivery_failed_exists`
3. `test_slack_config_defaults` -- `enabled=False`, `default_thread_ts=True`.
4. `test_webhook_config_defaults` -- `enabled=False`, `allowed_channels=[]`.
5. `test_channels_config_includes_slack_and_webhook` -- `ChannelsConfig()` has `slack` and `webhook` attributes.
6. `test_slack_adapter_start_without_sdk_does_not_crash` -- monkeypatch import; `start()` returns without `_started=True`. `@pytest.mark.asyncio`.
7. `test_slack_adapter_send_response_emits_failure_when_not_started` -- `send_response("C123", "hi")` -> emit fires `CHANNEL_DELIVERY_FAILED` with `reason="not_started"`. `@pytest.mark.asyncio`.
8. `test_webhook_adapter_receive_with_correct_secret_routes_message` -- adapter.receive(text="ping", channel="ops", secret="s") with cfg.shared_secret="s" -> handle_message called via mock; `CHANNEL_MESSAGE_RECEIVED` emitted. `@pytest.mark.asyncio`.
9. `test_webhook_adapter_receive_rejects_bad_secret` -- mismatched secret -> empty return; `CHANNEL_DELIVERY_FAILED` with `reason="bad_secret"`. `@pytest.mark.asyncio`.
10. `test_webhook_adapter_receive_rejects_disallowed_channel` -- `allowed_channels=["ops"]` and channel="bridge" -> empty + emit `reason="channel_not_allowed"`. `@pytest.mark.asyncio`.
11. `test_webhook_adapter_send_response_is_noop_in_v1` -- v1 contract: `send_response` returns without raising; no emit. `@pytest.mark.asyncio`.
12. `test_discord_intent_warning_logged_when_message_content_disabled` -- monkeypatch a fake `discord.Client` with `intents.message_content=False` -> `start()` logs the AD-472 warning. `@pytest.mark.asyncio` (skipif discord.py not installed).

Each test uses `MagicMock`/`SimpleNamespace` stubs and `runtime.emit_event` fakes.

---

## What This Does NOT Change

- `ChannelAdapter` ABC at `channels/base.py:34` is unchanged. AD-472 EXTENDS the channels package; no ABC modification.
- `DiscordAdapter` core flow (`channels/discord_adapter.py:52-...`) unchanged except for the three additive enhancements in Section 1.
- `runtime.task_scheduler._channel_adapters` (existing wiring at `__main__.py:456`) is unchanged. Slack/Webhook adapters land in the same list.
- `api.py` and `routers/` are unchanged. v1 ships `WebhookAdapter.receive(...)` as a callable; the FastAPI route registration is deferred to AD-472b.
- **Telegram, WhatsApp, Matrix, Microsoft Teams adapters are NOT shipped in v1.** Wholesale deferred to AD-472b/c/d.
- AD-472 introduces NO destructive intents. The `requires_consensus=True` rule does not apply.
- No new HARD pyproject dependencies. `slack-sdk` is opt-in via `[project.optional-dependencies] slack`.

---

## Tracking

- `PROGRESS.md`: add `AD-472 CLOSED. Channel Adapters v1 (Discord enhancements + Slack + Webhook) ...`
- `docs/development/roadmap.md`: flip AD-472 status from `*(planned)*` to `*(partial - v1 ships Discord enhancements + Slack + Webhook; Telegram/WhatsApp/Matrix/Teams deferred to AD-472b/c/d)*` near line 4193.
- `DECISIONS.md`: optional entry recording the v1-3-of-7 scope decision and the FastAPI-route deferral.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/channels/discord_adapter.py`: ~15 lines added (Section 1c intent check; 1a + 1b are no-ops if already present / not applicable).
- `src/probos/channels/slack_adapter.py`: ~150 lines (new).
- `src/probos/channels/webhook_adapter.py`: ~115 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~30 lines added (SlackConfig + WebhookConfig + ChannelsConfig fields).
- `src/probos/__main__.py`: ~30 lines added (Slack + Webhook startup blocks).
- `pyproject.toml`: ~3 lines added (slack extra).
- `tests/test_ad472_channel_adapters.py`: ~290 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad472_channel_adapters.py -v -n 0` (Slack/Discord-dependent tests skip cleanly when their extras are absent).
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `WebhookAdapter` and `SlackAdapter` subclass `ChannelAdapter` (no ABC mutation).
- `pyproject.toml` adds the `slack` extra; no new HARD deps.
- `WebhookAdapter.send_response` is a documented no-op (no theater).
- `runtime` does not gain a top-level adapter attribute; the existing `task_scheduler._channel_adapters` list is the integration point.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
ls src/probos/channels/
  __init__.py  base.py  discord_adapter.py
  (AD-472 EXTENDS; does NOT own __init__.py creation)

grep -n "class ChannelAdapter\|class ChannelMessage\|class ChannelConfig" src/probos/channels/base.py
  19: class ChannelConfig(BaseModel):
  24: class ChannelMessage:
  34: class ChannelAdapter(ABC):

grep -n "class DiscordAdapter\|class DiscordConfig" src/probos/
  src/probos/channels/discord_adapter.py:52: class DiscordAdapter(ChannelAdapter):
  src/probos/config.py:1306: class DiscordConfig(BaseModel):

grep -rn "class SlackAdapter\|class WebhookAdapter\|class SlackConfig\|class WebhookConfig" src/probos/
  (no matches -- AD-472 introduces these names)

grep -n "CHANNEL_MESSAGE_RECEIVED\|CHANNEL_DELIVERY_FAILED" src/probos/events.py
  (no matches -- names are free)

grep -n "channels: ChannelsConfig" src/probos/config.py
  1674: channels: ChannelsConfig = ChannelsConfig()

grep -n "DiscordAdapter\|--discord" src/probos/__main__.py
  439: from probos.channels.discord_adapter import DiscordAdapter
  444: adapter = DiscordAdapter(runtime, discord_cfg)
  1117: serve_parser.add_argument("--discord", action="store_true", ...)

grep -n "discord = \|copilot = " pyproject.toml
  46: discord = [
  50: copilot = [

grep -n "MCP_BRIDGE_INVOKE\|MCP_BRIDGE_FAILED" src/probos/events.py
  (lands with AD-449; AD-472 anchor depends on AD-449 first)

grep -n "Discord adapter failed" src/probos/__main__.py
  450: console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")
  (em-dash U+2014 confirmed; Section 6 SEARCH/REPLACE matches this character exactly)
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: adapters live in the existing `task_scheduler._channel_adapters` list (legacy private; no new public runtime attribute introduced for AD-472, consistent with the Discord precedent). ✅
- #2 stdlib-only for runtime persistence: yes; `slack-sdk` is opt-in. ✅
- #3 Coordinator-then-dispatch: v1 ships consultation surface; FastAPI route deferred to AD-472b. ✅
- #4 Superset-filter: ChannelAdapter ABC unchanged; new adapters are subclasses. ✅
- #5 init_<phase>: Section 6 wires from `__main__.py` (startup CLI). ✅
- #6 Verify-first: footer above. ✅
- #7 No-theater: real Slack auth_test, real shared-secret check, real emit. WebhookAdapter.send_response no-op is documented (not pretend). ✅
- #14 Aggressive pre-deferral: 4 of 7 capabilities deferred at draft time. ✅

---

## Revision (2026-05-02)

Applied review findings from `prompts/Reviews/ad-472-channel-adapters-review.md` (verdict: ⚠️ Conditional; 3 Required + 6 Recommended).

**Required addressed:**

- **R#1: `SlackConfig` and `WebhookConfig` defined twice.** Resolution: define ONCE in `config.py` (canonical Pydantic location, mirroring `DiscordConfig`). Section 2's `slack_adapter.py` and Section 3's `webhook_adapter.py` now import the configs (`from probos.config import SlackConfig` / `WebhookConfig`); the duplicate `class SlackConfig(ChannelConfig):` / `class WebhookConfig(ChannelConfig):` definitions are removed from the adapter modules. Section 5 reorganized: `SlackConfig` and `WebhookConfig` defined BEFORE `ChannelsConfig` so direct `SlackConfig()` / `WebhookConfig()` defaults bind without forward refs. `model_rebuild()` workaround dropped.
- **R#2: SEARCH/REPLACE em-dash mismatch in Section 6.** SEARCH and REPLACE blocks now use the em-dash `—` (U+2014) matching the live source at `__main__.py:450`. Builder note added explaining that convention #9 (ASCII-only source comments) does NOT apply when matching pre-existing source. Verified-against-codebase footer extended with explicit grep showing the em-dash character.
- **R#3: Pydantic forward-ref `= None` on non-Optional fields.** Resolution (a) chosen: configs defined BEFORE `ChannelsConfig`; direct defaults `slack: SlackConfig = SlackConfig()` and `webhook: WebhookConfig = WebhookConfig()`. Matches the existing `DiscordConfig` precedent. No `model_rebuild()` call needed. The Section 6 startup wiring simplifies from `if config.channels.slack and config.channels.slack.enabled` to just `if config.channels.slack.enabled` (configs are always-instantiated).

**Recommended applied:**

- **rec#1: drop Section 1b no-op.** Live grep confirmed no `fetch_messages` / `reconnection` / `on_disconnect` paths exist in `discord_adapter.py`. Section 1b rewritten as an explicit deferral to AD-472b (per convention #7, document the deferral instead of shipping a no-op). The Discord enhancements in v1 are now Section 1a (sender-allowlist confirmation) + Section 1c (intent-warning at startup).
- **rec#4: pin `slack-sdk` minor version.** Section 7 `pyproject.toml` extras line changed from `"slack-sdk>=3.27"` to `"slack-sdk>=3.21,<4"`. The `AsyncWebClient` import path is stable from 3.21+ and the `<4` upper bound prevents accidental major-version drift.

**Recommended deferred:**

- **rec#2: WebhookAdapter docstring tightening.** Cosmetic; existing docstring documents the synchronous-return-value contract clearly. No change.
- **rec#3: WebhookAdapter without FastAPI route is borderline-theater.** Architect judgment: keep WebhookAdapter in v1 because (a) the `receive(...)` method is fully testable today, (b) operator-driven test harnesses can call it directly, (c) AD-472b's FastAPI route is a 3-line addition that needs the adapter class to exist. The "bridge with no road" framing is honest deferral; convention #7 is honored because the inbound API surface is real even though the public HTTP route is pending. Documented in `What This Does NOT Change` already.
- **rec#5: Test 12 mock at adapter level.** Folded into the test plan's existing `monkeypatch a fake discord.Client` framing; Builder will choose the mock site at test-write time.
- **rec#6: footer adds `__main__.py:438-452` SEARCH anchor.** Folded into the rec#2 / R#2 em-dash grep entry above.

**Phantom-API pre-check (run during revision):**

```
grep -n "class ChannelAdapter\|class DiscordAdapter\|class DiscordConfig\|channels: ChannelsConfig" src/probos/
  channels/base.py:34: class ChannelAdapter(ABC):
  channels/discord_adapter.py:52: class DiscordAdapter(ChannelAdapter):
  config.py:1306: class DiscordConfig(BaseModel):
  config.py:1318: class ChannelsConfig(BaseModel):
  config.py:1674: channels: ChannelsConfig = ChannelsConfig()
```

All concrete claims grep-confirmed. No additional phantoms found.

**Test count: 12 → 12** (no new tests added; rec#5 is folded into existing Test 12).

**Verdict shift:** Pass-1 ⚠️ Conditional → expected ✅ Approved on second-pass review (3 Requireds mechanical; 4 of 6 Recommendeds applied; 2 deferred with explicit architect judgment).
