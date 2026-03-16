# Phase 24a: Discord Bot Adapter — Channel Integration

**AD-274 through AD-278** | Implements the first channel adapter from the Phase 24 roadmap.

## Context

Phase 24 is "Channel Integration + Tool Connectors." This prompt implements the Discord bot adapter — the first external channel. It also establishes the reusable `ChannelAdapter` base pattern for future channels (Slack, email, Teams).

**Current highest AD: AD-273.** This prompt uses AD-274 through AD-278.

## Pre-done Work

The architect session already created the following files. **Do not recreate them.** Read each one, verify it's correct, then proceed from Step 4.

| File | Status | What it does |
|------|--------|-------------|
| `src/probos/channels/__init__.py` | Created | Package init, re-exports |
| `src/probos/channels/base.py` | Created | `ChannelAdapter` ABC + `ChannelMessage` dataclass |
| `src/probos/channels/response_formatter.py` | Created | `extract_response_text()` — shared response extraction |
| `src/probos/channels/discord_adapter.py` | Created | `DiscordAdapter` — full Discord bot implementation |
| `src/probos/config.py` | Modified | Added `DiscordConfig`, `ChannelsConfig`, wired into `SystemConfig` |
| `src/probos/api.py` | Modified | Refactored to use shared `extract_response_text()` for fallback |
| `src/probos/__main__.py` | Modified | Added `--discord` flag to `serve_parser` (partial — lifecycle not wired) |

## Architecture

```
Discord message → DiscordAdapter.on_message()
    → ChannelAdapter.handle_message()
        → runtime.process_natural_language() [NL]
        → api._handle_slash_command() [slash commands via ! prefix]
    → extract_response_text(dag_result)
    → DiscordAdapter.send_response() → Discord channel reply
```

The adapter runs as a background `asyncio.create_task` alongside the API server in `probos serve --discord`.

---

## Steps

### Step 1: Read and verify pre-done files (AD-274)

Read all 7 files listed above. Verify:
- `response_formatter.py` correctly mirrors the extraction logic formerly in `api.py` (response → reflection → correction → results fallback)
- `base.py` ChannelAdapter uses `runtime.process_natural_language()` for NL and `api._handle_slash_command()` for slash commands
- `discord_adapter.py` uses `asyncio.create_task(bot.start())` not `bot.run()` (event loop sharing)
- `discord_adapter.py` has lazy `import discord` inside `start()` and event handlers
- `config.py` has `DiscordConfig` with: enabled, token, allowed_channel_ids, command_prefix, mention_required
- `config.py` has `channels: ChannelsConfig = ChannelsConfig()` in SystemConfig
- `api.py` refactor preserved the diagnostic block (lines ~271-315) — only the extraction logic was replaced
- `__main__.py` has the `--discord` flag on serve_parser

Fix any issues found. Run tests after: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

Report test count. All 1590 existing tests must pass.

### Step 2: Wire Discord adapter lifecycle into `_serve()` (AD-275)

In `src/probos/__main__.py`, modify the `_serve()` function:

1. After `app = create_app(runtime)` (around line 357), add Discord adapter startup:
   - Check `getattr(args, 'discord', False) or config.channels.discord.enabled`
   - If enabled: import `os` and `DiscordAdapter` from `probos.channels.discord_adapter`
   - Resolve token: `os.environ.get("PROBOS_DISCORD_TOKEN", "") or config.channels.discord.token`
   - Create a copy of the config with the resolved token
   - Create `DiscordAdapter(runtime, discord_config)` and `await adapter.start()`
   - Print: `console.print("  [green]✓[/green] Discord bot adapter started")`
   - Store adapter in a list for shutdown

2. In the `finally` block (around line 397), before `runtime.stop()`:
   - Stop all adapters: `for adapter in adapters: await adapter.stop()`
   - Wrap in try/except to not block shutdown

3. The `_serve()` function signature does NOT need to change — the `--discord` flag comes through the `args` namespace in the caller (`_cmd_serve` or similar dispatch in `main()`). Check how `--interactive` is passed and follow the same pattern.

**Important:** Look at how `--interactive` is currently passed from `main()` to `_serve()`. If `_serve()` doesn't receive `args` directly, you'll need to add a `discord: bool = False` parameter to `_serve()` and pass it from the caller.

Run tests after. Report count.

### Step 3: Update pyproject.toml and config/system.yaml (AD-276)

1. In `pyproject.toml`, add optional dependency group after `dev`:
   ```toml
   discord = [
       "discord.py>=2.0",
   ]
   ```

2. In `config/system.yaml`, add a commented-out channels section at the end:
   ```yaml
   # --- Channel Adapters (Phase 24) ---
   # channels:
   #   discord:
   #     enabled: false
   #     token: ""                     # Set via PROBOS_DISCORD_TOKEN env var
   #     allowed_channel_ids: []       # Empty = all channels
   #     command_prefix: "!"           # "!status" -> "/status"
   #     mention_required: false       # Only respond when @mentioned
   ```

Run tests after. Report count.

### Step 4: Create tests — test_channel_base.py (AD-277)

Create `tests/test_channel_base.py`:

**TestExtractResponseText:**
- `test_none_result` — returns "(Processing failed)"
- `test_direct_response` — `{"response": "Hello"}` → "Hello"
- `test_reflection_fallback` — `{"response": "", "reflection": "Based on..."}` → reflection text
- `test_correction_fallback` — `{"response": "", "correction": {"changes": "Fixed"}}` → correction text
- `test_results_with_stdout` — node result with `.result = {"stdout": "output"}` → "output"
- `test_results_with_string` — node result with `.result = "file contents"` → "file contents"
- `test_results_with_error` — node result with `.error = "failed"` → "Error: failed"
- `test_empty_result` — `{"response": "", "results": {}}` → non-empty fallback message

**TestChannelMessage:**
- `test_construction` — verify fields
- `test_defaults` — display_name defaults to "", reply_to defaults to None

**TestChannelAdapterHandleMessage:**
Create a `_FakeAdapter(ChannelAdapter)` stub (following ProbOS test conventions):
- Implement `start()`, `stop()`, `send_response()` as no-ops
- `test_slash_command` — message starting with "/" routes through slash handler
- `test_natural_language` — message without "/" routes through `process_natural_language()`
- `test_conversation_history` — two messages to same channel_id → history has 4 entries (2 user + 2 assistant)
- `test_history_trimming` — send 12 messages → history trimmed to `max_history * 2` entries

For the NL tests, boot a real `ProbOSRuntime` with `MockLLMClient` (follow the pattern in `tests/test_hxi_chat_integration.py`).

Run tests after. Report count — should be 1590 + new tests.

### Step 5: Create tests — test_discord_adapter.py (AD-278)

Create `tests/test_discord_adapter.py`:

**TestChunkMessage:**
- `test_short_message` — "hello" → `["hello"]`
- `test_exact_limit` — 2000 chars → single chunk
- `test_long_message_splits_on_newline` — message with newline at position < 2000 → splits there
- `test_very_long_hard_splits` — 5000 chars no spaces → all chunks ≤ 2000

**TestDiscordAdapterInit:**
- `test_creates_with_config` — verify `DiscordAdapter(runtime, config)` doesn't crash
- `test_config_defaults` — verify DiscordConfig defaults (enabled=False, prefix="!", mention_required=False)

**TestDiscordConfig:**
- `test_config_in_system_config` — load a SystemConfig with channels.discord section, verify it parses
- `test_config_defaults` — SystemConfig() has channels.discord.enabled == False

Do NOT test actual Discord connectivity — no `import discord` in tests. Only test `_chunk_message()`, config models, and adapter construction.

Run full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

Report final test count.

---

## Acceptance Criteria

1. All pre-existing 1590 tests pass at every step
2. New test count: ~1590 + 15-20 new tests
3. `probos serve --discord` flag exists and accepted
4. Discord adapter starts when `PROBOS_DISCORD_TOKEN` is set and `--discord` passed
5. Adapter fails gracefully (log + return) when discord.py not installed or token empty
6. `api.py` still works identically (the refactor is behavior-preserving)
7. `config/system.yaml` has documented channel config section

## Do Not Build

- **Do not build Slack, email, or any other adapter.** Only Discord.
- **Do not register Discord slash commands** (application commands). Use the `!` prefix mapping.
- **Do not add Discord as a required dependency.** It must be optional (`discord.py>=2.0` in `[project.optional-dependencies]`).
- **Do not modify the runtime.** `process_natural_language()` is used as-is.
- **Do not refactor the IntentBus, decomposer, or shell.** The adapter is a consumer.
- **Do not add federation or multi-node features.**
- **Do not install discord.py** unless the user asks you to test the actual connection.
- **Do not expand scope beyond these 5 steps.**
