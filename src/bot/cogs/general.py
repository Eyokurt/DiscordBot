"""
Discord Bot — General Commands Cog

Basic utility commands available to all users.

Commands:
    /ping     — Bot latency check
    /bilgi    — Bot information and statistics
    /sunucu   — Current server information
"""

from __future__ import annotations

import time
import platform
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.general")


class GeneralCog(commands.Cog, name="Genel"):
    """General utility commands."""

    def __init__(self, bot: DiscordBot):
        self.bot = bot
        self._start_time = time.time()

    # ── /ping ──────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="Bot'un gecikme süresini gösterir")
    async def ping(self, interaction: discord.Interaction):
        """Check bot latency."""
        ws_latency = round(self.bot.latency * 1000)

        # Measure round-trip time
        start = time.monotonic()
        await interaction.response.defer(ephemeral=True)
        rtt = round((time.monotonic() - start) * 1000)

        embed = discord.Embed(
            title="🏓 Pong!",
            color=discord.Color.green() if ws_latency < 200 else discord.Color.yellow(),
        )
        embed.add_field(name="WebSocket", value=f"`{ws_latency}ms`", inline=True)
        embed.add_field(name="API (RTT)", value=f"`{rtt}ms`", inline=True)
        embed.add_field(name="ZMQ", value="`< 1ms`", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /bilgi ─────────────────────────────────────────────────────────

    @app_commands.command(name="bilgi", description="Bot hakkında bilgi gösterir")
    async def info(self, interaction: discord.Interaction):
        """Display bot information and statistics."""
        uptime_seconds = int(time.time() - self._start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        embed = discord.Embed(
            title=f"ℹ️  {self.bot.user.name}",
            description="ZMQ tabanlı microservice mimarisi ile çalışan modüler Discord botu.",
            color=discord.Color.from_str("#5865F2"),
        )

        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(
            name="📊 İstatistikler",
            value=(
                f"**Sunucu:** {len(self.bot.guilds)}\n"
                f"**Kullanıcı:** {sum(g.member_count for g in self.bot.guilds if g.member_count)}\n"
                f"**Uptime:** {hours}s {minutes}dk {seconds}sn"
            ),
            inline=True,
        )

        cogs = self.bot.cog_manager.get_loaded_cogs()
        embed.add_field(
            name="🧩 Yüklü Modüller",
            value="\n".join(f"✅ {c}" for c in cogs) if cogs else "Hiçbiri",
            inline=True,
        )

        embed.add_field(
            name="⚙️ Teknik",
            value=(
                f"**Python:** {platform.python_version()}\n"
                f"**discord.py:** {discord.__version__}\n"
                f"**Mimari:** ZMQ Microservice"
            ),
            inline=True,
        )

        embed.set_footer(text="Geliştirici: Yayıncı Bot Ekibi")

        await interaction.response.send_message(embed=embed)

    # ── /sunucu ────────────────────────────────────────────────────────

    @app_commands.command(name="sunucu", description="Sunucu bilgilerini gösterir")
    async def server_info(self, interaction: discord.Interaction):
        """Display current server information."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Bu komut sadece sunucularda çalışır.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋  {guild.name}",
            color=discord.Color.from_str("#5865F2"),
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="👑 Sahip", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="👥 Üye", value=str(guild.member_count), inline=True)
        embed.add_field(name="📅 Kuruluş", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        embed.add_field(
            name="📺 Kanallar",
            value=f"💬 {text_channels} metin | 🔊 {voice_channels} ses",
            inline=False,
        )

        roles_count = len(guild.roles) - 1  # Exclude @everyone
        embed.add_field(name="🏷️ Roller", value=str(roles_count), inline=True)
        embed.add_field(name="😀 Emojiler", value=str(len(guild.emojis)), inline=True)

        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0
        embed.add_field(
            name="💎 Boost",
            value=f"Seviye {boost_level} ({boost_count} boost)",
            inline=True,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: DiscordBot):
    """Load the GeneralCog."""
    await bot.add_cog(GeneralCog(bot))
    log.info("GeneralCog loaded.")
