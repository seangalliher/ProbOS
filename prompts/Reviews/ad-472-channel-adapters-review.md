# Review: AD-472 — Channel Adapters (v1)

**Verdict:** ⚠️ Conditional — `SlackConfig`/`WebhookConfig` defined twice (config.py + adapter.py); SEARCH/REPLACE for Discord block has em-dash mismatch; Optional typing on forward-ref defaults. All mechanical fixes; no architectural rework.

**Date:** 2026-05-02

**Headline:** Section 2 + Section 5 redundantly define `SlackConfig` and `WebhookConfig` in two modules with different parents (`ChannelConfig` vs `BaseModel`). Builder will hit a name-collision and type-mismatch.

---

## Required (must fix before building)

1. **`SlackConfig` and `WebhookConfig` defined in two places with different parents.** Section 2 (`channels/slack_adapter.py`):

   ```python
   class SlackConfig(ChannelConfig):
       enabled: bool = False
       bot_token: str = ""
       ...
   ```

   Section 5 (`config.py`, after `ChannelsConfig` rebuild):

   ```python
   class SlackConfig(BaseModel):
       enabled: bool = False
       bot_token: str = ""
       ...
   ```

   Two classes, same name, different parents. The startup code at `__main__.py` (Section 6) does `if config.channels.slack and config.channels.slack.enabled` — the typed config is the `BaseModel` version. The adapter's `__init__(runtime, config: SlackConfig)` annotates the local `ChannelConfig`-subclass version. **Type mismatch + name shadow.** Same problem applies to `WebhookConfig`.

   **Fix:** define `SlackConfig` and `WebhookConfig` once — in `config.py` as `BaseModel` subclasses (matching the existing `DiscordConfig` precedent at `config.py:1306`). The adapter modules import from `config`:

   ```python
   from probos.config import SlackConfig
   ```

   Drop the local `class SlackConfig(ChannelConfig):` definition from `slack_adapter.py`. Same for `webhook_adapter.py`.

2. **Section 6 SEARCH block contains ASCII `-` where live code uses em-dash `—`.** Live source at `__main__.py:450`:

   ```
   console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")
   ```

   The prompt's SEARCH block has `"Discord adapter failed - run"` (ASCII hyphen). Builder's text search will MISS — SEARCH/REPLACE will not apply. **Fix:** correct the SEARCH block to use the em-dash:

   ```
   "  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord"
   ```

   (Ironically, convention #9 says "ASCII-only source comments" for new comments — but this is matching pre-existing source, not adding a new comment. The em-dash already exists; the SEARCH must match what's there.)

3. **Section 5 forward-reference defaults use `None` on non-Optional Pydantic fields.** Lines:

   ```python
   class ChannelsConfig(BaseModel):
       discord: DiscordConfig = DiscordConfig()
       slack: "SlackConfig" = None  # set after class definition (forward ref)
       webhook: "WebhookConfig" = None
   ```

   With Pydantic v2, `slack: "SlackConfig" = None` has type `SlackConfig` (not `Optional[SlackConfig]`). At validation time Pydantic raises a type error because `None` is not a `SlackConfig`. **Fix options:**

   - (a) Reorder: define `SlackConfig` and `WebhookConfig` BEFORE `ChannelsConfig` (the prompt itself recommends this in the Builder note as "preferred" — promote it to the only path):

     ```python
     class SlackConfig(BaseModel):
         ...
     class WebhookConfig(BaseModel):
         ...
     class ChannelsConfig(BaseModel):
         discord: DiscordConfig = DiscordConfig()
         slack: SlackConfig = SlackConfig()
         webhook: WebhookConfig = WebhookConfig()
     ```

   - (b) Use proper Optional typing with `None` defaults:

     ```python
     slack: SlackConfig | None = None
     webhook: WebhookConfig | None = None
     ```

   Recommend (a) — matches the existing `DiscordConfig` precedent and avoids the runtime `model_rebuild()` call. Also subsumes Required #1 if `SlackConfig`/`WebhookConfig` are sourced from `config.py`.

---

## Recommended

1. **Section 1b — `fetch_messages reconnection recovery`** is documented as "Builder MUST grep before adding" with explicit no-op guidance if not found. Live grep:

   ```
   grep -n "fetch_messages\|reconnection\|on_disconnect" src/probos/channels/discord_adapter.py
   (no matches)
   ```

   So Section 1b IS a no-op for v1. Per convention #7, drop the section entirely from the v1 prompt rather than ship guidance that's already known to no-op. Saves Builder a grep + a build-report explanation.

2. **WebhookAdapter.send_response is a documented no-op.** The prompt acknowledges this as "honest deferral, not theater" — and it IS, because the inbound `receive()` returns the response synchronously. ✅. But the contract docstring at lines 312-318 should restate the synchronous-return-value contract (the originating route receives the response inline) to make the no-op less surprising.

3. **WebhookAdapter has no FastAPI route registration.** The prompt explicitly defers route wiring to AD-472b. Without a route, `WebhookAdapter.receive` is unreachable from external HTTP traffic in v1 — only via tests or manual code calls. **This means v1 ships zero working webhook delivery.** Consider whether the WebhookAdapter is genuinely v1-shippable, or whether it should also be deferred to AD-472b (where the route lands). The current state is "bridge with no road"; honest, but the v1 deliverable list shrinks to 2 (Discord enhancements + Slack) if WebhookAdapter is honestly assessed.

4. **`pyproject.toml` extras add `slack-sdk>=3.27` but the SlackAdapter imports `slack_sdk.web.async_client.AsyncWebClient`.** Verify the import path in `slack-sdk` 3.27+. Per the slack-sdk docs, the path is `slack_sdk.web.async_client.AsyncWebClient` (was `AsyncSlackClient` in early 3.x). Recommend pinning a known-compatible minor version, e.g., `slack-sdk>=3.21,<4` (the AsyncWebClient path is stable from 3.21+).

5. **Test 12 (Discord intent warning)** uses `monkeypatch a fake discord.Client with intents.message_content=False`. This works only if `DiscordAdapter.start()` reads `self._client.intents` synchronously before the network connect. Builder will need to confirm the read order. Recommend the test mocks at the adapter level (`_client = fake`) rather than at the `discord.Client` import level.

6. **AD-472 verify-first footer.** The footer claims `channels: ChannelsConfig = ChannelsConfig()` at `config.py:1674`. Live grep confirms this. ✅. But the footer should also include the `__main__.py:438-452` Discord-startup block as the SEARCH anchor for Section 6 — currently absent.

---

## Nits

- The opt-in extra naming `slack` matches the existing `discord` precedent. ✅
- `WebhookConfig.shared_secret = ""` warning when empty is clear; `start()` does the right thing.
- `class WebhookConfig(ChannelConfig)` in `webhook_adapter.py` then `class WebhookConfig(BaseModel)` in `config.py` mirrors the Slack name-collision (Required #1). Same fix.
- Section 6's startup code uses `getattr(adapter, "_started", False)` — defensive read on a private attribute is OK for the existing `DiscordAdapter` precedent which also exposes `_started`. Mild Demeter violation but matches the established pattern.
- `pyproject.toml:46-49` (Discord extras) shows `aiohttp>=3.9,<3.13` constraint. The Slack extras don't pin `aiohttp` — but `slack-sdk` doesn't depend on `aiohttp` (it has its own httpx-based client in 3.x). ✅
- Section 0 EventTypes `CHANNEL_MESSAGE_RECEIVED` and `CHANNEL_DELIVERY_FAILED` are free in `events.py`. ✅

---

## Verified (looks good)

- `ChannelAdapter` ABC at `channels/base.py:34`. ✅
- `DiscordAdapter` at `channels/discord_adapter.py:52`. ✅
- `DiscordConfig` at `config.py:1306` (base reference for Slack/Webhook). ✅
- `ChannelsConfig` at `config.py:1318`. ✅
- `runtime.task_scheduler._channel_adapters` integration site at `__main__.py:456`. ✅
- 4 deferred adapters (Telegram, WhatsApp, Matrix, Teams) wholesale-deferred at draft time per convention #14. ✅
- No new HARD pyproject deps (slack-sdk is opt-in). ✅
- `convention #9 ASCII comments`: new code uses ASCII; the SEARCH-block em-dash is matching existing source, not adding a new Unicode comment.

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ (no new runtime attrs; uses existing `task_scheduler._channel_adapters` list per Discord precedent) |
| 2 | stdlib-only | ✅ |
| 3 | Coordinator-then-dispatch | ✅ FastAPI route deferred to AD-472b |
| 4 | Superset-filter | ✅ ABC unchanged |
| 5 | init_<phase> | ✅ Section 6 wires from `__main__.py` (CLI startup) |
| 6 | Verify-first | ⚠️ Required #2 (em-dash mismatch) |
| 7 | No-theater | ⚠️ WebhookAdapter has no FastAPI route in v1 (Recommended #3) |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A |
| 9 | ASCII-only comments | ✅ (em-dash issue is matching pre-existing source) |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | ✅ |
| 12 | Solution Overview drift | ✅ |
| 13 | Pool template name collision | N/A |
| 14 | Aggressive pre-deferral | ✅ 4 of 7 deferred |
| 15 | Tolerance: relaxed | n/a (review tier) |

---

## Bottom Line

Three mechanical Required fixes (config-class duplication, em-dash SEARCH miss, forward-ref defaults). One borderline-theater concern (WebhookAdapter without route). Revisable in one pass; expected to converge.

---

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved

**Headline:** All 3 Required findings genuinely resolved; configs single-defined in config.py, em-dash SEARCH literal matches live source, forward-ref typing eliminated via reorder. No regressions.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: SlackConfig/WebhookConfig defined twice | ✅ Resolved | Adapter modules now import: `from probos.config import SlackConfig` (line 145), `from probos.config import WebhookConfig` (line 293). Section 5 REPLACE block defines configs ONCE in config.py. The local `class SlackConfig(ChannelConfig):` and `class WebhookConfig(ChannelConfig):` definitions are removed from adapter source. |
| R#2: SEARCH em-dash mismatch | ✅ Resolved | Lines 506, 527, 544 all use em-dash `—` (U+2014) matching live source at `__main__.py:450` (verified: line 712 of the prompt cites `console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")`). Builder note explicitly explains convention #9 does NOT apply when matching pre-existing source. |
| R#3: forward-ref `= None` typing | ✅ Resolved | Section 5 REPLACE block reorders: `class SlackConfig(BaseModel)` and `class WebhookConfig(BaseModel)` defined BEFORE `class ChannelsConfig(BaseModel)`; direct defaults `slack: SlackConfig = SlackConfig()` and `webhook: WebhookConfig = WebhookConfig()` bind without `model_rebuild()`. Forward-ref `= None` workaround dropped. Section 6 startup wiring simplified to `if config.channels.slack.enabled:` (configs always-instantiated). |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: drop Section 1b no-op | ✅ Applied | Section 1b rewritten as explicit deferral to AD-472b. The Discord enhancements in v1 are now Section 1a (sender allowlist) + Section 1c (intent warning). |
| rec#2: WebhookAdapter docstring tightening | 📦 Deferred | Cosmetic; existing docstring is clear. |
| rec#3: WebhookAdapter without FastAPI route | 📦 Deferred | Architect judgment: keep WebhookAdapter in v1; `receive(...)` is testable today; AD-472b adds the route. Documented in `What This Does NOT Change`. |
| rec#4: pin slack-sdk minor version | ✅ Applied | `slack-sdk>=3.21,<4` in pyproject extras. |
| rec#5: Test 12 mock at adapter level | 📦 Deferred | Folded into existing test framing. |
| rec#6: footer add __main__.py SEARCH anchor | ✅ Applied | Footer line 711-712 has the explicit em-dash grep evidence. |

### New Findings (introduced during revision)

None. Revisions to Section 5 / Section 6 / Section 1b / pyproject extras / verify-first footer are all targeted; no collateral drift.

### Verified Against Revised Codebase Claims

- Live source `__main__.py:450` uses em-dash `—`: confirmed by direct grep ✅
- `class ChannelAdapter(ABC)` at `channels/base.py:34` ✅
- `class DiscordConfig(BaseModel)` at `config.py:1306` (precedent for SlackConfig/WebhookConfig single-definition) ✅
- `class ChannelsConfig(BaseModel)` at `config.py:1318` (anchor for Section 5) ✅
- `runtime.task_scheduler._channel_adapters` integration site at `__main__.py:456` ✅

### Tolerance Assessment

AD-472 cleared second-pass cleanly. The R#1 R#2 R#3 trio (config consolidation + em-dash + forward-ref typing) was a tight cluster of mechanical fixes; revision applied each surgically without regressions. Ready for Builder dispatch.
