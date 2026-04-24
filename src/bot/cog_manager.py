"""
Discord Bot — Dynamic Cog Manager

Handles runtime loading, unloading, and reloading of bot extensions (cogs).
Discovers cogs from the `src/bot/cogs/` directory and provides admin
commands for hot-swapping modules without restarting the bot.

Features:
    - Auto-discovery of .py files in the cogs directory
    - load_cog / unload_cog / reload_cog methods
    - load_all for initial boot
    - Admin slash commands: /cog yükle, /cog kaldır, /cog yenile, /cog liste

Usage:
    manager = CogManager(bot)
    await manager.load_all()
    await manager.reload_cog("general")
"""

from __future__ import annotations

import os
import importlib
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cogs")

# Path to the cogs directory
COGS_DIR = os.path.join(os.path.dirname(__file__), "cogs")
COGS_PACKAGE = "src.bot.cogs"


class CogManager:
    """
    Manages the lifecycle of Discord bot cogs (extensions).

    Provides methods for discovering, loading, unloading, and
    reloading cogs at runtime.
    """

    def __init__(self, bot: DiscordBot):
        self.bot = bot
        self._loaded_cogs: set[str] = set()

    def discover_cogs(self) -> list[str]:
        """
        Discover all available cog modules in the cogs directory.

        Returns:
            List of module paths (e.g. ["src.bot.cogs.general", ...])
        """
        cogs = []
        if not os.path.isdir(COGS_DIR):
            log.warning("Cogs directory not found: %s", COGS_DIR)
            return cogs

        for filename in sorted(os.listdir(COGS_DIR)):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]  # Remove .py
                cogs.append(f"{COGS_PACKAGE}.{module_name}")

        return cogs

    async def load_all(self):
        """Load all discovered cogs. Called during bot startup."""
        cog_paths = self.discover_cogs()
        log.info("Discovered %d cog(s): %s", len(cog_paths), [c.split(".")[-1] for c in cog_paths])

        for cog_path in cog_paths:
            await self.load_cog(cog_path)

        # Register the cog management commands
        await self._register_admin_commands()

    async def load_cog(self, cog_path: str) -> bool:
        """
        Load a single cog by its module path.

        Args:
            cog_path: Full module path (e.g. "src.bot.cogs.general")

        Returns:
            True if loaded successfully, False otherwise.
        """
        name = cog_path.split(".")[-1]

        if cog_path in self._loaded_cogs:
            log.warning("Cog already loaded: %s", name)
            return False

        try:
            await self.bot.load_extension(cog_path)
            self._loaded_cogs.add(cog_path)
            log.info("✅ Cog loaded: %s", name)
            return True
        except commands.ExtensionAlreadyLoaded:
            self._loaded_cogs.add(cog_path)
            log.warning("Cog was already loaded: %s", name)
            return True
        except Exception as e:
            log.error("❌ Failed to load cog '%s': %s", name, e, exc_info=True)
            return False

    async def unload_cog(self, cog_path: str) -> bool:
        """
        Unload a single cog by its module path.

        Args:
            cog_path: Full module path (e.g. "src.bot.cogs.general")

        Returns:
            True if unloaded successfully, False otherwise.
        """
        name = cog_path.split(".")[-1]

        try:
            await self.bot.unload_extension(cog_path)
            self._loaded_cogs.discard(cog_path)
            log.info("⬇️ Cog unloaded: %s", name)
            return True
        except commands.ExtensionNotLoaded:
            self._loaded_cogs.discard(cog_path)
            log.warning("Cog was not loaded: %s", name)
            return True
        except Exception as e:
            log.error("❌ Failed to unload cog '%s': %s", name, e)
            return False

    async def reload_cog(self, cog_path: str) -> bool:
        """
        Reload a single cog (unload + load). Hot-swaps the module.

        Args:
            cog_path: Full module path (e.g. "src.bot.cogs.general")

        Returns:
            True if reloaded successfully, False otherwise.
        """
        name = cog_path.split(".")[-1]

        try:
            await self.bot.reload_extension(cog_path)
            self._loaded_cogs.add(cog_path)
            log.info("🔄 Cog reloaded: %s", name)
            return True
        except commands.ExtensionNotLoaded:
            # Not loaded yet, just load it
            return await self.load_cog(cog_path)
        except Exception as e:
            log.error("❌ Failed to reload cog '%s': %s", name, e, exc_info=True)
            return False

    def get_loaded_cogs(self) -> list[str]:
        """Return list of currently loaded cog names."""
        return [path.split(".")[-1] for path in sorted(self._loaded_cogs)]

    def resolve_cog_path(self, name: str) -> str:
        """Convert a short cog name to its full module path."""
        # Remove common suffixes for convenience
        if name.endswith("_cog"):
            name = name
        return f"{COGS_PACKAGE}.{name}"

    # ── Admin Commands ─────────────────────────────────────────────────

    async def _register_admin_commands(self):
        """Register the /cog admin command group."""
        # Only register if not already registered
        existing = self.bot.tree.get_command("cog")
        if existing:
            return

        cog_group = app_commands.Group(
            name="cog",
            description="Cog yönetimi (sadece bot sahibi)",
            default_permissions=discord.Permissions(administrator=True),
        )

        manager = self  # Capture reference

        @cog_group.command(name="yükle", description="Bir cog modülünü yükle")
        @app_commands.describe(isim="Yüklenecek cog adı (örn: general, music_cog)")
        async def cog_load(interaction: discord.Interaction, isim: str):
            path = manager.resolve_cog_path(isim)
            success = await manager.load_cog(path)

            if success:
                await interaction.response.send_message(
                    f"✅ **{isim}** başarıyla yüklendi.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{isim}** yüklenemedi. Loglara bakın.", ephemeral=True
                )

        @cog_group.command(name="kaldır", description="Bir cog modülünü kaldır")
        @app_commands.describe(isim="Kaldırılacak cog adı")
        async def cog_unload(interaction: discord.Interaction, isim: str):
            path = manager.resolve_cog_path(isim)
            success = await manager.unload_cog(path)

            if success:
                await interaction.response.send_message(
                    f"⬇️ **{isim}** başarıyla kaldırıldı.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{isim}** kaldırılamadı.", ephemeral=True
                )

        @cog_group.command(name="yenile", description="Bir cog modülünü yeniden yükle")
        @app_commands.describe(isim="Yenilenecek cog adı")
        async def cog_reload(interaction: discord.Interaction, isim: str):
            path = manager.resolve_cog_path(isim)
            success = await manager.reload_cog(path)

            if success:
                await interaction.response.send_message(
                    f"🔄 **{isim}** başarıyla yenilendi.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{isim}** yenilenemedi. Loglara bakın.", ephemeral=True
                )

        @cog_group.command(name="liste", description="Yüklü cog listesini göster")
        async def cog_list(interaction: discord.Interaction):
            loaded = manager.get_loaded_cogs()
            available = [p.split(".")[-1] for p in manager.discover_cogs()]

            embed = discord.Embed(
                title="🧩 Cog Durumu",
                color=discord.Color.blue(),
            )

            loaded_text = "\n".join(f"✅ {c}" for c in loaded) or "Hiçbiri"
            unloaded = [c for c in available if c not in loaded]
            unloaded_text = "\n".join(f"⬇️ {c}" for c in unloaded) or "Hiçbiri"

            embed.add_field(name="Yüklü", value=loaded_text, inline=True)
            embed.add_field(name="Mevcut (yüklü değil)", value=unloaded_text, inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        self.bot.tree.add_command(cog_group)
        log.info("Cog admin commands registered.")
