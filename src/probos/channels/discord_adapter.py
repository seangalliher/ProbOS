"""Discord bot adapter for ProbOS.

Bridges Discord messages to the ProbOS runtime via the ChannelAdapter
base class. Incoming messages are processed through
runtime.process_natural_language(), and results are sent back as
channel replies.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import warnings
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
        except (ImportError, Exception) as exc:
            logger.error(
                "discord.py failed to load: %s. Install/fix with: "
                "uv add 'discord.py>=2.0'", exc
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
        """Wrapper that retries on rate limits and catches crashes."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                await self._bot.start(self.discord_config.token)
                return  # Clean shutdown
            except Exception as e:
                is_rate_limit = "429" in str(e) or "rate limit" in str(e).lower()
                if is_rate_limit and attempt < max_retries - 1:
                    delay = 2 ** (attempt + 2)  # 4, 8, 16, 32s
                    logger.warning(
                        "Discord login rate limited (attempt %d/%d), retrying in %ds",
                        attempt + 1, max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    # discord.py needs a fresh client after a failed login
                    import discord
                    intents = discord.Intents.default()
                    intents.message_content = True
                    self._bot = discord.Client(intents=intents)
                    self._setup_event_handlers()
                else:
                    logger.error("Discord bot crashed: %s", e, exc_info=True)
                    self._started = False
                    return

    async def stop(self) -> None:
        """Close the Discord connection.

        discord.py's shutdown path can block the event loop on Windows
        (SSL teardown, keep-alive thread joins). We isolate the teardown
        in a dedicated thread with its own event loop so blocking calls
        can't defeat asyncio.wait_for() timeouts on the main loop.
        """
        if not self._started:
            return

        # ---- Suppress known discord.py shutdown noise ----

        _original_excepthook = threading.excepthook

        def _suppress_keepalive(args: threading.ExceptHookArgs) -> None:
            if (
                args.exc_type is RuntimeError
                and args.thread
                and "keep-alive" in (args.thread.name or "")
            ):
                return
            _original_excepthook(args)

        threading.excepthook = _suppress_keepalive
        warnings.filterwarnings(
            "ignore",
            message="coroutine.*was never awaited",
            category=RuntimeWarning,
        )

        # ---- Thread-isolated teardown ----

        bot = self._bot
        bot_task = self._bot_task

        def _teardown_in_thread() -> None:
            """Run discord teardown in a separate thread with a hard deadline.

            This prevents discord.py's blocking SSL/WebSocket cleanup from
            stalling the main event loop on Windows SelectorEventLoop.
            """
            if bot and not bot.is_closed():
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(bot.close(), timeout=2.0)
                    )
                except Exception:
                    pass
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass

            # Force-close the HTTP session if still open
            if bot and hasattr(bot, "http"):
                http = bot.http
                session = getattr(http, "_HTTPClient__session", None)
                if session and not session.closed:
                    loop2 = asyncio.new_event_loop()
                    try:
                        loop2.run_until_complete(session.close())
                    except Exception:
                        pass
                    finally:
                        try:
                            loop2.close()
                        except Exception:
                            pass

        # Run teardown in a thread with a hard 3-second wall-clock deadline.
        # threading.Thread.join(timeout) is a real OS timeout that can't be
        # blocked by asyncio event loop issues.
        teardown_thread = threading.Thread(
            target=_teardown_in_thread,
            name="discord-teardown",
            daemon=True,
        )
        teardown_thread.start()
        # Poll with async sleep — asyncio.to_thread hangs on Windows
        # SelectorEventLoop, so we yield to the loop between checks.
        for _ in range(30):  # 3 seconds max (30 × 0.1s)
            if not teardown_thread.is_alive():
                break
            await asyncio.sleep(0.1)

        # Cancel the bot task (don't await — avoids the double-close hang)
        if bot_task and not bot_task.done():
            bot_task.cancel()

        self._bot = None
        self._bot_task = None
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

            # User filter — only respond to allowed users
            if (
                self.discord_config.allowed_user_ids
                and message.author.id
                not in self.discord_config.allowed_user_ids
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
