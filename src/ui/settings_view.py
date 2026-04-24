"""
Discord Bot — Settings View (discord.ui.View)

Main settings interface that combines Select menus, Buttons, and Modals
into a cohesive settings experience. Handles user session state management.

Flow:
    /ayarlar → SettingsView (category select) → category buttons → Modal (data input)

State Management:
    Each user has an active session tracked in _active_sessions dict.
    Sessions auto-expire after 180 seconds (View timeout).
    Only the user who invoked /ayarlar can interact with their menu.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import discord

from src.core.logger import get_logger
from src.ui.settings_select import CategorySelect
from src.ui.settings_modal import (
    WelcomeMessageModal,
    GoodbyeMessageModal,
    PrefixModal,
    VolumeModal,
)

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("ui.settings")

# ── Session State ──────────────────────────────────────────────────────────

# Active user sessions: user_id → {"category": str, "guild_id": int, "timestamp": float}
_active_sessions: dict[int, dict[str, Any]] = {}

# Session timeout in seconds
SESSION_TIMEOUT = 180


def get_session(user_id: int) -> dict | None:
    """Get active session for a user, or None if expired/missing."""
    session = _active_sessions.get(user_id)
    if session and (time.time() - session["timestamp"]) < SESSION_TIMEOUT:
        return session
    # Clean up expired session
    _active_sessions.pop(user_id, None)
    return None


def set_session(user_id: int, guild_id: int, category: str = ""):
    """Create or update a user's settings session."""
    _active_sessions[user_id] = {
        "category": category,
        "guild_id": guild_id,
        "timestamp": time.time(),
    }


def clear_session(user_id: int):
    """Remove a user's settings session."""
    _active_sessions.pop(user_id, None)


# ── Settings Embed Builders ───────────────────────────────────────────────

def build_main_embed(guild: discord.Guild) -> discord.Embed:
    """Build the main settings embed shown when /ayarlar is first invoked."""
    embed = discord.Embed(
        title="⚙️  Sunucu Ayarları",
        description=(
            f"**{guild.name}** için bot ayarlarını bu menüden yapılandırabilirsiniz.\n\n"
            "Aşağıdaki menüden bir kategori seçin:"
        ),
        color=discord.Color.from_str("#5865F2"),
    )
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.set_footer(text="Bu menü 3 dakika sonra kapanacaktır.")
    return embed


def build_category_embed(
    category: str,
    settings: dict,
    guild: discord.Guild,
) -> discord.Embed:
    """Build the embed for a specific settings category."""
    category_info = {
        "general": {
            "title": "🌐  Genel Ayarlar",
            "color": discord.Color.blue(),
            "fields": [
                ("Prefix", settings.get("prefix", "!"), True),
                ("Dil", settings.get("language", "tr"), True),
                ("Otomatik Rol", f"<@&{settings['auto_role_id']}>" if settings.get("auto_role_id") else "Kapalı", True),
            ],
        },
        "welcome": {
            "title": "👋  Hoşgeldin / Veda",
            "color": discord.Color.green(),
            "fields": [
                ("Hoşgeldin Kanalı", f"<#{settings['welcome_channel_id']}>" if settings.get("welcome_channel_id") else "Kapalı", True),
                ("Hoşgeldin Mesajı", settings.get("welcome_message", "Ayarlanmamış")[:100], False),
                ("Veda Kanalı", f"<#{settings['goodbye_channel_id']}>" if settings.get("goodbye_channel_id") else "Kapalı", True),
                ("Veda Mesajı", settings.get("goodbye_message", "Ayarlanmamış")[:100], False),
            ],
        },
        "music": {
            "title": "🎵  Müzik Ayarları",
            "color": discord.Color.from_str("#1DB954"),
            "fields": [
                ("DJ Rolü", f"<@&{settings['dj_role_id']}>" if settings.get("dj_role_id") else "Herkese açık", True),
                ("Ses Seviyesi", f"{settings.get('music_volume', 50)}%", True),
            ],
        },
        "moderation": {
            "title": "🛡️  Moderasyon Ayarları",
            "color": discord.Color.red(),
            "fields": [
                ("Mod Log Kanalı", f"<#{settings['mod_log_channel_id']}>" if settings.get("mod_log_channel_id") else "Kapalı", True),
            ],
        },
    }

    info = category_info.get(category, {
        "title": f"📋  {category.title()} Ayarları",
        "color": discord.Color.greyple(),
        "fields": [],
    })

    embed = discord.Embed(title=info["title"], color=info["color"])
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    for name, value, inline in info["fields"]:
        embed.add_field(name=name, value=str(value), inline=inline)

    embed.set_footer(text="Bir ayarı değiştirmek için aşağıdaki butonları kullanın.")
    return embed


# ── Main Settings View ────────────────────────────────────────────────────

class SettingsView(discord.ui.View):
    """
    Main settings UI view with category selection and action buttons.

    Only the original invoker can interact with this view.
    """

    def __init__(self, bot: DiscordBot, user_id: int, guild_id: int, settings: dict):
        super().__init__(timeout=SESSION_TIMEOUT)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.settings = settings
        self.current_category: str | None = None

        # Add the category select menu
        self.category_select = CategorySelect(self)
        self.add_item(self.category_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the original user to interact."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Bu menü sadece komutu kullanan kişi tarafından kullanılabilir.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        """Clean up session on timeout."""
        clear_session(self.user_id)

    async def show_category(self, interaction: discord.Interaction, category: str):
        """
        Display the settings for a specific category with action buttons.
        """
        self.current_category = category
        set_session(self.user_id, self.guild_id, category)

        # Remove old buttons (keep the select at index 0)
        self.clear_items()
        self.add_item(self.category_select)

        # Add category-specific buttons
        if category == "general":
            self.add_item(EditButton("Prefix Değiştir", "prefix", discord.ButtonStyle.primary))
            self.add_item(EditButton("Dil Değiştir", "language", discord.ButtonStyle.primary))

        elif category == "welcome":
            self.add_item(EditButton("Hoşgeldin Mesajı", "welcome_message", discord.ButtonStyle.primary))
            self.add_item(EditButton("Veda Mesajı", "goodbye_message", discord.ButtonStyle.primary))
            self.add_item(ChannelSelectButton("Hoşgeldin Kanalı", "welcome_channel_id"))
            self.add_item(ChannelSelectButton("Veda Kanalı", "goodbye_channel_id"))

        elif category == "music":
            self.add_item(EditButton("Ses Seviyesi", "music_volume", discord.ButtonStyle.primary))
            self.add_item(RoleSelectButton("DJ Rolü", "dj_role_id"))

        elif category == "moderation":
            self.add_item(ChannelSelectButton("Mod Log Kanalı", "mod_log_channel_id"))

        # Close button (always present)
        self.add_item(CloseButton())

        # Build and send the category embed
        embed = build_category_embed(category, self.settings, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)


# ── Buttons ───────────────────────────────────────────────────────────────

class EditButton(discord.ui.Button):
    """Button that opens a Modal for editing a text-based setting."""

    def __init__(self, label: str, setting_key: str, style=discord.ButtonStyle.primary):
        super().__init__(label=label, style=style, emoji="✏️")
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        view: SettingsView = self.view

        # Choose the appropriate modal based on the setting key
        modal_map = {
            "prefix": PrefixModal,
            "welcome_message": WelcomeMessageModal,
            "goodbye_message": GoodbyeMessageModal,
            "music_volume": VolumeModal,
        }

        modal_cls = modal_map.get(self.setting_key)
        if modal_cls:
            modal = modal_cls(
                bot=view.bot,
                guild_id=view.guild_id,
                current_value=str(view.settings.get(self.setting_key, "")),
            )
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message(
                "Bu ayar henüz düzenlenemez.", ephemeral=True
            )


class ChannelSelectButton(discord.ui.Button):
    """Button that opens a channel selector for setting a channel ID."""

    def __init__(self, label: str, setting_key: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, emoji="📢")
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        """Send a channel select view."""
        view: SettingsView = self.view

        select_view = ChannelPickerView(
            bot=view.bot,
            guild_id=view.guild_id,
            setting_key=self.setting_key,
            user_id=view.user_id,
        )
        await interaction.response.send_message(
            f"📢 **{self.label}** için bir kanal seçin:",
            view=select_view,
            ephemeral=True,
        )


class RoleSelectButton(discord.ui.Button):
    """Button that opens a role selector."""

    def __init__(self, label: str, setting_key: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, emoji="👤")
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        view: SettingsView = self.view

        select_view = RolePickerView(
            bot=view.bot,
            guild_id=view.guild_id,
            setting_key=self.setting_key,
            user_id=view.user_id,
        )
        await interaction.response.send_message(
            f"👤 **{self.label}** için bir rol seçin:",
            view=select_view,
            ephemeral=True,
        )


class CloseButton(discord.ui.Button):
    """Button to close the settings menu."""

    def __init__(self):
        super().__init__(label="Kapat", style=discord.ButtonStyle.danger, emoji="✖️", row=4)

    async def callback(self, interaction: discord.Interaction):
        view: SettingsView = self.view
        clear_session(view.user_id)

        embed = discord.Embed(
            title="⚙️  Ayarlar Kapatıldı",
            description="Ayarlar menüsü kapatıldı. Tekrar açmak için `/ayarlar` kullanın.",
            color=discord.Color.greyple(),
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── Picker Views (ephemeral channel/role selection) ────────────────────────

class ChannelPickerView(discord.ui.View):
    """Ephemeral view for selecting a text channel."""

    def __init__(self, bot: DiscordBot, guild_id: int, setting_key: str, user_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.setting_key = setting_key
        self.user_id = user_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Kanal seçin...",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1,
    )
    async def channel_callback(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]

        # Save via ZMQ
        from src.core.protocol import make_request, Topic
        msg = make_request(
            "SAVE_SETTING",
            data={"key": self.setting_key, "value": channel.id},
            guild_id=self.guild_id,
            user_id=self.user_id,
        )
        response = await self.bot.request(Topic.DB, msg)

        if response and response.data.get("success"):
            await interaction.response.edit_message(
                content=f"✅ Kanal **{channel.name}** olarak ayarlandı!",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="❌ Ayar kaydedilemedi.",
                view=None,
            )


class RolePickerView(discord.ui.View):
    """Ephemeral view for selecting a role."""

    def __init__(self, bot: DiscordBot, guild_id: int, setting_key: str, user_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.setting_key = setting_key
        self.user_id = user_id

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Rol seçin...",
        min_values=1,
        max_values=1,
    )
    async def role_callback(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]

        from src.core.protocol import make_request, Topic
        msg = make_request(
            "SAVE_SETTING",
            data={"key": self.setting_key, "value": role.id},
            guild_id=self.guild_id,
            user_id=self.user_id,
        )
        response = await self.bot.request(Topic.DB, msg)

        if response and response.data.get("success"):
            await interaction.response.edit_message(
                content=f"✅ Rol **{role.name}** olarak ayarlandı!",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="❌ Ayar kaydedilemedi.",
                view=None,
            )
