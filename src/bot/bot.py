"""
Discord Bot — Core Bot Class

The central Discord bot that connects to the Discord API and routes
commands to worker services via ZMQ. Uses discord.py v2.x with
app commands (slash commands).

Responsibilities:
    - Discord gateway connection and event handling
    - Slash command registration (via Cogs)
    - ZMQ listener task for receiving worker responses
    - Pending request correlation (REQUEST → RESPONSE matching)

Usage:
    python -m src.bot.bot
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any

import discord
from discord.ext import commands

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.config import DISCORD_TOKEN, DISCORD_GUILD_ID, BOT_PREFIX
from src.core.logger import get_logger
from src.core.zmq_client import AsyncZMQEventBus
from src.core.protocol import Topic, ZMQMessage, MessageType
from src.bot.cog_manager import CogManager

log = get_logger("bot")


class DiscordBot(commands.Bot):
    """
    Main Discord bot with integrated ZMQ event bus.

    The bot runs an asyncio task that listens for ZMQ messages from
    worker services and resolves pending request futures.
    """

    def __init__(self):
        # Discord.py setup
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=BOT_PREFIX,
            intents=intents,
            help_command=None,  # We'll use slash commands instead
        )

        # ZMQ event bus (async version for the asyncio loop)
        self.ebus = AsyncZMQEventBus(service_name="bot")
        self.ebus.subscribe(Topic.BOT)
        self.ebus.subscribe(Topic.SYSTEM)
        self.ebus.subscribe(Topic.SETTINGS)

        # Pending requests: request_id → asyncio.Future
        # Used to correlate REQ/REP messages from workers
        self._pending: dict[str, asyncio.Future] = {}

        # Cog manager for dynamic loading
        self.cog_manager = CogManager(self)

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def setup_hook(self):
        """Called once when the bot is ready to set up internal state."""
        log.info("Bot setup_hook started.")

        # Load all cogs from the cogs directory
        await self.cog_manager.load_all()

        # Start ZMQ listener as a background task
        self.loop.create_task(self._zmq_listener())

        # Sync slash commands
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild %s.", DISCORD_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally.")

    async def on_ready(self):
        """Fires when the bot is fully connected to Discord."""
        log.info(
            "Bot online: %s (ID: %s) — %d guild(s)",
            self.user.name, self.user.id, len(self.guilds),
        )

        # Set presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(self.guilds)} sunucu 👀",
        )
        await self.change_presence(activity=activity)

    async def on_guild_join(self, guild: discord.Guild):
        """Create default settings when joining a new guild."""
        from src.core.protocol import make_command
        await self.ebus.publish(
            Topic.DB,
            make_command("GET_GUILD_SETTINGS", guild_id=guild.id),
        )
        log.info("Joined guild: %s (ID: %s)", guild.name, guild.id)

    # ── ZMQ Communication ─────────────────────────────────────────────

    async def _zmq_listener(self):
        """
        Background task: listens for ZMQ messages from worker services.

        Resolves pending futures for REQUEST/RESPONSE correlation and
        dispatches events to registered handlers.
        """
        log.info("ZMQ listener started.")

        while not self.is_closed():
            try:
                topic, message = await self.ebus.receive()

                if topic is None or message is None:
                    continue

                # Handle RESPONSE messages → resolve pending futures
                if message.msg_type == MessageType.RESPONSE:
                    future = self._pending.pop(message.request_id, None)
                    if future and not future.done():
                        future.set_result(message)
                    continue

                # Handle SYSTEM messages
                if topic == Topic.SYSTEM:
                    await self._handle_system_event(message)
                    continue

                # Handle SETTINGS change events
                if topic == Topic.SETTINGS:
                    await self._handle_settings_event(message)
                    continue

                # Dispatch to bot event handlers
                self.dispatch(f"zmq_{message.action.lower()}", message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("ZMQ listener error: %s", e, exc_info=True)
                await asyncio.sleep(1)

        log.info("ZMQ listener stopped.")

    async def request(
        self,
        topic: str,
        message: ZMQMessage,
        timeout: float = 10.0,
    ) -> ZMQMessage | None:
        """
        Send a REQUEST message and await the RESPONSE.

        This creates an asyncio.Future keyed by request_id, publishes
        the message, and waits for the worker to reply.

        Args:
            topic:   Target service topic.
            message: ZMQMessage with msg_type=REQUEST.
            timeout: Max seconds to wait for response.

        Returns:
            The response ZMQMessage, or None on timeout.
        """
        future = self.loop.create_future()
        self._pending[message.request_id] = future

        await self.ebus.publish(topic, message)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(message.request_id, None)
            log.warning(
                "Request timeout: %s/%s (id=%s)",
                topic, message.action, message.request_id,
            )
            return None

    async def fire_and_forget(self, topic: str, message: ZMQMessage):
        """Send a COMMAND message without waiting for a response."""
        await self.ebus.publish(topic, message)

    # ── Internal Event Handlers ────────────────────────────────────────

    async def _handle_system_event(self, message: ZMQMessage):
        """Process SYSTEM topic events."""
        if message.action == "SERVICE_READY":
            service = message.data.get("service", "unknown")
            log.info("Service ready: %s", service)

    async def _handle_settings_event(self, message: ZMQMessage):
        """Process SETTINGS change notifications."""
        if message.action == "SETTING_CHANGED":
            guild_id = message.data.get("guild_id")
            key = message.data.get("key")
            log.info("Setting changed: guild=%s key=%s", guild_id, key)

    # ── Cleanup ────────────────────────────────────────────────────────

    async def close(self):
        """Graceful shutdown: cleanup ZMQ, then close Discord connection."""
        log.info("Bot shutting down...")
        self.ebus.cleanup()
        await super().close()


# ── Entry Point ────────────────────────────────────────────────────────────

def run_bot():
    """Start the Discord bot (blocks until shutdown)."""
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_bot_token_here":
        log.critical("DISCORD_TOKEN is not set. Check your .env file.")
        sys.exit(1)

    bot = DiscordBot()
    bot.run(DISCORD_TOKEN, log_handler=None)  # We use our own logger


if __name__ == "__main__":
    run_bot()
