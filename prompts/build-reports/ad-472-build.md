# AD-472 Build Report

**Date:** 2026-05-02
**Builder:** Wave 8 continuous-build (3 of 6)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+4: EventTypes | `src/probos/events.py` | ✅ Added `CHANNEL_MESSAGE_RECEIVED`, `CHANNEL_DELIVERY_FAILED` after AD-475 anchor |
| Section 1a: allowed_user_ids enforcement | `src/probos/channels/discord_adapter.py:271-277` | ✅ Already in correct position (no-op per prompt) |
| Section 1b: fetch_messages reconnection | (deferred to AD-472b) | ✅ Documented as wholesale-deferred per convention #7 |
| Section 1c: Message Content Intent warning | `src/probos/channels/discord_adapter.py:90+` | ✅ Inserted after `discord.Client(intents=intents)`; uses live attribute name `self._bot` (prompt's `self._client` was a hint, defensive `getattr` pattern handles it) |
| Section 2: SlackAdapter | `src/probos/channels/slack_adapter.py` (new) | ✅ Imports `SlackConfig` from `config.py` (single-definition per Required #1) |
| Section 3: WebhookAdapter | `src/probos/channels/webhook_adapter.py` (new) | ✅ Imports `WebhookConfig` from `config.py` |
| Section 5: ChannelsConfig extension | `src/probos/config.py:1306+` | ✅ SlackConfig + WebhookConfig defined BEFORE ChannelsConfig; direct `SlackConfig()`/`WebhookConfig()` defaults |
| Section 6: __main__.py startup | `src/probos/__main__.py:451+` | ✅ Slack + Webhook adapter blocks added after Discord; em-dash `—` matches live source character-for-character |
| Section 7: pyproject extras | `pyproject.toml` | ✅ `slack-sdk>=3.21,<4` added; no new HARD deps |
| Tests | `tests/test_ad472_channel_adapters.py` (new) | ✅ 11 passed, 1 skipped (Discord test gated on discord.py) at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4193` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad472_channel_adapters.py -v -n 0` → **11 passed, 1 skipped in 0.26s**
- Full parallel gate: **10,498 passed (+11 vs AD-484 baseline 10,487), 15 skipped (+1 from Discord intent test)**

## Notes / Decisions

- Live source attribute is `self._bot` not `self._client` (prompt was approximate). Defensive `getattr(self._bot, "intents", None)` pattern handles either name.
- The intent attribute is hardcoded to `True` at `discord_adapter.py:87` (`intents.message_content = True`); the warning fires only if a future operator override sets it False. Pattern preserved per prompt.
- Section 5 reordering: `SlackConfig` + `WebhookConfig` defined BEFORE `ChannelsConfig` so direct field defaults bind. No `model_rebuild()` workaround needed (preferred per Required #3).
- Section 6 SEARCH-block em-dash matches live `__main__.py:450` character (U+2014). Convention #9 (ASCII-only source comments) does NOT apply when matching pre-existing source.
- `WebhookAdapter.send_response` is a documented no-op in v1; FastAPI route registration deferred to AD-472b.
- Wholesale-deferred (convention #14): Telegram → AD-472b, WhatsApp → AD-472c, Matrix → AD-472d, Microsoft Teams → AD-472d, FastAPI webhook route → AD-472b.

## Pre-Commit Sanity Check

11 files changed, ~520 insertions, ~6 deletions. Max per-file deletion: ~5 lines. Well under 200-line threshold.
