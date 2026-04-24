"""
Discord Bot — Settings Modals (discord.ui.Modal)

Pop-up input forms for editing specific settings.
Each modal sends the updated value to the DB service via ZMQ.

Modals:
    PrefixModal         — Edit the bot command prefix
    WelcomeMessageModal — Edit the welcome message template
    GoodbyeMessageModal — Edit the goodbye message template
    VolumeModal         — Edit the default music volume
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("ui.modal")


# ── Base Modal ─────────────────────────────────────────────────────────────

class SettingsModalBase(discord.ui.Modal):
    """
    Base class for settings modals.

    Handles the common pattern of:
    1. Display current value as default
    2. Accept user input
    3. Save via ZMQ to DB service
    4. Confirm success/failure
    """

    def __init__(
        self,
        *,
        title: str,
        bot: DiscordBot,
        guild_id: int,
        setting_key: str,
        current_value: str = "",
    ):
        super().__init__(title=title)
        self.bot = bot
        self.guild_id = guild_id
        self.setting_key = setting_key
        self.current_value = current_value

    async def save_setting(self, interaction: discord.Interaction, value: str):
        """Send the setting to DB service via ZMQ and respond."""
        msg = make_request(
            "SAVE_SETTING",
            data={"key": self.setting_key, "value": value},
            guild_id=self.guild_id,
            user_id=interaction.user.id,
        )

        response = await self.bot.request(Topic.DB, msg, timeout=5.0)

        if response and response.data.get("success"):
            await interaction.response.send_message(
                f"✅ **{self.title}** başarıyla güncellendi!\n"
                f"```{value}```",
                ephemeral=True,
            )
            log.info(
                "Setting saved: guild=%s key=%s by user=%s",
                self.guild_id, self.setting_key, interaction.user.id,
            )
        else:
            error = response.data.get("error", "Bilinmeyen hata") if response else "Zaman aşımı"
            await interaction.response.send_message(
                f"❌ Ayar kaydedilemedi: {error}",
                ephemeral=True,
            )


# ── Prefix Modal ───────────────────────────────────────────────────────────

class PrefixModal(SettingsModalBase):
    """Modal for editing the bot command prefix."""

    prefix_input = discord.ui.TextInput(
        label="Komut Prefix'i",
        placeholder="Örn: ! veya ? veya .",
        max_length=5,
        min_length=1,
        style=discord.TextStyle.short,
    )

    def __init__(self, bot: DiscordBot, guild_id: int, current_value: str = "!"):
        super().__init__(
            title="Prefix Değiştir",
            bot=bot,
            guild_id=guild_id,
            setting_key="prefix",
            current_value=current_value,
        )
        self.prefix_input.default = current_value

    async def on_submit(self, interaction: discord.Interaction):
        value = self.prefix_input.value.strip()
        if not value:
            await interaction.response.send_message("❌ Prefix boş olamaz.", ephemeral=True)
            return
        await self.save_setting(interaction, value)


# ── Welcome Message Modal ─────────────────────────────────────────────────

class WelcomeMessageModal(SettingsModalBase):
    """Modal for editing the welcome message template."""

    message_input = discord.ui.TextInput(
        label="Hoşgeldin Mesajı",
        placeholder="Sunucuya hoş geldin, {user}! 🎉\n\nDesteklenen: {user}, {server}, {member_count}",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, bot: DiscordBot, guild_id: int, current_value: str = ""):
        super().__init__(
            title="Hoşgeldin Mesajı Düzenle",
            bot=bot,
            guild_id=guild_id,
            setting_key="welcome_message",
            current_value=current_value,
        )
        self.message_input.default = current_value or "Sunucuya hoş geldin, {user}! 🎉"

    async def on_submit(self, interaction: discord.Interaction):
        value = self.message_input.value
        await self.save_setting(interaction, value)


# ── Goodbye Message Modal ─────────────────────────────────────────────────

class GoodbyeMessageModal(SettingsModalBase):
    """Modal for editing the goodbye message template."""

    message_input = discord.ui.TextInput(
        label="Veda Mesajı",
        placeholder="{user} aramızdan ayrıldı. 👋\n\nDesteklenen: {user}, {server}, {member_count}",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, bot: DiscordBot, guild_id: int, current_value: str = ""):
        super().__init__(
            title="Veda Mesajı Düzenle",
            bot=bot,
            guild_id=guild_id,
            setting_key="goodbye_message",
            current_value=current_value,
        )
        self.message_input.default = current_value or "{user} aramızdan ayrıldı. 👋"

    async def on_submit(self, interaction: discord.Interaction):
        value = self.message_input.value
        await self.save_setting(interaction, value)


# ── Volume Modal ───────────────────────────────────────────────────────────

class VolumeModal(SettingsModalBase):
    """Modal for setting the default music volume."""

    volume_input = discord.ui.TextInput(
        label="Ses Seviyesi (0-100)",
        placeholder="50",
        max_length=3,
        min_length=1,
        style=discord.TextStyle.short,
    )

    def __init__(self, bot: DiscordBot, guild_id: int, current_value: str = "50"):
        super().__init__(
            title="Müzik Ses Seviyesi",
            bot=bot,
            guild_id=guild_id,
            setting_key="music_volume",
            current_value=current_value,
        )
        self.volume_input.default = current_value

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.volume_input.value.strip()
        try:
            volume = int(raw)
            if not (0 <= volume <= 100):
                raise ValueError("Out of range")
        except ValueError:
            await interaction.response.send_message(
                "❌ Geçersiz değer. 0-100 arası bir sayı girin.",
                ephemeral=True,
            )
            return

        await self.save_setting(interaction, str(volume))
