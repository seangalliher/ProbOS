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
    # None when no pairing exists yet (only possible inside `_check_pairing`
    # itself; once `handle_message` runs the field is always populated for
    # paired-channel adapters).
    paired_did: str | None = None


class ChannelAdapter(ABC):
    """Abstract base for channel adapters that bridge external messaging
    platforms to the ProbOS runtime.

    Subclasses implement connect/disconnect and message delivery.
    The base class provides shared message processing logic via
    handle_message().
    """

    #: Stable channel identifier used by AD-802 PairingService and AD-801
    #: doctor checks (e.g. "telegram", "slack"). Subclasses MUST override.
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

        Returns:
            True  -> message can proceed to `handle_message` body.
            False -> a pairing code was minted, sender notified, message
                     dropped. Caller should NOT process further.

        Default behavior:
            * No `runtime.pairing_service` -> no-op pass-through (returns True).
            * `channel_name` empty -> no-op pass-through (subclass didn't
              opt in).
            * `pairing_service.resolve_did(channel_name, user_id)`:
                - returns a DID -> attach to `message.paired_did`, return True.
                - returns None  -> mint pending pairing, send instructions
                                   reply, return False.

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
        except Exception:
            logger.error(
                "AD-802a: request_pairing failed for channel=%s user_id=%s; "
                "dropping message",
                self.channel_name, message.user_id, exc_info=True,
            )
            return False

        instructions = (
            f"Hi — this is a ProbOS bot. The Captain hasn't paired your "
            f"account yet. Please ask them to run:\n\n"
            f"    probos pairing approve {self.channel_name} {code}\n\n"
            f"Then send your message again."
        )
        try:
            await self.send_response(message.channel_id, instructions)
        except Exception:
            logger.warning(
                "AD-802a: send_response for pairing instructions failed; "
                "user will need to retry",
                exc_info=True,
            )
        return False

    async def handle_message(self, message: ChannelMessage) -> str:
        """Process an inbound message through the ProbOS runtime.

        Routes slash commands to the shell handler, natural language
        to process_natural_language(). Maintains per-channel conversation
        history.

        AD-802a: pairing-gate runs first. Unknown senders receive a
        pairing code reply and the message is dropped (returns "").
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
