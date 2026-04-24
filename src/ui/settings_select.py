"""
Discord Bot — Settings Category Select (discord.ui.Select)

Dropdown menu for selecting a settings category.
Triggers the parent SettingsView to display category-specific options.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.ui.settings_view import SettingsView

log = get_logger("ui.select")


class CategorySelect(discord.ui.Select):
    """
    Dropdown menu for choosing a settings category.

    Categories:
        🌐 Genel      — Prefix, language, auto-role
        👋 Hoşgeldin  — Welcome/goodbye messages and channels
        🎵 Müzik      — DJ role, volume
        🛡️ Moderasyon — Mod log channel, warning settings
    """

    def __init__(self, parent_view: SettingsView):
        self._parent_view = parent_view

        options = [
            discord.SelectOption(
                label="Genel",
                value="general",
                description="Prefix, dil ve genel ayarlar",
                emoji="🌐",
            ),
            discord.SelectOption(
                label="Hoşgeldin / Veda",
                value="welcome",
                description="Hoşgeldin ve veda mesajları",
                emoji="👋",
            ),
            discord.SelectOption(
                label="Müzik",
                value="music",
                description="DJ rolü ve ses seviyesi",
                emoji="🎵",
            ),
            discord.SelectOption(
                label="Moderasyon",
                value="moderation",
                description="Mod log ve uyarı sistemi",
                emoji="🛡️",
            ),
        ]

        super().__init__(
            placeholder="📋 Bir kategori seçin...",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle category selection — update the parent view."""
        selected = self.values[0]
        log.info(
            "User %s selected category: %s (guild=%s)",
            interaction.user.id, selected, interaction.guild_id,
        )

        # Delegate to the parent SettingsView to show category details
        await self._parent_view.show_category(interaction, selected)
