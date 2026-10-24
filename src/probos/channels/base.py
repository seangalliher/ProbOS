"""Abstract channel adapter base class for external messaging integrations."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


class ChannelConfig(BaseModel):
    """Base configuration for any channel adapter."""
    enabled: bool = False


@dataclass
class ChannelMessage:
    """Normalized inbound message from any channel."""
    text: str
    channel_id: str
    user_id: str
    user_display_name: str = ""
    reply_to_message_id: str | None = None
    # AD-802a: DID attached by `_check_pairing` for paired senders.
    # Stays None when the sender is not yet paired, when the adapter has no
    # `channel_name` and so opts out of pairing, or when the runtime has no
    # pairing service -- so `handle_message` can legitimately run with this
    # unset. BF-903 (#1581): once set, the sender is a visiting officer and
    # `handle_message` serves it only an @callsign direct message, with dm.send.
    paired_did: str | None = None


#: BF-804: the entire text of a `PairingNotificationError`. It is echoed into
#: an HTTP response body by `probos.routers.teams_webhook`, so it names the
#: channel and nothing else -- the sender id, the raw address and the
#: underlying transport error belong in the log line only.
_PAIRING_NOTICE_FAILED = (
    "pairing instructions could not be delivered on channel {channel}"
)


class PairingNotificationError(RuntimeError):
    """An unpaired sender could not be told how to pair.

    BF-804: `_check_pairing` returning False means "unknown sender, and the
    pairing instructions WERE delivered", so a caller that treats the message
    as handled is right to do so. When the code was never minted, or the
    instructions never left, the sender gets no instructions, no answer and no
    retry -- and a bool cannot tell the caller which of the two happened. That
    is a delivery-integrity failure, so it belongs in the propagate tier.

    `GmailAdapter._poll_loop` already declines to acknowledge when
    `handle_message` raises, so this leaves the mail UNSEEN and re-fetched on
    the next poll without any edit to that adapter.
    """


#: BF-903 (#1581): the entire text of a `PairingLookupError`. Like BF-804's
#: notice it names the channel and nothing else: Teams echoes it into an HTTP
#: body (`routers/teams_webhook.py`).
_PAIRING_LOOKUP_FAILED = (
    "the pairing state could not be read on channel {channel}"
)

#: BF-903 (#1581): the replies a paired sender -- a visiting officer -- gets for
#: what its visit does not allow. They name the reason and nothing internal.
_PAIRED_NO_COMMANDS = (
    "Slash commands are not available to a paired visitor; send @callsign "
    "<message> to reach a crew member (BF-903)."
)
_PAIRED_NO_CONVERSATION = (
    "A paired visitor may send @callsign <message> to a crew member and "
    "nothing else (BF-903)."
)
_PAIRED_DM_REFUSED = (
    "Your message was not delivered: your visit does not allow direct "
    "messages ({reason}) (BF-903)."
)

#: BF-914 (#1621): how many distinct refused senders one adapter names in the
#: log. Each is named once; past the cap one more line says the rest go
#: unnamed, so a flood of throwaway accounts can grow neither memory nor the log.
_REFUSED_SENDER_LOG_CAP = 256


class PairingLookupError(PairingNotificationError):
    """BF-903 (#1581): `resolve_did` failed, so whether the sender is paired is unknown.

    AD-802a let such a message through (fail-open). A paired sender is a
    visiting officer, so an unclassified one reaching the slash-command and
    natural-language paths could be granted what pairing refuses. This is a
    `PairingNotificationError`, so every caller's existing handling applies
    unchanged: Gmail withholds its acknowledgement and retries on the next
    poll; Slack's webhook returns "" and its poll, Telegram and Matrix log and
    move on; Discord logs and posts nothing; Teams answers HTTP 200 with this
    text. On all but Gmail the sender must send again.
    """


class ChannelAdapter(ABC):
    """Abstract base for channel adapters that bridge external messaging
    platforms to the ProbOS runtime.

    Subclasses implement connect/disconnect and message delivery.
    The base class provides shared message processing logic via
    handle_message().
    """

    #: Stable channel identifier used by AD-802 PairingService and AD-801
    #: doctor checks (e.g. "telegram", "slack"). Subclasses that participate
    #: in pairing MUST override it; leaving it empty is the supported opt-out
    #: and is how `WebhookAdapter` bypasses the pairing gate entirely.
    channel_name: str = ""

    def __init__(self, runtime: ProbOSRuntime, config: ChannelConfig) -> None:
        self.runtime = runtime
        self.config = config
        self._started = False
        self._conversation_histories: dict[str, list[tuple[str, str]]] = {}
        self._max_history: int = 10
        # BF-914 (#1621): senders the user allow-list refused, each logged once.
        self._refused_senders: set[str] = set()
        self._refused_senders_capped = False

    @abstractmethod
    async def start(self) -> None:
        """Connect to the platform and begin listening for messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect from the platform and clean up resources."""
        ...

    @abstractmethod
    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        """Deliver a response back to the originating channel."""
        ...

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

        BF-804: there are THREE outcomes, and only two of them are return
        values.

        Returns:
            True  -> sender is paired, or the gate is not active; the message
                     can proceed to the `handle_message` body.
            False -> sender is unknown, a pairing code was minted AND the
                     instructions were DELIVERED. The message is dropped and
                     the caller may treat it as handled.

        Raises:
            PairingNotificationError: sender is unknown and could NOT be told
                how to pair -- either `request_pairing` failed or the
                instruction reply was never accepted. The caller must NOT
                treat the message as handled. What each caller then does is
                its own decision, and only Gmail currently recovers:
                `GmailAdapter._poll_loop` withholds its acknowledgement so the
                next poll retries the mail, whereas Slack returns an empty
                response, Discord drops the event, Telegram and Slack advance
                their offsets, Matrix advances its sync token and Teams answers
                HTTP 200. On those the sender must send again.

        Default behavior:
            * No `runtime.pairing_service` -> no-op pass-through (returns True).
            * `channel_name` empty -> no-op pass-through (subclass didn't
              opt in).
            * `pairing_service.resolve_did(channel_name, user_id)`:
                - returns a DID -> attach to `message.paired_did`, return True.
                - raises        -> raise `PairingLookupError` (BF-903: fail
                                   closed; a `PairingNotificationError`).
                - returns None  -> mint pending pairing, send instructions
                                   reply, return False -- or raise
                                   `PairingNotificationError` if either step
                                   fails.

        Reachability of the raise, which is narrower than it looks:
            The raise fires only when `request_pairing` or `send_response`
            *raises*. `GmailAdapter.send_response` does, because it surfaces
            an SMTP rejection, so Gmail -- the adapter where a wrongly
            acknowledged message is silent data loss -- distinguishes all
            three outcomes. Adapters whose `send_response` catches its own
            transport error and returns normally (Slack `SlackAPIError`,
            Telegram `TelegramAPIError`, Matrix `MatrixAPIError`, Teams
            `TeamsAPIError`, and Discord's unavailable-channel path) still
            report an undelivered notice as delivered. Giving those adapters
            the same three-way discrimination means changing their
            `send_response` delivery contract, which is deliberately out of
            scope here.

        Subclasses override only for adapter-specific behavior (per-guild
        allow-lists, anon-mode bypasses, etc.).
        """
        pairing_service = getattr(self.runtime, "pairing_service", None)
        if pairing_service is None or not self.channel_name:
            return True
        try:
            did = pairing_service.resolve_did(self.channel_name, message.user_id)
        except Exception as exc:
            logger.error(
                "AD-802a/BF-903: resolve_did failed for channel=%s user_id=%s; "
                "refusing the message (fail-closed): a sender whose pairing "
                "cannot be read may be a visiting officer. Raising "
                "PairingLookupError, which each caller handles as it handles "
                "PairingNotificationError.",
                self.channel_name, message.user_id, exc_info=True,
            )
            raise PairingLookupError(_PAIRING_LOOKUP_FAILED.format(channel=self.channel_name)) from exc

        if did is not None:
            message.paired_did = did
            return True

        # Unknown sender — mint a pending pairing and reply with instructions.
        try:
            code = await pairing_service.request_pairing(
                channel=self.channel_name,
                raw_id=message.user_id,
            )
        except Exception as exc:
            logger.error(
                "AD-802a/BF-804: request_pairing failed for channel=%s "
                "user_id=%s; no code exists, so the sender cannot be told how "
                "to pair. Raising PairingNotificationError so the caller can "
                "decline to treat this as handled. What follows is "
                "caller-dependent: Gmail withholds its acknowledgement and "
                "retries on the next poll, while the other adapters settle or "
                "drop the event, so on those the sender must send again.",
                self.channel_name, message.user_id, exc_info=True,
            )
            raise PairingNotificationError(
                _PAIRING_NOTICE_FAILED.format(channel=self.channel_name)
            ) from exc

        instructions = (
            f"Hi — this is a ProbOS bot. The Captain hasn't paired your "
            f"account yet. Please ask them to run:\n\n"
            f"    probos pairing approve {self.channel_name} {code}\n\n"
            f"Then send your message again."
        )
        try:
            await self.send_response(message.channel_id, instructions)
        except Exception as exc:
            logger.error(
                "AD-802a/BF-804: sending the pairing instructions failed for "
                "channel=%s user_id=%s; the sender was never told how to "
                "pair. Raising PairingNotificationError so the caller can "
                "decline to treat this as handled. What follows is "
                "caller-dependent: Gmail withholds its acknowledgement and "
                "retries on the next poll, while the other adapters settle or "
                "drop the event, so on those the sender must send again.",
                self.channel_name, message.user_id, exc_info=True,
            )
            raise PairingNotificationError(
                _PAIRING_NOTICE_FAILED.format(channel=self.channel_name)
            ) from exc
        return False

    async def handle_message(self, message: ChannelMessage) -> str:
        """Process an inbound message through the ProbOS runtime.

        Routes slash commands to the shell handler, natural language
        to process_natural_language(). Maintains per-channel conversation
        history.

        AD-802a: pairing-gate runs first. Unknown senders receive a
        pairing code reply and the message is dropped (returns "").

        BF-804: if those instructions could NOT be delivered, the gate raises
        `PairingNotificationError` rather than returning "", so a caller with
        an acknowledgement gate (Gmail) leaves the message for the next poll
        instead of recording it as handled.

        BF-903 (#1581): a paired sender is a visiting officer; `_handle_paired`
        serves it an @callsign direct message, with dm.send, and refuses the
        rest with a reply naming the reason.
        """
        from probos.utils.response_formatter import extract_response_text

        proceed = await self._check_pairing(message)
        if not proceed:
            return ""

        text = message.text.strip()
        if not text:
            return ""

        if message.paired_did is not None:  # BF-903 (#1581): a paired sender is a visiting officer
            return await self._handle_paired(message.paired_did, text)

        if text.startswith("/"):
            from probos.api import _handle_slash_command
            result = await _handle_slash_command(text, self.runtime)
            return result.get("response", "")

        # AD-397/BF-009: @callsign one-shot direct message via channel (anywhere in text)
        from probos.crew_profile import extract_callsign_mention
        mention = extract_callsign_mention(text)
        if mention:
            callsign, message_text = mention
            resolved = self.runtime.callsign_registry.resolve(callsign)
            if resolved is not None:
                return await self._handle_callsign_resolved(resolved, callsign, message_text)

        # Natural language path
        history = self._conversation_histories.get(message.channel_id, [])
        dag_result = await asyncio.wait_for(
            self.runtime.process_natural_language(
                text,
                auto_selfmod=False,
                conversation_history=history[-self._max_history:],
            ),
            timeout=30.0,
        )
        response_text = extract_response_text(dag_result)

        # Update conversation history
        if message.channel_id not in self._conversation_histories:
            self._conversation_histories[message.channel_id] = []
        hist = self._conversation_histories[message.channel_id]
        hist.append(("user", text))
        hist.append(("assistant", response_text))
        if len(hist) > self._max_history * 2:
            self._conversation_histories[message.channel_id] = hist[-(self._max_history * 2):]

        return response_text

    async def _handle_paired(self, did: str, text: str) -> str:
        """BF-903 (#1581): what a paired sender may do here -- an @callsign direct message, with dm.send.

        Pairing registered the sender as a visiting officer (AD-802), so its
        session is checked directly, at use, in AD-701's registry; with no
        registry attached the message is refused. No declared capability grants
        a slash command or a natural-language turn, so each is refused with a
        reply naming the reason. The AD that wires pairing declares what more a
        paired sender may do.
        """
        from probos.crew_profile import extract_callsign_mention
        from probos.visiting_officers import CAP_DM_SEND, VisitorScopeRefused, require_session_capability

        if text.startswith("/"):  # BF-903: no declared capability grants a slash command
            logger.warning(
                "BF-903: refused a slash command from paired sender %s on channel %s",
                did, self.channel_name,
            )
            return _PAIRED_NO_COMMANDS
        mention = extract_callsign_mention(text)
        resolved = None if mention is None else self.runtime.callsign_registry.resolve(mention[0])
        if mention is None or resolved is None:
            logger.warning(
                "BF-903: refused a natural-language turn from paired sender %s on channel %s",
                did, self.channel_name,
            )
            return _PAIRED_NO_CONVERSATION
        try:
            require_session_capability(
                did, CAP_DM_SEND, surface=f"channel.{self.channel_name}.dm",
                visiting_officers=getattr(self.runtime, "visiting_officers", None),
            )
        except VisitorScopeRefused as refused:
            return _PAIRED_DM_REFUSED.format(reason=refused.reason)
        callsign, message_text = mention
        return await self._handle_callsign_resolved(resolved, callsign, message_text)

    async def _handle_callsign_resolved(self, resolved: dict, callsign: str, message_text: str) -> str:
        """Route to a resolved crew member (AD-397, BF-009). One-shot, no session."""
        from probos.types import IntentMessage
        from probos.dm_reply import DmReply

        if resolved["agent_id"] is None:
            return f"{resolved['callsign']} is not currently on duty."

        if not message_text:
            return f"{resolved['callsign']} is available. Send a message: @{callsign} <message>"

        intent = IntentMessage(
            intent="direct_message",
            params={"text": message_text, "from": "channel", "session": False},
            target_agent_id=resolved["agent_id"],
        )
        result = await self.runtime.intent_bus.send(intent)
        if result is None:
            return f"{resolved['callsign']}: (no response)"

        # BF-802 (#1266) / AD-1248: compose here rather than gating on
        # `result.result`. A run whose tools all failed produces empty text but
        # a non-empty failure set, and the old `if result and result.result`
        # threw that away -- the Captain was told "(no response)" when the
        # truthful answer was "web_search failed". This is the fifth sink where
        # that same gate hid a disclosure.
        #
        # `render()` returns RenderedDmText (a str SUBCLASS). Interpolating it
        # into an f-string yields a plain str, which matters because
        # `threads/__init__.py` rejects `type(body) is not str`.
        rendered = DmReply.from_intent_result(result).render()
        if not str(rendered):
            return f"{resolved['callsign']}: (no response)"
        return f"{resolved['callsign']}: {rendered}"
