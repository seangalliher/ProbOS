"""Discord bot adapter for ProbOS.

Bridges Discord messages to the ProbOS runtime via the ChannelAdapter
base class. Incoming messages are processed through
runtime.process_natural_language(), and results are sent back as
channel replies.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.config import DiscordConfig

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 2000


def _chunk_message(text: str, limit: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long response into chunks that fit Discord's 2000-char limit.

    Tries to split on newlines first, then on spaces, then hard-splits.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to find a newline to split on
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


class DiscordAdapter(ChannelAdapter):
    """Discord bot that connects to ProbOS.

    Configuration:
        token: Discord bot token (required)
        allowed_channel_ids: list of channel IDs to listen on (empty = all)
        command_prefix: prefix for ProbOS slash commands (default: "!")
        mention_required: if True, bot only responds when @mentioned
    """

    def __init__(self, runtime: Any, config: DiscordConfig) -> None:
        super().__init__(runtime, config)
        self.discord_config: DiscordConfig = config
        self._bot: Any = None
        self._bot_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Create the discord.py client and start it as a background task."""
        try:
            import discord
        except ImportError:
            logger.error(
                "discord.py is not installed. Install with: "
                "uv add 'discord.py>=2.0'"
            )
            return

        if not self.discord_config.token:
            logger.error(
                "Discord bot token not configured. Set channels.discord.token "
                "in config or PROBOS_DISCORD_TOKEN environment variable."
            )
            return

        intents = discord.Intents.default()
        intents.message_content = True

        self._bot = discord.Client(intents=intents)
        self._setup_event_handlers()

        self._bot_task = asyncio.create_task(
            self._run_with_error_handling(),
            name="discord-adapter",
        )
        self._started = True
        logger.info("Discord adapter started")

    async def _run_with_error_handling(self) -> None:
        """Wrapper that catches bot crashes without taking down the runtime."""
        try:
            await self._bot.start(self.discord_config.token)
        except Exception as e:
            logger.error("Discord bot crashed: %s", e, exc_info=True)
            self._started = False

    async def stop(self) -> None:
        """Close the Discord connection."""
        if self._bot and not self._bot.is_closed():
            await self._bot.close()
        if self._bot_task:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except (asyncio.CancelledError, Exception):
                pass
        self._started = False
        logger.info("Discord adapter stopped")

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        """Send a response to a Discord channel, splitting if needed."""
        if not self._bot:
            return

        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            logger.warning("Discord channel %s not found", channel_id)
            return

        chunks = _chunk_message(response)
        for chunk in chunks:
            await channel.send(chunk)

    def _setup_event_handlers(self) -> None:
        """Wire discord.py event handlers."""
        import discord

        @self._bot.event
        async def on_ready() -> None:
            logger.info(
                "Discord bot connected as %s (id: %s)",
                self._bot.user.name,
                self._bot.user.id,
            )
            await self._bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.listening,
                    name="ProbOS commands",
                )
            )

        @self._bot.event
        async def on_message(message: discord.Message) -> None:
            # Never respond to ourselves or other bots
            if message.author == self._bot.user or message.author.bot:
                return

            # Channel filter
            if (
                self.discord_config.allowed_channel_ids
                and message.channel.id
                not in self.discord_config.allowed_channel_ids
            ):
                return

            text = message.content.strip()

            # Mention-required mode
            if self.discord_config.mention_required:
                if not self._bot.user.mentioned_in(message):
                    return
                text = text.replace(f"<@{self._bot.user.id}>", "").strip()
                text = text.replace(f"<@!{self._bot.user.id}>", "").strip()

            if not text:
                return

            # Map command prefix to ProbOS slash commands
            prefix = self.discord_config.command_prefix
            if prefix and text.startswith(prefix):
                text = "/" + text[len(prefix):]

            # Show typing indicator while processing
            async with message.channel.typing():
                try:
                    channel_msg = ChannelMessage(
                        text=text,
                        channel_id=str(message.channel.id),
                        user_id=str(message.author.id),
                        user_display_name=message.author.display_name,
                    )
                    response_text = await self.handle_message(channel_msg)
                    await self.send_response(
                        str(message.channel.id),
                        response_text,
                    )
                except asyncio.TimeoutError:
                    await message.channel.send(
                        "Request timed out \u2014 try a simpler query."
                    )
                except Exception as e:
                    logger.error(
                        "Discord message processing failed: %s",
                        e,
                        exc_info=True,
                    )
                    await message.channel.send(
                        f"Processing error: {type(e).__name__}"
                    )
