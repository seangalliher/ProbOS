# AD-803a — Telegram Adapter Substrate (polling + pairing-gate)

**Issues closed:** [#727](https://github.com/seangalliher/ProbOS/issues/727)
**Pairs with (in-wave):** AD-802a — ChannelAdapter `_check_pairing` hook
**Wave:** 190
**Author:** Architect (sole-author small-AD fast path)
**Estimated tests added:** ~12

## License disposition (surfaced per BUILDER standing rule)

The obvious dep is `python-telegram-bot`. It is **LGPL-3.0**. Per the standing rule (`Avoid AGPL/GPL — copyleft propagates into Apache 2.0`) and the "absorb the PATTERN, write our own code" policy, **this AD does not add the dep**. Instead it ships a minimal `TelegramClient` on top of `httpx` (already a ProbOS runtime dep).

Trade-off: we re-implement ~150 lines of API-call boilerplate that python-telegram-bot would handle. We gain: no LGPL infection, no new install requirement for OSS operators, smaller image, matches the way other ProbOS adapters call third-party HTTP APIs.

The Telegram Bot API is a stable HTTP-JSON endpoint set at `https://api.telegram.org/bot<token>/<method>` — well-documented and unlikely to break.

## Scope split (AD-803a vs deferred AD-803b)

| Capability | AD-803a (this wave) | AD-803b (later) |
|---|---|---|
| Long-polling `getUpdates` loop | ✅ | — |
| `sendMessage` outbound text | ✅ | — |
| Pairing-gate (via AD-802a) | ✅ | — |
| Webhook receive mode | — | ✅ |
| Photo / document inbound → `AttachmentStore` | — | ✅ |
| Voice memo → Whisper STT | — | ✅ |
| Outbound media (artifact replies, AD-797) | — | ✅ |
| Slash command registration with Bot Father | — | ✅ |

## File layout

- `src/probos/channels/base.py` — **modify** to add `_check_pairing(message) -> bool` hook and call it from `handle_message`.
- `src/probos/channels/telegram_client.py` — new. Minimal Bot API client on `httpx`. Methods: `get_me`, `get_updates`, `send_message`. Long-polling timeout default 25s.
- `src/probos/channels/telegram_adapter.py` — new. `TelegramAdapter(ChannelAdapter)`. Spawns a polling task on `start()`, cancels on `stop()`.
- `src/probos/channels/telegram_config.py` — new. `TelegramAdapterConfig(BaseModel)` (token, polling_timeout_s, allowed_updates).
- `src/probos/__main__.py` — **modify** to add `probos channel telegram setup` subcommand (interactive token entry, persists to `~/.probos/channels/telegram.yaml`).
- `src/probos/doctor/checks/channel_telegram_check.py` — new. Reads the persisted token, calls `getMe`, reports OK / FAIL.

## Public surface

### `TelegramClient`

```python
class TelegramClient:
    def __init__(self, token: str, *, http: httpx.AsyncClient | None = None, timeout: float = 30.0): ...
    async def get_me(self) -> dict: ...
    async def get_updates(self, *, offset: int | None = None, timeout: int = 25, allowed_updates: list[str] | None = None) -> list[dict]: ...
    async def send_message(self, chat_id: int | str, text: str, *, parse_mode: str | None = None, reply_to_message_id: int | None = None) -> dict: ...
    async def close(self) -> None: ...
```

### `TelegramAdapter`

```python
class TelegramAdapter(ChannelAdapter):
    def __init__(self, runtime, config: TelegramAdapterConfig, *, client: TelegramClient | None = None): ...
    async def start(self) -> None: ...   # spawns polling task
    async def stop(self) -> None: ...    # cancels + awaits
    async def send_response(self, channel_id: str, response: str, **kwargs) -> None: ...
    async def _poll_loop(self) -> None:  # private; runs until cancelled
    def _convert_update(self, update: dict) -> ChannelMessage | None:  # filters to text messages
```

### AD-802a `_check_pairing` hook on the base

Add to `ChannelAdapter`:

```python
async def _check_pairing(self, message: ChannelMessage) -> bool:
    """Return True if the message can proceed; False if a pairing was
    minted and the message was dropped. Default: no-op (returns True)
    when runtime.pairing_service is absent. Subclasses override only if
    they need adapter-specific behavior (e.g., per-chat allow-list).
    """
```

Default body reads `runtime.pairing_service`, calls `resolve_did(channel_name, raw_id)`. If None: calls `request_pairing(...)`, calls `self.send_response(channel_id, "Reply with /pair CODE…")`, returns False. If DID resolved: attaches it to the message via a new optional field on `ChannelMessage` and returns True.

`handle_message` calls `_check_pairing` first; bails out when it returns False.

## CLI verb

`probos channel telegram setup` (interactive):
- Prompts for bot token (input not echoed).
- Calls `TelegramClient.get_me()` to verify the token works; reports `Bot @YourBotName ready`.
- Writes `~/.probos/channels/telegram.yaml` with `enabled: true`, `token: …` (mode 0600 on POSIX).

## Doctor integration

`src/probos/doctor/checks/channel_telegram_check.py`:
- OK if config file missing (telegram is opt-in).
- OK with bot username if token valid + `getMe` returns 200.
- FAIL if config exists but token invalid / unreachable.

## Test plan (`tests/test_ad803a_telegram.py`)

12 tests, all `-n 0`-safe, no real network. Use `httpx.MockTransport` for the API.

1. `TelegramClient.get_me` parses `result.username`.
2. `get_updates` builds the right URL + query string with `offset` + `timeout`.
3. `send_message` posts the right body.
4. `_convert_update` returns `None` for non-text messages (photo, voice, etc.).
5. `_convert_update` returns a `ChannelMessage` with `text`, `channel_id=str(chat_id)`, `user_id=str(from.id)`, `user_display_name` from `from.username` / `from.first_name`.
6. `_check_pairing` on the base returns True when `runtime.pairing_service` is `None`.
7. `_check_pairing` on the base calls `request_pairing` + `send_response` and returns False when sender unknown.
8. `_check_pairing` on the base returns True when `resolve_did` returns a DID.
9. `TelegramAdapter.start()` spawns the polling task; `stop()` cancels it.
10. Polling loop calls `get_updates` with `offset` updated past the last seen `update_id`.
11. Polling loop calls `handle_message` for each text update.
12. `channel_telegram_check` doctor returns OK when token is valid (mock), FAIL when invalid.

## Acceptance

- `probos channel telegram setup` walks the operator through setup and persists `~/.probos/channels/telegram.yaml`.
- `probos doctor` includes a `channel_telegram` check.
- Unit tests cover the polling lifecycle + pairing-gate plumbing end-to-end (no real network).
- Full pytest gate stays non-decreasing.
- No new entries in `pyproject.toml` `dependencies`.

## Out of scope (forward markers)

- **AD-803b** — webhook mode, media attachments (AD-720 integration), voice-memo Whisper STT (AD-705a integration), outbound media (AD-797 artifact replies), Bot Father slash-command registration.
- **AD-803c** — group-chat / channel-mention semantics. Today's adapter handles 1:1 DM only.
- **AD-803d** — per-chat → AD-791 thread mapping when AD-791 lands (today, route inbound to default per-sender DM with Yeo).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
