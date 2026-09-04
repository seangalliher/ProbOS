"""Abstract channel adapter base class for external messaging integrations."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
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
    # `channel_name` and so opts out of pairing, when the runtime has no
    # pairing service, and on the `resolve_did` fail-open path -- so
    # `handle_message` can legitimately run with this unset.
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
                - raises        -> fail open, return True.
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
        except Exception:
            logger.warning(
                "AD-802a: resolve_did failed for channel=%s user_id=%s; "
                "allowing message (fail-open)",
                self.channel_name, message.user_id, exc_info=True,
            )
            return True

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
        """
        from probos.utils.response_formatter import extract_response_text

        proceed = await self._check_pairing(message)
        if not proceed:
            return ""

        text = message.text.strip()
        if not text:
            return ""

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
