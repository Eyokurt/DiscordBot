"""
Discord Bot — Settings Command Cog

Provides the /ayarlar slash command that opens the interactive
settings UI (View + Select + Modal).

Commands:
    /ayarlar — Open the server settings menu

This cog bridges the Discord UI components from src/ui/ and the
DB service via ZMQ for persistent storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request
from src.ui.settings_view import SettingsView, build_main_embed, set_session

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.settings")


class SettingsCog(commands.Cog, name="Ayarlar"):
    """Settings management commands."""

    def __init__(self, bot: DiscordBot):
        self.bot = bot

    # ── /ayarlar ───────────────────────────────────────────────────────

    @app_commands.command(name="ayarlar", description="Sunucu ayarları menüsünü açar")
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        """
        Open the interactive settings menu.

        Flow:
        1. Fetch current guild settings from DB via ZMQ
        2. Build the main settings embed
        3. Create SettingsView with category select
        4. Send as an ephemeral message
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Bu komut sadece sunucularda çalışır.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Fetch current guild settings from DB service
        msg = make_request(
            "GET_GUILD_SETTINGS",
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )

        response = await self.bot.request(Topic.DB, msg, timeout=5.0)

        if response and response.data.get("settings"):
            settings = response.data["settings"]
        else:
            # Fallback to defaults if DB service is unavailable
            log.warning("Could not fetch settings from DB, using defaults.")
            settings = {
                "prefix": "!",
                "language": "tr",
                "welcome_channel_id": None,
                "welcome_message": "Sunucuya hoş geldin, {user}! 🎉",
                "goodbye_channel_id": None,
                "goodbye_message": "{user} aramızdan ayrıldı. 👋",
                "dj_role_id": None,
                "mod_log_channel_id": None,
                "auto_role_id": None,
                "music_volume": 50,
            }

        # Create session for this user
        set_session(interaction.user.id, interaction.guild_id)

        # Build the view with embed
        embed = build_main_embed(interaction.guild)
        view = SettingsView(
            bot=self.bot,
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            settings=settings,
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        log.info(
            "Settings menu opened by %s in guild %s",
            interaction.user.id, interaction.guild_id,
        )


async def setup(bot: DiscordBot):
    """Load the SettingsCog."""
    await bot.add_cog(SettingsCog(bot))
    log.info("SettingsCog loaded.")
