# BF-914: a channel adapter's empty user allow-list admits no one, and admitting everyone is an explicit opt-in

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23

**Status:** build-ready after the orchestrator verifies it by tool on the then-current `main`. Decided by the Architect under Delegated AD Execution Mode (§3 D0). **Tier HIGH** (a default security control). **Base:** `origin/main` `ba20e949` (AD-1347 S1 and S4 and wave 2 merged). AD-1347 S2+S3 (in review) touches none of this contract's files (§5, last row). **Number:** BF-914. Nothing is allocated. **Issue:** #1621.

**Tests:** one new file, `tests/test_bf914_channel_allow_lists.py`: 11 functions, 21 cases. Nine updated pins (§6).

**Line endings:** working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with each file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| Discord's and Slack's user lists mean "empty = everyone" | present | `config_models/experience.py:393` (comment `Empty = respond to all users (SECURITY RISK)`), `:661`; filters `discord_adapter.py:287-293`, `slack_adapter.py:192-193`, `:252-253` |
| No pairing service is ever wired, so `_check_pairing` passes every sender | present | `channels/base.py:198-200`; Absence AV1 |
| An admitted sender's `/` text reaches the ship's shell with no caller identity | present | `base.py:295-298` → `api.py:74-83` (blocks only `/quit`, `/debug`, `:46`) |
| The shipped config enables Discord with both lists empty | present | `config/system.yaml:1134-1141` (HEAD; this worktree is clean) |
| Only Discord, Slack and the webhook adapters are constructed in production | present | `__main__.py:826-868`; Absence AV2 |
| The doctor reports OK for an enabled, token-present Discord adapter with an empty user list | present | `doctor/checks/channel_discord_check.py:49-60` |

## 1. Problem

`DiscordAdapter.on_message` (`discord_adapter.py:287-293`), `SlackAdapter.receive` (`slack_adapter.py:192`) and `SlackAdapter._convert_message` (`:252`) apply the user list only when it is non-empty. With no pairing service (AV1), every sender reaches `ChannelAdapter.handle_message`. From there, `/prune`, `/order`, `/revoke`, `/grant`, `/credentials`, `/approve`, `/rollback` and natural-language turns are all reachable (`shell.py:63-123`, `:101`). The shipped config enables Discord with an empty list. Installing `discord.py` and setting a token opens it to any Discord user who can message the bot.

## 2. Solution overview

- `DiscordConfig` and `SlackConfig` gain `allow_all_users: bool = False`.
- `ChannelAdapter` gains the rule, once:
  - `_sender_admitted`: admit a sender when the opt-in is on or its id is listed; ids compare as strings;
  - `_log_refused_sender`: one WARNING per refused sender, without the text, bounded at 256 ids plus one cap line;
  - `_warn_sender_policy`: one WARNING at start when the adapter will admit no one, or everyone.
- Discord's `on_message` and Slack's `receive` and `_convert_message` call the rule at their existing filter sites. Discord's and Slack's `start` call the start warning.
- `channel_discord_check` WARNs when the opt-in is on, or when the user list is empty.
- One doc sentence that claims pairing gates every new sender is corrected.
- The config manifests and the pins that freeze the models' fields absorb the two new fields.

## 3. Decisions

**D0: classification (in the envelope).** It strengthens a control. "Empty = all" was labelled a risk, not promised. `allow_all_users: true` is the tested migration path. No shipped config changes, and rollback is a revert. None of the six Captain conditions applies (`orchestrator.agent.md:114-121`).

**D1: fail closed (ranked 1 of 4).** Alternatives: Gmail and Teams now (2: unreachable today, register); one base-class gate in `handle_message` (3: rejected, because Telegram and Matrix rely on pairing alone and the webhook's user id is caller-asserted); keep "empty = all" with a doctor WARN only (4: rejected, it leaves the exposure).

**D2: where the rule lives.**
- The policy is defined once on the base class. Each adapter calls it where it already filters, because that is where the sender's own id is known:
  - Discord: the integer `message.author.id`, before the typing indicator and any reply;
  - Slack: the string `user` / `user_id`, before `_emit_received`.
- `handle_message` is not used as the choke point. Its `ChannelMessage.user_id` is reliable for every adapter, but adapters differ in who their sender is (the webhook's id is caller-asserted) and in what gate they rely on (pairing only, for Telegram and Matrix).

**D3: the opt-in.** One bool per adapter config, beside its list: `channels.discord.allow_all_users`, `channels.slack.allow_all_users`.
- A copy of today's config has no such key, so it refuses every sender (test N11).
- A Captain who truly wants "everyone" sets `allow_all_users: true`, and the start warning and doctor WARN then name the slash-command reach.
- No new top-level section. The ids compare as strings, so `[7]` admits Discord author `7` and nothing else.
- A sender is admitted if `allow_all_users` OR it is listed. A list together with the opt-in admits everyone, and the doctor says so.

**D4: the doctor and the start warning.**
- Doctor: WARN, not FAIL. FAIL drives the doctor's exit code (`doctor/protocol.py:26-28`), and both states are valid configs: an inert adapter, or a deliberate opt-in. Token-empty FAIL is unchanged.
- The start warning follows the precedent at `webhook_adapter.py:34-38`.
- A refused sender is logged once, as `%r` of the id and never the text. The set of logged ids is capped at 256, so a flood of throwaway accounts can grow neither memory nor the log.
- No `await` separates the check from the record, so overlapping refusals log once (N3 proves it with `asyncio.gather`).

**D5: defence in depth (deferred to the pairing-wiring AD).** See the consult's ranking. This issue changes nothing in `api.py` or `shell.py`.

## 4. Milestones

One milestone, M1, opened by §7.1. One commit for code and tests; the tracker pairs in §8 go in the same commit.

## 5. Consumers of every value this changes

| Value | Consumer | Accepts it because |
|---|---|---|
| `DiscordConfig.allow_all_users`, `SlackConfig.allow_all_users` | `on_message`, `receive`, `_convert_message`, both `start`s; `channel_discord_check`; the config facade baseline; `config-profiles.yaml` (classification + census); `config-reference.md` (generated); `test_ad1270e2c` EXPECTED_DUMPS; `test_ad1152` golden; `test_ad1270e1` field count | each is updated or regenerated in §7 |
| `_sender_admitted` returning False | Discord: returns before typing, reply or `handle_message`. Slack `receive`: returns `""` (its existing refusal value, `:191`). Slack `_convert_message`: `None`, after `_process_channel` has already advanced the offset (`:282-288`) | the same values the channel filters already return |
| New WARNING lines on `probos.channels.base` | operator log | no test reads them except N3, N4, N8, N9 |
| Doctor WARN | `probos doctor` output; WARN does not count as a failure | `protocol.py:26-28` |
| AD-1347 S2+S3 | edits `agent_stop.py`, `agent_work*.py`, `cognitive/*`, `proactive.py`, `routers/capability_requests.py`, `runtime.py`, `startup/*`, `ward_room_pipeline.py` | disjoint from every file here |

## 6. Tests

**New, `tests/test_bf914_channel_allow_lists.py` (§7.17).**
- The real Discord `on_message` closure runs over a fake bot with a stub `discord` module (the `test_ad807_discord_refresh.py:147-164` technique), so `discord.py` need not be installed.
- The real `SlackAdapter` runs over `httpx.MockTransport` through `SlackClient`.
- `probos.api._handle_slash_command` is replaced by a recorder, so no command runs. N1 asserts the premise that `/prune` is a shell command.
- Every refusal test carries a control on the same harness that shows a delivery is observable.

| # | Test | Proves |
|---|---|---|
| N1 | `test_discord_an_unlisted_sender_never_reaches_the_shell` | issue acceptance: the real filter; a listed sender's `!prune` reaches the recorder (control); an unlisted one's does not, and nothing is posted |
| N2 | `test_discord_an_empty_allow_list_refuses_every_sender` | empty list: no slash, no natural language, no post. Control: the same harness with the opt-in admits both |
| N3 | `test_a_refused_sender_is_logged_once_without_its_text` | two overlapping refusals of one sender plus a third → one line; a second sender → its own line; no line contains the text |
| N4 | `test_the_refusal_log_is_bounded` | cap 2: two per-sender lines, one cap line, nothing after |
| N5 | `test_slack_poll_refuses_an_unlisted_sender_before_the_shell` | real `_process_channel`: only the listed sender reaches the shell and gets a reply |
| N6 | `test_slack_receive_refuses_on_an_empty_list_and_admits_with_the_opt_in` | webhook entry point, both directions |
| N7 | `test_slack_convert_message_applies_the_rule` (5 cases) | boundary table: empty, listed, unlisted, opt-in empty, opt-in with list |
| N8 | `test_slack_start_states_who_it_admits` (3 cases) | start warning: empty / listed (none) / opt-in |
| N9 | `test_discord_start_warns_when_it_admits_no_one` | Discord start warning, through a stub `discord` |
| N10 | `test_doctor_channel_discord_judges_the_user_allow_list` (4 cases) | issue acceptance: the doctor's empty-list case; OK / WARN empty / WARN opt-in / WARN opt-in with list |
| N11 | `test_the_opt_in_is_off_by_default_and_a_copy_of_todays_block_keeps_it_off` (2 cases) | D3 migration property |

**Updated pins.** Each one fails, or would pass vacuously, on the M1 tree without its update. Hunted by grep (§12, AV5 and AV6):
- `tests/test_ad807_discord_refresh.py` `_wire_on_message`: sender 42 must be listed. `test_discord_posts_nothing_when_pairing_instructions_fail` asserts that the message reached the pairing gate, and `test_discord_still_reports_other_processing_failures` asserts that processing ran (§7.7).
- `tests/test_ad804_slack.py`: `test_convert_message_returns_message_for_user_text`, `test_convert_message_drops_self_messages` and `test_convert_message_honors_allowed_channel_ids` expect admission. `test_convert_message_drops_bot_subtype` would pass vacuously, so U1 is listed to keep it testing the subtype filter (§7.8).
- `tests/test_bf804_pairing_notification.py` (the Slack webhook pair, `:413`): the paired control expects `_PAIRED_NO_CONVERSATION` (§7.9).
- `tests/test_bf903_channel_and_mcp.py:279`: it would pass vacuously by refusal instead of exercising the unreadable pairing store (§7.10).
- `tests/test_ad1270e2c_experience_models.py` EXPECTED_DUMPS: Discord and Slack (§7.11).
- `tests/test_ad1152_agentic_correlation.py`: the golden pops (§7.12).
- `tests/test_ad1270e1_config_facade.py`: `field_definitions` (§7.13).
- `tests/test_ad1185_config_profiles.py::test_the_census_covers_every_default_off_flag` and `::test_the_measured_census_matches_the_manifest_header` (§7.14).
- `tests/test_config_reference_current.py` and the preflight `gen_config_reference.py --check` (§7.16).

**Not updated, still valid:**
- `test_ad472_channel_adapters.py:29-42`: defaults stay `[]`.
- `test_ad807_discord_refresh.py:41-67`: calls `_check_pairing` directly.
- `test_ad804_slack.py:143-179`: the same.
- `test_discord_adapter.py`: config only.
- `test_ad1248_slice_b.py:189-190`: reads `DmReply` in base, which is unchanged.

**Focused gate (Builder, `-n 0`):** the new file plus every file above, plus `tests/test_ad472_channel_adapters.py`, `tests/test_discord_adapter.py` and `tests/test_ad1248_slice_b.py`. Then run `scripts/check_config_facade.py --check`, `scripts/check_config_profiles.py` and `scripts/gen_config_reference.py --check`.

## 7. The contract

### 7.1 `src/probos/config_models/experience.py` (M1)

SEARCH (occurs once):
```python
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
```
REPLACE:
```python
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # BF-914: the users answered; empty = no one unless allow_all_users
    allow_all_users: bool = False            # BF-914: admit every Discord sender, slash commands included (explicit opt-in)
    command_prefix: str = "!"                # "!status" -> "/status"
```

SEARCH (occurs once):
```python
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    default_thread_ts: bool = True
```
REPLACE:
```python
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []         # BF-914: the users answered; empty = no one unless allow_all_users
    allow_all_users: bool = False            # BF-914: admit every Slack sender, slash commands included (explicit opt-in)
    default_thread_ts: bool = True
```

### 7.2 `src/probos/channels/base.py` (M1)

SEARCH (occurs once):
```python
import asyncio
import logging
from abc import ABC, abstractmethod
```
REPLACE:
```python
import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Collection
```

SEARCH (occurs once):
```python
_PAIRED_DM_REFUSED = (
    "Your message was not delivered: your visit does not allow direct "
    "messages ({reason}) (BF-903)."
)
```
REPLACE:
```python
_PAIRED_DM_REFUSED = (
    "Your message was not delivered: your visit does not allow direct "
    "messages ({reason}) (BF-903)."
)

#: BF-914 (#1621): how many distinct refused senders one adapter names in the
#: log. Each is named once; past the cap one more line says the rest go
#: unnamed, so a flood of throwaway accounts can grow neither memory nor the log.
_REFUSED_SENDER_LOG_CAP = 256
```

SEARCH (occurs once):
```python
        self._conversation_histories: dict[str, list[tuple[str, str]]] = {}
        self._max_history: int = 10
```
REPLACE:
```python
        self._conversation_histories: dict[str, list[tuple[str, str]]] = {}
        self._max_history: int = 10
        # BF-914 (#1621): senders the user allow-list refused, each logged once.
        self._refused_senders: set[str] = set()
        self._refused_senders_capped = False
```

SEARCH (occurs once):
```python
    async def _check_pairing(self, message: ChannelMessage) -> bool:
        """AD-802a: gate inbound messages from unknown senders behind a
        pairing code.
```
REPLACE:
```python
    def _sender_admitted(
        self, user_id: str, allowed_user_ids: Collection[object], *, allow_all_users: bool,
    ) -> bool:
        """BF-914 (#1621): the adapter's user allow-list, failing closed.

        A sender is admitted when ``allow_all_users`` is on or its id is in
        ``allowed_user_ids``. An empty list with the opt-in off admits no one.
        Before BF-914 an empty list meant "everyone", and with no pairing
        service wired that let any sender reach ``handle_message`` and, through
        it, the ship's slash commands. Ids compare as strings, so Discord's
        integer ids and Slack's string ids share one rule. A refused sender is
        logged once, without the message text (`_log_refused_sender`).
        """
        if allow_all_users or user_id in {str(allowed) for allowed in allowed_user_ids}:
            return True
        self._log_refused_sender(user_id)
        return False

    def _log_refused_sender(self, user_id: str) -> None:
        """BF-914 (#1621): one WARNING per refused sender, for at most `_REFUSED_SENDER_LOG_CAP` senders.

        No ``await`` separates the check from the record, so two overlapping
        refusals of one sender on the event loop still log once.
        """
        if user_id in self._refused_senders:
            return
        if len(self._refused_senders) >= _REFUSED_SENDER_LOG_CAP:
            if not self._refused_senders_capped:
                self._refused_senders_capped = True
                logger.warning(
                    "BF-914: channel %s has refused %d distinct senders; further refused "
                    "senders are not logged by id",
                    self.channel_name, _REFUSED_SENDER_LOG_CAP,
                )
            return
        self._refused_senders.add(user_id)
        logger.warning(
            "BF-914: refused a message from sender %r on channel %s: the sender is not in "
            "allowed_user_ids and allow_all_users is off. Later messages from this sender "
            "are refused without a log line.",
            user_id, self.channel_name,
        )

    def _warn_sender_policy(
        self, section: str, allowed_user_ids: Collection[object], *, allow_all_users: bool,
    ) -> None:
        """BF-914 (#1621): at start, say so when this adapter will admit no one, or everyone."""
        if allow_all_users:
            logger.warning(
                "BF-914: channels.%s.allow_all_users is on, so every sender who can reach "
                "this adapter is admitted, including to the ship's slash commands. List the "
                "senders in channels.%s.allowed_user_ids and turn allow_all_users off unless "
                "that is intended.",
                section, section,
            )
        elif not allowed_user_ids:
            logger.warning(
                "BF-914: channels.%s.allowed_user_ids is empty, so this adapter refuses every "
                "sender. List the user ids that may use the ship there, or set "
                "channels.%s.allow_all_users: true to admit everyone.",
                section, section,
            )

    async def _check_pairing(self, message: ChannelMessage) -> bool:
        """AD-802a: gate inbound messages from unknown senders behind a
        pairing code.
```

### 7.3 `src/probos/channels/discord_adapter.py` (M1)

SEARCH (occurs once):
```python
        allowed_channel_ids: list of channel IDs to listen on (empty = all)
        command_prefix: prefix for ProbOS slash commands (default: "!")
```
REPLACE:
```python
        allowed_channel_ids: list of channel IDs to listen on (empty = all)
        allowed_user_ids: the users it answers (BF-914: empty = no one)
        allow_all_users: answer every user, slash commands included (default off)
        command_prefix: prefix for ProbOS slash commands (default: "!")
```

SEARCH (occurs once):
```python
                "in config or PROBOS_DISCORD_TOKEN environment variable."
            )
            return

        intents = discord.Intents.default()
```
REPLACE:
```python
                "in config or PROBOS_DISCORD_TOKEN environment variable."
            )
            return

        # BF-914 (#1621): say so at start when this adapter will admit no one, or everyone.
        self._warn_sender_policy("discord", self.discord_config.allowed_user_ids, allow_all_users=self.discord_config.allow_all_users)

        intents = discord.Intents.default()
```

SEARCH (occurs once):
```python
            # User filter — only respond to allowed users
            if (
                self.discord_config.allowed_user_ids
                and message.author.id
                not in self.discord_config.allowed_user_ids
            ):
                return
```
REPLACE:
```python
            # User filter -- BF-914 (#1621): an empty allow-list admits no one unless allow_all_users is on
            if not self._sender_admitted(str(message.author.id), self.discord_config.allowed_user_ids, allow_all_users=self.discord_config.allow_all_users):
                return
```

### 7.4 `src/probos/channels/slack_adapter.py` (M1)

SEARCH (occurs once):
```python
        if not token:
            logger.warning("AD-472: SlackAdapter has no bot_token; refusing to start")
            return
```
REPLACE:
```python
        if not token:
            logger.warning("AD-472: SlackAdapter has no bot_token; refusing to start")
            return

        # BF-914 (#1621): say so at start when this adapter will admit no one, or everyone.
        self._warn_sender_policy("slack", self._slack_config.allowed_user_ids, allow_all_users=self._slack_config.allow_all_users)
```

SEARCH (occurs once):
```python
        if cfg.allowed_user_ids and user_id not in cfg.allowed_user_ids:
            return ""
```
REPLACE:
```python
        # BF-914 (#1621): an empty allow-list admits no one unless allow_all_users is on.
        if not self._sender_admitted(user_id, cfg.allowed_user_ids, allow_all_users=cfg.allow_all_users):
            return ""
```

SEARCH (occurs once):
```python
        if cfg.allowed_user_ids and user not in cfg.allowed_user_ids:
            return None
```
REPLACE:
```python
        # BF-914 (#1621): an empty allow-list admits no one unless allow_all_users is on.
        if not self._sender_admitted(user, cfg.allowed_user_ids, allow_all_users=cfg.allow_all_users):
            return None
```

### 7.5 `src/probos/doctor/checks/channel_discord_check.py` (M1)

SEARCH (occurs once):
```python
call — discord.py opens a websocket on start that's too heavy for
``probos doctor``; we just verify config sanity).
"""
```
REPLACE:
```python
call — discord.py opens a websocket on start that's too heavy for
``probos doctor``; we just verify config sanity).
BF-914 (#1621): WARN when ``allow_all_users`` is on (every sender is
admitted, slash commands included) or the user allow-list is empty (the
bot refuses every sender).
"""
```

SEARCH (occurs once):
```python
        allowed_channels = getattr(discord_cfg, "allowed_channel_ids", []) or []
        allowed_users = getattr(discord_cfg, "allowed_user_ids", []) or []
        return CheckResult(
```
REPLACE:
```python
        allowed_channels = getattr(discord_cfg, "allowed_channel_ids", []) or []
        allowed_users = getattr(discord_cfg, "allowed_user_ids", []) or []
        # BF-914 (#1621): who the bot will answer.
        if getattr(discord_cfg, "allow_all_users", False):
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=(
                    "Channel discord: allow_all_users is on, so every sender who can reach "
                    "the bot is admitted, including to the ship's slash commands (BF-914)"
                ),
                remediation=(
                    "List your own Discord user id in channels.discord.allowed_user_ids and "
                    "set channels.discord.allow_all_users: false."
                ),
            )
        if not allowed_users:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Channel discord: allowed_user_ids is empty, so the bot refuses every sender (BF-914)",
                remediation=(
                    "Set channels.discord.allowed_user_ids to the Discord user ids that may "
                    "use the ship, your own first."
                ),
            )
        return CheckResult(
```

### 7.6 `docs/architecture/experience.md` (M1)

SEARCH (occurs once):
```markdown
Channel adapters connect the crew to Discord, Slack, Telegram, Matrix, Microsoft Teams, Gmail and generic webhooks. Inbound direct messages from a new user require a pairing that the operator approves with `probos pairing approve`, and `probos channel <telegram|slack|matrix> setup` stores a channel's credentials.
```
REPLACE:
```markdown
Channel adapters connect the crew to Discord, Slack, Telegram, Matrix, Microsoft Teams, Gmail and generic webhooks. Discord and Slack answer only the senders listed in the adapter's `allowed_user_ids`: an empty list answers no one, and `allow_all_users: true` answers everyone, the ship's slash commands included (BF-914). The pairing gate (`probos pairing approve`) applies only when a pairing service is wired, which a standard boot does not yet do, and `probos channel <telegram|slack|matrix> setup` stores a channel's credentials.
```

### 7.7 `tests/test_ad807_discord_refresh.py` (M1: the harness's sender must be listed)

SEARCH (occurs once):
```python
    monkeypatch.setitem(sys.modules, "discord", ModuleType("discord"))
    adapter = DiscordAdapter(runtime, DiscordConfig(enabled=True, token="dummy"))
```
REPLACE:
```python
    monkeypatch.setitem(sys.modules, "discord", ModuleType("discord"))
    # BF-914 (#1621): an empty user list now refuses every sender, so the
    # sender these tests drive (42) is listed to reach the gate and the turn.
    adapter = DiscordAdapter(runtime, DiscordConfig(enabled=True, token="dummy", allowed_user_ids=[42]))
```

### 7.8 `tests/test_ad804_slack.py` (M1: four pins)

SEARCH (occurs once):
```python
def test_convert_message_returns_message_for_user_text():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
```
REPLACE:
```python
def test_convert_message_returns_message_for_user_text():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U42"])  # BF-914: listed
```

SEARCH (occurs once):
```python
def test_convert_message_drops_bot_subtype():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
```
REPLACE:
```python
def test_convert_message_drops_bot_subtype():
    # BF-914: U1 is listed, so each None below is the subtype/bot filter, not the allow-list.
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U1"])
```

SEARCH (occurs once):
```python
    """Messages from our own bot user are filtered out."""
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
```
REPLACE:
```python
    """Messages from our own bot user are filtered out."""
    # BF-914: both are listed, so U_BOT is dropped by the self filter, not the allow-list.
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U_BOT", "U_HUMAN"])
```

SEARCH (occurs once):
```python
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_channel_ids=["C_ALLOWED"])
```
REPLACE:
```python
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_channel_ids=["C_ALLOWED"], allowed_user_ids=["U1"])  # BF-914
```

### 7.9 `tests/test_bf804_pairing_notification.py` (M1)

SEARCH (occurs once):
```python
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True}))
```
REPLACE:
```python
    # BF-914 (#1621): U42 is listed so both halves reach the pairing gate, not the allow-list.
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U42"])
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True}))
```

### 7.10 `tests/test_bf903_channel_and_mcp.py` (M1)

SEARCH (occurs once):
```python
        slack = SlackAdapter(rig.runtime, SlackConfig(enabled=True, bot_token="xoxb-test"), client=client)
```
REPLACE:
```python
        # BF-914 (#1621): U42 is listed so the refusal below is the unreadable pairing store's.
        slack = SlackAdapter(rig.runtime, SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U42"]), client=client)
```

### 7.11 `tests/test_ad1270e2c_experience_models.py` (M1: EXPECTED_DUMPS)

SEARCH (occurs once):
```python
                         'allowed_user_ids': [],
                         'command_prefix': '!',
```
REPLACE:
```python
                         'allowed_user_ids': [],
                         # BF-914 (#1621): the explicit opt-in to admit every sender (off).
                         'allow_all_users': False,
                         'command_prefix': '!',
```

SEARCH (occurs once):
```python
                       'allowed_user_ids': [],
                       'default_thread_ts': True,
```
REPLACE:
```python
                       'allowed_user_ids': [],
                       # BF-914 (#1621): the explicit opt-in to admit every sender (off).
                       'allow_all_users': False,
                       'default_thread_ts': True,
```

### 7.12 `tests/test_ad1152_agentic_correlation.py` (M1: the golden pops the new fields)

SEARCH (occurs once):
```python
    # BF-875's inert (empty) MCP server token and allowlist were added after this capture too.
    assert config["federation"]["mcp_server"].pop("auth_token") == ""
    assert config["federation"]["mcp_server"].pop("exposed_intents") == []
```
REPLACE:
```python
    # BF-875's inert (empty) MCP server token and allowlist were added after this capture too.
    assert config["federation"]["mcp_server"].pop("auth_token") == ""
    assert config["federation"]["mcp_server"].pop("exposed_intents") == []
    # BF-914's channel opt-ins (admit every sender; off) were added after this capture too; this
    # agentic-loop observation starts no channel adapter.
    assert config["channels"]["discord"].pop("allow_all_users") is False
    assert config["channels"]["slack"].pop("allow_all_users") is False
```

### 7.13 `tests/test_ad1270e1_config_facade.py` (M1: a counter pair)

This is a count, not text. If the base's number differs when you build (another item added fields first), the REPLACE number is the base's value plus 2, and the comment chain gains this line. The arbiter is `--check` on the regenerated baseline (§7.15).

SEARCH (occurs once on `ba20e949`):
```python
    # AD-1347 S1 adds AgentWorkConfig's seven fields and SystemConfig.agent_work (1869 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1347 S1 adds AgentWorkConfig's seven fields and SystemConfig.agent_work (1869 -> 1877).
    # BF-914 adds channels.discord.allow_all_users and channels.slack.allow_all_users (1877 -> 1879).
    assert counts["field_definitions"] == 1879  # AD-1206 intentionally adds github_repository.
```

### 7.14 `docs/development/config-profiles.yaml` (M1: classify the two flags, and count them)

Pair 1 of 2 (the classification). It is anchored on a row no queue item edits; the path line occurs once (`:426`).

SEARCH:
```yaml
- path: avatar_telemetry.inject_into_agent_context
  kind: consent-gate
```
REPLACE:
```yaml
- path: channels.discord.allow_all_users
  kind: consent-gate
  profiles: []
  evidence_to_promote: Not promotable. Arming it admits every Discord sender who can reach the
    bot, the ship's slash commands included (BF-914, issue 1621). That is the Captain's decision,
    not a test result; tests/test_bf914_channel_allow_lists.py proves the flag admits when on
    and that an empty allowed_user_ids refuses every sender when off.
  external_dependency: null
  requires: []
  conflicts_with: []
- path: channels.slack.allow_all_users
  kind: consent-gate
  profiles: []
  evidence_to_promote: Not promotable. Arming it admits every Slack sender the adapter polls or
    receives, the ship's slash commands included (BF-914, issue 1621). A consent decision; the same
    test file proves both directions.
  external_dependency: null
  requires: []
  conflicts_with: []
- path: avatar_telemetry.inject_into_agent_context
  kind: consent-gate
```

Pair 2 of 2 is a counter: `default_false` equals the checker's count (`test_ad1185_config_profiles.py:859`). It is the base's value plus 2. On `ba20e949` it is 224 (`:20`). The other header numbers are unpinned and left alone, as in the AD-1347 S1 precedent.

SEARCH (occurs once on `ba20e949`):
```yaml
  boolean_fields_reachable: 445
  default_false: 224
  default_true: 225
```
REPLACE:
```yaml
  boolean_fields_reachable: 445
  default_false: 226
  default_true: 225
```

### 7.15 `docs/development/config-facade-baseline.yaml` (M1: generated, then checked)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline`, then `--check`. `git diff` on the file must show only:
1. `surface_counts.field_definitions` +2 (1877 → 1879 on `ba20e949`). Also the tool-computed `canonical_dump_leaves` and `canonical_dump_sha256`, if they move. Report their values; they are not hand-checked.
2. `DiscordConfig`: its `schema_sha256`, and one row `- {default: 'False', name: allow_all_users}` immediately after `- {default: '[]', name: allowed_user_ids}`.
3. `SlackConfig`: the same, after its `allowed_user_ids` row.
4. `ChannelsConfig` and `SystemConfig`: their `schema_sha256` only.

Anything else is a hard stop.

### 7.16 `docs/development/config-reference.md` (M1: generated, then checked)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py`, then the same with `--check`. Expected: two inserted rows, `allow_all_users | bool | False`, each after its section's `allowed_user_ids` row (`:1212`, `:1227` today). No deletions.

### 7.17 New file: `tests/test_bf914_channel_allow_lists.py` (M1)

```python
"""BF-914 (#1621): a channel adapter's user allow-list fails closed.

An empty ``allowed_user_ids`` used to mean "everyone", and with no pairing
service wired every admitted sender's slash text reached the ship's shell.
These tests drive the REAL filters -- Discord's ``on_message`` closure, Slack's
poll and webhook entry points -- over fake transports, and record what reaches
``probos.api._handle_slash_command`` instead of running it. Every refusal test
carries a control on the same harness that shows a delivery is observable, so a
harness that never delivered cannot pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from types import ModuleType
from typing import Any

import pytest
from httpx import AsyncClient as _AsyncClient
from httpx import MockTransport as _MockTransport
from httpx import Request as _Request
from httpx import Response as _Response

from probos.channels.discord_adapter import DiscordAdapter
from probos.channels.slack_adapter import SlackAdapter
from probos.channels.slack_client import SlackClient
from probos.config import DiscordConfig, SlackConfig
from probos.doctor.checks.channel_discord_check import _ChannelDiscordCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.experience.shell import ProbOSShell

_BASE_LOGGER = "probos.channels.base"
_REFUSAL = "BF-914: refused a message from sender"
_SECRET = "SECRET-TEXT-914"


class _Runtime:
    """The runtime members the base ``handle_message`` and Slack's emitters reach."""

    def __init__(self) -> None:
        self.pairing_service = None  # the production state: no pairing service is wired
        self.processed: list[str] = []

    def emit_event(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def process_natural_language(self, text: str, **_kwargs: Any) -> dict[str, Any]:
        self.processed.append(text)
        return {"response": "all systems nominal"}


@pytest.fixture
def shell_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every text that reaches the ship's shell dispatcher; run none of them."""
    calls: list[str] = []

    async def _record(text: str, _runtime: Any) -> dict[str, Any]:
        calls.append(text)
        return {"response": "recorded"}

    monkeypatch.setattr("probos.api._handle_slash_command", _record)
    return calls


# --- Discord: the real on_message closure over a fake bot ------------------------------------


class _Typing:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _Channel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.posted: list[str] = []

    def typing(self) -> _Typing:
        return _Typing()

    async def send(self, content: str) -> None:
        self.posted.append(content)


class _BotUser:
    id = 1
    name = "probos"
    bot = True


class _Bot:
    """The slice of the discord client that the event handlers and ``send_response`` touch."""

    def __init__(self, channel: _Channel) -> None:
        self.user = _BotUser()
        self.handlers: dict[str, Any] = {}
        self._channels = {channel.id: channel}

    def event(self, fn: Any) -> Any:
        self.handlers[fn.__name__] = fn
        return fn

    def get_channel(self, channel_id: int) -> _Channel | None:
        return self._channels.get(channel_id)


class _Author:
    def __init__(self, author_id: int) -> None:
        self.id = author_id
        self.bot = False
        self.display_name = f"sender-{author_id}"


class _Message:
    def __init__(self, channel: _Channel, author_id: int, content: str) -> None:
        self.channel = channel
        self.author = _Author(author_id)
        self.content = content


def _discord(
    monkeypatch: pytest.MonkeyPatch, config: DiscordConfig, runtime: _Runtime | None = None,
) -> tuple[Any, _Channel]:
    """Build the REAL ``on_message`` closure; discord.py is not installed, so a bare module stands in."""
    monkeypatch.setitem(sys.modules, "discord", ModuleType("discord"))
    adapter = DiscordAdapter(runtime or _Runtime(), config)
    channel = _Channel(4242)
    adapter._bot = _Bot(channel)
    adapter._setup_event_handlers()
    return adapter._bot.handlers["on_message"], channel


async def test_discord_an_unlisted_sender_never_reaches_the_shell(
    monkeypatch: pytest.MonkeyPatch, shell_calls: list[str],
) -> None:
    """N1, #1621's acceptance: the real filter and a fake transport; an unlisted user's text is not passed on."""
    assert "/prune" in ProbOSShell.COMMANDS, "premise: /prune is a shell command a sender could reach"
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t", allowed_user_ids=[7]))

    await on_message(_Message(channel, 7, "!prune agent-1"))
    assert shell_calls == ["/prune agent-1"], "control: a listed sender reaches the shell, so a delivery is observable"
    assert channel.posted == ["recorded"]

    await on_message(_Message(channel, 42, "!prune agent-2"))
    assert shell_calls == ["/prune agent-1"], "an unlisted sender's command must not reach the shell"
    assert channel.posted == ["recorded"], "and the unlisted sender is told nothing"


async def test_discord_an_empty_allow_list_refuses_every_sender(
    monkeypatch: pytest.MonkeyPatch, shell_calls: list[str],
) -> None:
    """N2: the shipped shape (both lists empty) answers no one; the explicit opt-in answers everyone."""
    runtime = _Runtime()
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t"), runtime)
    for author in (7, 42):
        await on_message(_Message(channel, author, "!prune agent-1"))
        await on_message(_Message(channel, author, "status report"))
    assert shell_calls == []
    assert runtime.processed == []
    assert channel.posted == []

    # Control on the same harness: the opt-in admits the same sender to both paths.
    opened_runtime = _Runtime()
    opened, opened_channel = _discord(
        monkeypatch, DiscordConfig(enabled=True, token="t", allow_all_users=True), opened_runtime,
    )
    await opened(_Message(opened_channel, 42, "!prune agent-1"))
    await opened(_Message(opened_channel, 42, "status report"))
    assert shell_calls == ["/prune agent-1"]
    assert opened_runtime.processed == ["status report"]
    assert opened_channel.posted == ["recorded", "all systems nominal"]


async def test_a_refused_sender_is_logged_once_without_its_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, shell_calls: list[str],
) -> None:
    """N3: two overlapping refusals of one sender and a third log one line; a second sender gets its own."""
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t", allowed_user_ids=[7]))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await asyncio.gather(
            on_message(_Message(channel, 42, f"!prune {_SECRET}")),
            on_message(_Message(channel, 42, f"!prune {_SECRET}")),
        )
        await on_message(_Message(channel, 42, f"status {_SECRET}"))
        await on_message(_Message(channel, 43, f"status {_SECRET}"))
    refusals = [r.getMessage() for r in caplog.records if _REFUSAL in r.getMessage()]
    assert len(refusals) == 2, refusals
    assert "'42'" in refusals[0]
    assert "'43'" in refusals[1]
    assert not any(_SECRET in r.getMessage() for r in caplog.records), "a refusal must not log the message text"
    assert shell_calls == []
    assert channel.posted == []


def test_the_refusal_log_is_bounded(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """N4: past the cap, one line says further senders go unnamed, and nothing more is logged."""
    monkeypatch.setattr("probos.channels.base._REFUSED_SENDER_LOG_CAP", 2)
    adapter = SlackAdapter(_Runtime(), SlackConfig(enabled=True, bot_token="xoxb-test"))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        admitted = [
            adapter._sender_admitted(user, [], allow_all_users=False)
            for user in ("U1", "U2", "U3", "U4", "U1")
        ]
    assert admitted == [False] * 5
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    assert len([line for line in lines if _REFUSAL in line]) == 2
    assert len([line for line in lines if "not logged by id" in line]) == 1
    assert len(lines) == 3


# --- Slack: the real adapter over a fake Web API -----------------------------------------------


class _SlackApi:
    """A fake Slack Web API: identity, no member channels, a fixed history, recorded posts."""

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.posted: list[str] = []

    def __call__(self, request: _Request) -> _Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "auth.test":
            return _Response(200, json={"ok": True, "user_id": "U_BOT", "team": "T1"})
        if method == "conversations.list":
            return _Response(200, json={"ok": True, "channels": []})
        if method == "conversations.history":
            return _Response(200, json={"ok": True, "messages": self.history})
        if method == "chat.postMessage":
            self.posted.append(json.loads(request.content)["text"])
            return _Response(200, json={"ok": True, "ts": "9.0"})
        return _Response(200, json={"ok": False, "error": f"unexpected {method}"})


@pytest.fixture
async def slack_api() -> AsyncIterator[tuple[_SlackApi, SlackClient]]:
    api = _SlackApi()
    async with _AsyncClient(transport=_MockTransport(api)) as http:
        yield api, SlackClient(bot_token="xoxb-test", http=http)


async def test_slack_poll_refuses_an_unlisted_sender_before_the_shell(
    slack_api: tuple[_SlackApi, SlackClient], shell_calls: list[str],
) -> None:
    """N5: the real poll path; only the listed sender reaches the shell and is answered."""
    api, client = slack_api
    api.history = [  # Slack answers newest first
        {"user": "U_OUT", "text": f"/prune agent-2 {_SECRET}", "ts": "2.0"},
        {"user": "U_IN", "text": "/prune agent-1", "ts": "1.0"},
    ]
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U_IN"])
    adapter = SlackAdapter(_Runtime(), config, client=client)
    await adapter._process_channel("C1")
    assert shell_calls == ["/prune agent-1"], "control: the listed sender was delivered; the unlisted one was not"
    assert api.posted == ["recorded"]


async def test_slack_receive_refuses_on_an_empty_list_and_admits_with_the_opt_in(
    slack_api: tuple[_SlackApi, SlackClient], shell_calls: list[str],
) -> None:
    """N6: the webhook entry point, both directions, on one client."""
    _api, client = slack_api
    closed = SlackAdapter(_Runtime(), SlackConfig(enabled=True, bot_token="xoxb-test"), client=client)
    assert await closed.receive(text="/prune agent-1", channel_id="C1", user_id="U_ANY") == ""
    assert shell_calls == []
    opened_config = SlackConfig(enabled=True, bot_token="xoxb-test", allow_all_users=True)
    opened = SlackAdapter(_Runtime(), opened_config, client=client)
    assert await opened.receive(text="/prune agent-1", channel_id="C1", user_id="U_ANY") == "recorded"
    assert shell_calls == ["/prune agent-1"], "control: the same entry point delivers once the opt-in is on"


@pytest.mark.parametrize(
    ("allowed", "allow_all", "user", "admitted"),
    [
        ([], False, "U1", False),
        (["U1"], False, "U1", True),
        (["U1"], False, "U2", False),
        ([], True, "U2", True),
        (["U1"], True, "U2", True),
    ],
)
def test_slack_convert_message_applies_the_rule(
    allowed: list[str], allow_all: bool, user: str, admitted: bool,
) -> None:
    """N7: the boundary table of the one rule, on the real poll filter."""
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=allowed, allow_all_users=allow_all)
    adapter = SlackAdapter(_Runtime(), config)
    converted = adapter._convert_message("C1", {"user": user, "text": "hi", "ts": "1.0"})
    assert (converted is not None) is admitted


@pytest.mark.parametrize(
    ("allowed", "allow_all", "expected"),
    [
        ([], False, "channels.slack.allowed_user_ids is empty, so this adapter refuses every sender"),
        (["U1"], False, None),
        ([], True, "channels.slack.allow_all_users is on"),
    ],
)
async def test_slack_start_states_who_it_admits(
    slack_api: tuple[_SlackApi, SlackClient], caplog: pytest.LogCaptureFixture,
    allowed: list[str], allow_all: bool, expected: str | None,
) -> None:
    """N8: the start warning names an adapter that will admit no one, or everyone, and is silent otherwise."""
    _api, client = slack_api
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=allowed, allow_all_users=allow_all)
    adapter = SlackAdapter(_Runtime(), config, client=client)
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await adapter.start()
    assert adapter._started is True, "control: start ran to the end"
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    if expected is None:
        assert lines == []
    else:
        assert len(lines) == 1
        assert expected in lines[0]


class _StubIntents:
    message_content = False

    @classmethod
    def default(cls) -> _StubIntents:
        return cls()


class _StubClient:
    def __init__(self, *, intents: _StubIntents) -> None:
        self.intents = intents
        self.handlers: dict[str, Any] = {}

    def event(self, fn: Any) -> Any:
        self.handlers[fn.__name__] = fn
        return fn

    async def start(self, _token: str) -> None:
        return None


async def test_discord_start_warns_when_it_admits_no_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """N9: the Discord start path, through a stub discord module (discord.py is not installed here)."""
    stub = ModuleType("discord")
    stub.Intents = _StubIntents  # type: ignore[attr-defined]
    stub.Client = _StubClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "discord", stub)
    adapter = DiscordAdapter(_Runtime(), DiscordConfig(enabled=True, token="t"))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await adapter.start()
        assert adapter._bot_task is not None
        await adapter._bot_task
    assert adapter._started is True, "control: start ran to the end"
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    assert len(lines) == 1
    assert "channels.discord.allowed_user_ids is empty, so this adapter refuses every sender" in lines[0]


# --- The doctor and the defaults ----------------------------------------------------------------


class _Channels:
    def __init__(self, discord: DiscordConfig) -> None:
        self.discord = discord


class _Config:
    def __init__(self, discord: DiscordConfig) -> None:
        self.channels = _Channels(discord)


@pytest.mark.parametrize(
    ("allowed", "allow_all", "outcome", "phrase"),
    [
        ([789], False, CheckOutcome.OK, "1 user allow-list"),
        ([], False, CheckOutcome.WARN, "refuses every sender"),
        ([], True, CheckOutcome.WARN, "every sender who can reach the bot is admitted"),
        ([789], True, CheckOutcome.WARN, "every sender who can reach the bot is admitted"),
    ],
)
async def test_doctor_channel_discord_judges_the_user_allow_list(
    tmp_path: Any, allowed: list[int], allow_all: bool, outcome: CheckOutcome, phrase: str,
) -> None:
    """N10, #1621's acceptance: the doctor names an empty allow-list and an open adapter."""
    discord = DiscordConfig(enabled=True, token="t", allowed_user_ids=allowed, allow_all_users=allow_all)
    ctx = DoctorContext(config=_Config(discord), home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelDiscordCheck().run(ctx)
    assert result.outcome is outcome
    assert phrase in result.message
    if outcome is CheckOutcome.WARN:
        assert "channels.discord" in result.remediation


@pytest.mark.parametrize("model", [DiscordConfig, SlackConfig])
def test_the_opt_in_is_off_by_default_and_a_copy_of_todays_block_keeps_it_off(model: Any) -> None:
    """N11: config/system.yaml's channel blocks name no opt-in, so a copy of them admits no one."""
    shipped = {"enabled": True, "allowed_channel_ids": [], "allowed_user_ids": []}
    assert model().allow_all_users is False
    assert model(**shipped).allow_all_users is False
```

## 8. Tracking

Each pair anchors on a line that occurs once, and that other queue items' entries do not change. They insert beside the anchor, not into it. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title line):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-914 (2026-10-23), closes #1621 -- a channel adapter's empty user allow-list admits no one, and admitting everyone is an explicit opt-in.** With no pairing service wired, Discord's and Slack's "empty = everyone" user lists let any sender reach `handle_message` and the ship's slash commands; the shipped config enables Discord with both lists empty (latent: no `discord.py`, no token). `DiscordConfig` and `SlackConfig` gain `allow_all_users` (default off). `ChannelAdapter._sender_admitted` admits a sender only when the opt-in is on or its id is listed (ids compare as strings), and is called at Discord's `on_message` and Slack's `receive` and `_convert_message`; a refusal is logged once per sender without the text, for at most 256 senders. Both adapters warn at start when they will admit no one or everyone, and `probos doctor` WARNs for an enabled Discord adapter whose list is empty or whose opt-in is on. `config/system.yaml` is unchanged; `docs/architecture/experience.md` no longer says pairing gates every new sender. New: `tests/test_bf914_channel_allow_lists.py` (real filters, fake transports, a recorder in place of the shell). Updated pins: `test_ad807_discord_refresh.py`, `test_ad804_slack.py`, `test_bf804_pairing_notification.py`, `test_bf903_channel_and_mcp.py`, `test_ad1270e2c_experience_models.py`, `test_ad1152_agentic_correlation.py`, `test_ad1270e1_config_facade.py`, plus the facade baseline, `config-profiles.yaml` and `config-reference.md`. The contract is `prompts/bf-914-channel-allow-lists-fail-closed.md`.
```

**`DECISIONS.md`** (inserted before this heading, which other entries also insert before):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-914 -- A channel adapter's empty user allow-list admits no one; admitting everyone is an explicit opt-in (2026-10-23, #1621)

- *Scope.* `config_models/experience.py` (`allow_all_users` on `DiscordConfig` and `SlackConfig`), `channels/base.py` (`_sender_admitted`, `_log_refused_sender`, `_warn_sender_policy`), the user filters and `start` of `discord_adapter.py` and `slack_adapter.py`, `doctor/checks/channel_discord_check.py`, one sentence of `docs/architecture/experience.md`. Tests: new `tests/test_bf914_channel_allow_lists.py`; pins per the contract. Contract: `prompts/bf-914-channel-allow-lists-fail-closed.md`. Tier HIGH.
- *D0 (decided by the Architect under Delegated AD Execution Mode).* In the envelope: it strengthens a control; "empty = everyone" was labelled a security risk, not promised; `allow_all_users: true` restores the old behaviour exactly, and the start warning, the doctor WARN and the refusal log say what changed; no shipped config changes; rollback is a revert.
- *D1/D2 (fail closed, one rule).* The rule lives once on `ChannelAdapter` and is called at each adapter's existing filter, where the sender's own id is known. A gate in `handle_message` was rejected: Telegram and Matrix rely on pairing alone and the webhook's user id is caller-asserted, so a base default would either keep the exposure or break them.
- *D3 (scope).* Discord and Slack, the only adapters a boot builds from shipped config. Gmail and Teams have the same "empty = all" shape but no production constructor; recorded for the AD that wires them.
- *D4 (no FAIL).* The doctor WARNs (an inert adapter and a deliberate opt-in are both valid). A refused sender is logged once, without the text, for at most 256 senders.
- *D5 (deferred).* Refusing admin slash commands to channel senders needs a caller identity in `execute_command` and a declared admin-command set: the pairing-wiring AD's requirement (#1621 Acceptance).
- *Disclosed effects.* An enabled Discord or Slack adapter with an empty `allowed_user_ids` now answers no one; it logs one WARNING at start and one per refused sender.
- *Reversal.* Revert the commit, or set `allow_all_users: true` on an adapter (the old behaviour).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. Commit the regenerated `open-ads-report.md` and `ad-ledger-snapshot.json`, and verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

**`docs/development/roadmap.md`:** no row. Its Bug Tracker lists only bugs filed and deliberately not fixed (`:1139`); BF-917 is the precedent.

## 9. What this does NOT change

- `config/system.yaml`, tracked or local. The Captain's required action stays as #1621 states it.
- `allowed_channel_ids` (empty = all channels), `mention_required`, `command_prefix`.
- `_check_pairing`, BF-903's paired-sender handling, `handle_message`, `api.py`, `shell.py`, `routers/chat.py`.
- Webhook (`allowed_channels`, `shared_secret`), Gmail (`allowed_senders`), Teams (`allowed_user_aads`), Telegram, Matrix (register).
- The Slack doctor check, which reads `~/.probos/channels/slack.yaml`, not the boot's config (register). Outbound delivery (`task_scheduler`, scout reports).

## 10. Mutation rows

Tier HIGH. Run every row against `tests/test_bf914_channel_allow_lists.py` after an unmutated baseline passes, restoring the file between rows:
`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf914_channel_allow_lists.py -q -n 0`.
Each Line cell occurs exactly once in its file after §7, as a whole stripped line and as a substring.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | `src/probos/channels/base.py` | `if allow_all_users or user_id in {str(allowed) for allowed in allowed_user_ids}:` | `if True:` | N1; N2; N7 |
| R2 | `src/probos/channels/base.py` | `if allow_all_users or user_id in {str(allowed) for allowed in allowed_user_ids}:` | `if allow_all_users:` | N1 (listed sender refused); N7 |
| R3 | `src/probos/channels/base.py` | `if allow_all_users or user_id in {str(allowed) for allowed in allowed_user_ids}:` | `if user_id in {str(allowed) for allowed in allowed_user_ids}:` | N2 control; N6; N7 |
| R4 | `src/probos/channels/base.py` | `self._log_refused_sender(user_id)` | `pass` | N3; N4 |
| R5 | `src/probos/channels/base.py` | `if user_id in self._refused_senders:` | `if False:` | N3 (42 logged three times); N4 |
| R6 | `src/probos/channels/base.py` | `self._refused_senders.add(user_id)` | `pass` | N3 |
| R7 | `src/probos/channels/base.py` | `if len(self._refused_senders) >= _REFUSED_SENDER_LOG_CAP:` | `if False:` | N4 |
| R8 | `src/probos/channels/base.py` | `_REFUSED_SENDER_LOG_CAP = 256` | `_REFUSED_SENDER_LOG_CAP = 0` | N3 (no per-sender line) |
| R9 | `src/probos/channels/base.py` | `if not self._refused_senders_capped:` | `if True:` | N4 (two cap lines) |
| R10 | `src/probos/channels/base.py` | `if allow_all_users:` | `if False:` | N8 `[opt-in]` |
| R11 | `src/probos/channels/base.py` | `elif not allowed_user_ids:` | `elif False:` | N8 `[empty]`; N9 |
| R12 | `src/probos/channels/discord_adapter.py` | `if not self._sender_admitted(str(message.author.id), self.discord_config.allowed_user_ids, allow_all_users=self.discord_config.allow_all_users):` | `if False:` | N1; N2 |
| R13 | `src/probos/channels/discord_adapter.py` | `if not self._sender_admitted(str(message.author.id), self.discord_config.allowed_user_ids, allow_all_users=self.discord_config.allow_all_users):` | `if not self._sender_admitted(str(message.author.id), self.discord_config.allowed_user_ids, allow_all_users=True):` | N1; N2 |
| R14 | `src/probos/channels/discord_adapter.py` | `self._warn_sender_policy("discord", self.discord_config.allowed_user_ids, allow_all_users=self.discord_config.allow_all_users)` | `pass` | N9 |
| R15 | `src/probos/channels/slack_adapter.py` | `if not self._sender_admitted(user_id, cfg.allowed_user_ids, allow_all_users=cfg.allow_all_users):` | `if False:` | N6 |
| R16 | `src/probos/channels/slack_adapter.py` | `if not self._sender_admitted(user, cfg.allowed_user_ids, allow_all_users=cfg.allow_all_users):` | `if False:` | N5; N7 |
| R17 | `src/probos/channels/slack_adapter.py` | `self._warn_sender_policy("slack", self._slack_config.allowed_user_ids, allow_all_users=self._slack_config.allow_all_users)` | `pass` | N8 |
| R18 | `src/probos/config_models/experience.py` | `allow_all_users: bool = False            # BF-914: admit every Discord sender, slash commands included (explicit opt-in)` | `allow_all_users: bool = True            # BF-914: admit every Discord sender, slash commands included (explicit opt-in)` | N11; N2 |
| R19 | `src/probos/config_models/experience.py` | `allow_all_users: bool = False            # BF-914: admit every Slack sender, slash commands included (explicit opt-in)` | `allow_all_users: bool = True            # BF-914: admit every Slack sender, slash commands included (explicit opt-in)` | N11; N6 |
| R20 | `src/probos/doctor/checks/channel_discord_check.py` | `if getattr(discord_cfg, "allow_all_users", False):` | `if False:` | N10 `[opt-in]` cases |
| R21 | `src/probos/doctor/checks/channel_discord_check.py` | `if not allowed_users:` | `if False:` | N10 `[empty]` |

## 11. Verified Against Codebase (2026-10-23, `origin/main` `ba20e949`)

```
Read src/probos/channels/base.py:1-403   imports 5-11; logger 16; ChannelConfig 19-21; ChannelMessage 24-38 (user_id: str 29);
  _PAIRED_DM_REFUSED 83-86; ChannelAdapter 103; channel_name 116; __init__ 118-123; _check_pairing 142, getattr 198-200;
  handle_message 263-330 (pairing 284, slash -> _handle_slash_command 295-298, NL 310-319); _handle_paired 332
Grep "class \w+\(ChannelAdapter\)" src   discord 44, gmail 88, matrix 31, slack 46, teams 37, telegram 37, webhook 19
Grep "allowed_\w+" config_models/experience.py   392, 393, 660, 661, 806
Read config_models/experience.py:387-396 DiscordConfig; 647-667 SlackConfig; 801-806 WebhookConfig; imports 8-12
Read discord_adapter.py:44-113 (docstring 49-50; start token check 81-86; intents 88); 239-253 send_response; 273-321 on_message
  (channel filter 279-285; user filter 287-293; prefix 307-310; handle_message 321)
Grep discord_adapter.py "PROBOS_DISCORD_TOKEN environment variable|# User filter|command_prefix: prefix"   84, 287, 50 (once each)
Read slack_adapter.py:46-135 (start token check 79-82); 180-219 receive (192-193); 223-261 _convert_message (252-253); 263-299 _process_channel (offset 282-285)
Grep slack_adapter.py "allowed_user_ids"   192, 252
Read slack_client.py grep: _call 71-74 posts f"{base}/{method}"; auth_test 99; conversations_list 107; history 121; chat_post_message 141; close owns_http 158-160
Read webhook_adapter.py:1-105   start warning 34-38; receive 56-80 (secret 67, allowed_channels 70)
Read teams_adapter.py:76-117 (allowed_user_aads 89-94); gmail_adapter.py:308-316 (allowed_senders); telegram_config.py, matrix_config.py (no user allow-list)
Read __main__.py:824-872   Discord 826-840 (env token 829); Slack 843-855; Webhook 858-868
Read doctor/checks/channel_discord_check.py:1-63; doctor/protocol.py CheckOutcome 14-19, CheckResult 22-38, DoctorContext 41-59
Read api.py:45-87   _BLOCKED_COMMANDS 46; _handle_slash_command 74
Grep "_handle_slash_command" src   api.py:74, base.py:296-297, routers/chat.py:101-102
Grep experience/shell.py   class ProbOSShell 49; COMMANDS 63; "/prune" 101; execute_command 218
Read config/system.yaml:1133-1154   discord enabled true, lists [] (1134-1141); slack enabled false (1142-1152)
Read tests/test_ad807_discord_refresh.py:1-265   _wire_on_message 147-164 (DiscordConfig line 158); senders 42 (181, 216); doctor 223-264
Read tests/test_ad804_slack.py:1-217   pins 104-113, 116-121, 124-130, 133-137
Read tests/test_bf804_pairing_notification.py:395-446 (cfg 413); tests/test_bf903_channel_and_mcp.py:260-281 (279)
Read tests/test_ad1270e2c_experience_models.py:85-208 EXPECTED_DUMPS (Discord 118-124, Slack 176-185); 256-340 the three dump/identity tests
Read tests/test_ad1152_agentic_correlation.py:215-268   pops; BF-875 block 255-257
Read tests/test_ad1270e1_config_facade.py:1540-1557   field_definitions 1877 at 1554
Read docs/development/config-facade-baseline.yaml:44-56 (field_definitions 1877), 979-988 ChannelsConfig, 1451-1464 DiscordConfig
Read docs/development/config-profiles.yaml:14-23 (default_false 224), 52-126, 417-433 (consent-gate rows; 426 avatar_telemetry path once)
Read scripts/check_config_profiles.py:90-104 VALID_KINDS (consent-gate), 228-237, 715-730 (unclassified rule)
Read tests/test_ad1185_config_profiles.py:850-859
Read docs/architecture/experience.md:56-58
Grep "asyncio_mode|addopts" pyproject.toml   181 auto; 196 "-n 16 --dist=loadfile"
SEARCH uniqueness: each block's distinctive line was grep-counted once in its target file (results above);
  multi-line blocks contain at least one once-only line. Mutation Line cells: each is introduced once by §7 and is
  textually distinct from its sibling (R15 "user_id," vs R16 "user,"; R18 "Discord" vs R19 "Slack"; R10 "if allow_all_users:" vs R1 "if allow_all_users or").
```

## 12. Absence Verified (2026-10-23)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | Nothing assigns `runtime.pairing_service` | Grep `pairing_service\s*=\|\.pairing_service\b\|PairingService\(` and `["']pairing_service["']` in `src` | base.py:169,198 (doc, read); discord 61, slack 49 (comments); `__main__.py:1919` (doc), `:1970` (the offline CLI) | yes |
| AV2 | Gmail, Teams, Telegram and Matrix adapters are never constructed in `src` | Grep `(Discord\|Slack\|Webhook\|Teams\|Gmail\|Telegram\|Matrix)Adapter\(`; Grep `from probos\.channels\.(telegram\|matrix\|gmail\|teams)_adapter import`; Grep `teams_adapter\s*=` | `__main__.py:832,849,864` only; 0; 0 (`routers/teams_webhook.py:29` only reads it) | yes |
| AV3 | No route calls `WebhookAdapter.receive` or `SlackAdapter.receive` | Grep `\.receive\(` in `src` | docstrings in webhook/slack, `mesh/gossip.py:84` | yes |
| AV4 | No architecture, seam or scanner manifest names the channel files | Grep `channels[/\\.]\|discord_adapter\|slack_adapter\|channel_discord_check` in `scripts/*.py`, `docs/**/*.yaml\|json`, `config/*.yaml`; Grep `ChannelAdapter\|channels/base` in `check_architecture_principles.py` | `config-profiles.yaml` (config paths only); 0 | yes |
| AV5 | No `?raw`/AST reader pins the edited lines | Grep `(getsource\|read_text\|ast\.parse).*(channel\|adapter\|base\|doctor)` in tests | `test_ad1248_slice_b.py:189` (asserts `DmReply` in base, unchanged); Telegram send_response only | yes |
| AV6 | Every test that builds a Discord/Slack adapter and expects delivery is in §6 | Grep `SlackAdapter\(\|DiscordAdapter\(` in tests | the 19 hits are in the files of §6; the rest test `_check_pairing` directly, config or start | yes |
| AV7 | No doc says "empty = all" for Discord/Slack | Grep `(?i)(empty\s*(=\|means\|list).{0,40}(all\|every\|anyone))\|discord.{0,80}allow` in `docs/` | `config-reference.md:1175` (an unrelated mail config); era-5 roadmap history; `architecture/experience.md:58` claims pairing gates new senders (corrected in §7.6) | yes |
| AV8 | `Field` and `SimpleNamespace` are not defined in `src` (precheck safety) | Grep `\bField\s*[:=]\|\bSimpleNamespace\s*[:=]` in `src` | 0, so neither is used in this contract's fences | yes |

## 13. Prior Art and Blind Spots

- **Hermes Agent's messaging gateway** (reference row: passing, 2026-06-06; treated as *never* for this problem). It denies by default when no allow-list is set, has a per-platform allow-all flag (`DISCORD_ALLOW_ALL_USERS`) and a global one, and logs a startup warning. **Adopted:** the same shape (per-adapter bool, warning at start). Sources are third-party mirrors of its docs: [fast.io](https://fast.io/resources/hermes-agent-security/), [hostinger](https://www.hostinger.com/tutorials/?p=150091), [toolnavs](https://toolnavs.com/en/article/1739-hermes-agent-allowed-users-zen-me-pei-zhi).
- **OpenClaw DM policy.** Pairing is the default, and `open` requires an explicit `"*"` in `allowFrom` ([access control](https://docs.openclaw.ai/gateway/security/access-control), [pairing](https://docs.openclaw.ai/channels/pairing/index.html)). **Adapted:** the explicit opt-in. **Rejected:** a wildcard, because Discord's list is `list[int]`. Pairing is ProbOS's AD-802 path, and this issue does not wire it.
- **Internal:** the AD-472 hardening note at `roadmap-era-5-completed.md:1255` ("sender allowlist ... enforcement at the adapter level") supports adapter-level enforcement; BF-903 (#1581) paired-sender scope; #1621's requirement on the pairing AD.
- **Overdue reference rows, considered and deferred** (today 2026-10-23): SWE-agent, Cursor, OpenCode, MCP Apps, AG-UI. None bears on channel access.
- **Blind spots** (each in §17 or handled here):
  - Unlisted Discord bystanders in an unmentioned channel are refused silently and logged once each, bounded at 256.
  - Slack `receive` is only as trustworthy as the operator's Events API verifier.
  - The Discord doctor FAILs a token supplied only by `PROBOS_DISCORD_TOKEN`.
  - The Slack doctor reads a file the boot does not read.

## 14. Diff Reviewer: properties to verify

Consumer that must accept the change: the Discord and Slack inbound paths, the `probos doctor` runner, and the config facade, profiles and reference checks.

1. Every Discord and Slack path that reaches `handle_message` first passes the adapter's own `allowed_user_ids` and `allow_all_users` to `_sender_admitted`: Discord `on_message`, Slack `receive` and `_convert_message`.
2. With the opt-in off, an empty list admits no one, and a listed id is admitted only by exact string equality. With the opt-in on, everyone is admitted.
3. A refusal returns before any typing indicator, received-event emission, reply or `handle_message`, and returns the value that path already used for a refusal.
4. A refusal log line carries the sender id as `%r` and the channel name, never message text. There is at most one line per sender, and at most cap + 1 lines per adapter instance.
5. Every pre-existing field default and `config/system.yaml` are unchanged. Both new fields default to False.
6. `allowed_channel_ids` semantics, pairing, BF-903 visitor handling and every other adapter are unchanged.
7. The doctor returns WARN, never FAIL, for an enabled, token-present Discord adapter with the opt-in on or an empty list. The token-empty FAIL and the non-empty OK message are unchanged.
8. Each updated pin still tests its original property, and the sender it drives is listed.
9. The three generated files equal their generators' output, and the baseline diff is exactly §7.15's list.

## 15. Acceptance criteria

- An unlisted Discord or Slack sender never reaches the shell dispatcher or a natural-language turn (N1, N2, N5, N6), with the real filter and a fake transport.
- An empty `allowed_user_ids` with the opt-in off refuses every sender (N2, N6, N7). The opt-in admits (N2, N6, N7). A listed user is admitted (N1, N5, N7).
- `channel_discord_check` has the empty-list case and the opt-in case (N10).
- Refusal logging is once per sender, without the text, and bounded (N3, N4). The start warnings fire (N8, N9).
- All 21 mutation rows are killed.
- `check_config_facade.py --check`, `check_config_profiles.py`, `gen_config_reference.py --check` and `gen_ad_ledger.py --check` are clean.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Not verified

- Nothing was run: this was a read-only consult. No test, no mutation campaign, no `phantom-api-precheck.ps1`, no generator.
- The exact tool-computed baseline values (`canonical_dump_leaves`, `canonical_dump_sha256`, the four schema digests) and the generated reference rows' exact text are unchecked. BF-890's precedent left `canonical_dump_leaves` unchanged for a new list field, so whether a bool moves it is unknown.
- That N9's stub satisfies every attribute `start()` touches was traced by reading `discord_adapter.py:70-140`, not run.
- The Hermes Agent details come from third-party mirrors.

**Orchestrator verification (2026-10-23, by tool, on `origin/main` `eea6e2f4`, AD-1347 S2 and S3 merged; the consult above ran none of this).** All 28 code pairs apply, each SEARCH once (the oracle, scratch commit `5f0f44cc`), and §7.17 creates the new test file. The new file passes (21 cases, 4 s) and, with the other changed test files and `test_ad1185_config_profiles.py`, 504 pass. **Tests-first:** the oracle's eight test files on `eea6e2f4`'s source: 22 failed, 363 passed; the failures are the new file's refusal, log, start-warning, doctor and default cases, `test_ad1270e2c_experience_models.py`'s Discord and Slack dumps (four cases), `test_ad1152_agentic_correlation.py`'s golden (three cases) and `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface`. **Generators:** `check_config_facade.py --update-baseline` then `--check` (fields 1879); the baseline diff is exactly §7.15's list, and the tool-computed values are `canonical_dump_leaves` 1888 to 1890 and `canonical_dump_sha256` `a168a469...` to `d7b6536f...`; `gen_config_reference.py` inserts two rows and deletes none, then `--check` is current; `config-profiles.yaml` gains the two rows and `default_false` 226. **Mutation campaign:** the 21 rows of §10 ran one at a time on that oracle after an unmutated baseline (21 passed): 21 of 21 killed, none survived, none inert, none invalid, the pinned files unchanged. The phantom API precheck lists seven heuristic candidates, all symbols the prompt itself introduces (`allow_all_users` on the two configs, `MockTransport`, the `discord.py` prose).

## 17. For the register

1. Gmail (`allowed_senders`) and Teams (`allowed_user_aads`) have the same "empty = all" shape. Telegram and Matrix have no user list and rely on pairing alone. None is constructed in production (AV2). The AD that constructs any of them must call `_sender_admitted`, or wire pairing first.
2. Webhook: an empty `shared_secret` only warns ("any caller can post"), and `user_id` is caller-asserted. It is dormant, because no route calls `receive` (AV3).
3. `channel_slack_check` reads `~/.probos/channels/slack.yaml`, while the boot reads `config.channels.slack`, so the doctor judges a file the boot does not use.
4. `channel_discord_check` FAILs "token is empty" when the token comes only from `PROBOS_DISCORD_TOKEN`, which the boot accepts (`__main__.py:829`).
5. Slack `receive` trusts its caller's `user_id`. `SlackAdapter` never checks `signing_secret`.
6. The pairing-wiring AD: a caller identity for `execute_command` and a declared admin-command set (D5; #1621 Acceptance).
