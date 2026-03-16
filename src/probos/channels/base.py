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


class ChannelAdapter(ABC):
    """Abstract base for channel adapters that bridge external messaging
    platforms to the ProbOS runtime.

    Subclasses implement connect/disconnect and message delivery.
    The base class provides shared message processing logic via
    handle_message().
    """

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

    async def handle_message(self, message: ChannelMessage) -> str:
        """Process an inbound message through the ProbOS runtime.

        Routes slash commands to the shell handler, natural language
        to process_natural_language(). Maintains per-channel conversation
        history.
        """
        from probos.channels.response_formatter import extract_response_text

        text = message.text.strip()
        if not text:
            return ""

        if text.startswith("/"):
            from probos.api import _handle_slash_command
            result = await _handle_slash_command(text, self.runtime)
            return result.get("response", "")

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
