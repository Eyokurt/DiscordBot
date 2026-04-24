"""
Discord Bot — Moderation Commands Cog

Commands:
    /temizle <sayı>           — Delete messages
    /sustur <kullanıcı> <dk>  — Timeout a user
    /uyar <kullanıcı> <sebep> — Warn a user
    /uyarılar <kullanıcı>     — List warnings
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request, make_command

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.moderation")


class ModerationCog(commands.Cog, name="Moderasyon"):
    def __init__(self, bot: DiscordBot):
        self.bot = bot

    @app_commands.command(name="temizle", description="Belirtilen sayıda mesajı siler")
    @app_commands.describe(sayı="Silinecek mesaj sayısı (1-100)")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, sayı: int):
        if not 1 <= sayı <= 100:
            await interaction.response.send_message("❌ 1-100 arası bir sayı girin.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=sayı)
        await interaction.followup.send(f"🗑️ **{len(deleted)}** mesaj silindi.", ephemeral=True)
        log.info("Purged %d messages in #%s by %s", len(deleted), interaction.channel.name, interaction.user.id)

    @app_commands.command(name="sustur", description="Bir kullanıcıyı belirtilen süre kadar susturur")
    @app_commands.describe(kullanıcı="Susturulacak kullanıcı", dakika="Susturma süresi (dakika)")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, kullanıcı: discord.Member, dakika: int):
        if dakika < 1 or dakika > 40320:  # Max 28 days
            await interaction.response.send_message("❌ Süre 1-40320 dakika arası olmalı.", ephemeral=True)
            return
        if kullanıcı.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Bu kullanıcıyı susturamazsınız.", ephemeral=True)
            return
        try:
            await kullanıcı.timeout(timedelta(minutes=dakika), reason=f"Susturuldu: {interaction.user}")
            embed = discord.Embed(
                title="🔇 Kullanıcı Susturuldu",
                description=f"{kullanıcı.mention} **{dakika} dakika** susturuldu.",
                color=discord.Color.orange(),
            )
            embed.add_field(name="Moderatör", value=interaction.user.mention, inline=True)
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Yetki hatası.", ephemeral=True)

    @app_commands.command(name="uyar", description="Bir kullanıcıya uyarı verir")
    @app_commands.describe(kullanıcı="Uyarılacak kullanıcı", sebep="Uyarı sebebi")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, kullanıcı: discord.Member, sebep: str):
        await interaction.response.defer()
        msg = make_request(
            "ADD_WARNING",
            data={"target_user_id": kullanıcı.id, "reason": sebep},
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        response = await self.bot.request(Topic.DB, msg, timeout=5.0)
        if response and response.data.get("success"):
            count = response.data.get("warning_count", "?")
            embed = discord.Embed(
                title="⚠️ Kullanıcı Uyarıldı",
                color=discord.Color.yellow(),
            )
            embed.add_field(name="Kullanıcı", value=kullanıcı.mention, inline=True)
            embed.add_field(name="Toplam Uyarı", value=str(count), inline=True)
            embed.add_field(name="Sebep", value=sebep, inline=False)
            embed.add_field(name="Moderatör", value=interaction.user.mention, inline=True)
            await interaction.followup.send(embed=embed)
            # DM the warned user
            try:
                await kullanıcı.send(f"⚠️ **{interaction.guild.name}** sunucusunda uyarı aldınız.\nSebep: {sebep}")
            except discord.Forbidden:
                pass
        else:
            await interaction.followup.send("❌ Uyarı kaydedilemedi.")

    @app_commands.command(name="uyarılar", description="Bir kullanıcının uyarılarını gösterir")
    @app_commands.describe(kullanıcı="Uyarıları görüntülenecek kullanıcı")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, kullanıcı: discord.Member):
        await interaction.response.defer(ephemeral=True)
        msg = make_request(
            "GET_WARNINGS",
            data={"target_user_id": kullanıcı.id},
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        response = await self.bot.request(Topic.DB, msg, timeout=5.0)
        if not response:
            await interaction.followup.send("❌ DB servisi yanıt vermedi.", ephemeral=True)
            return
        warnings_list = response.data.get("warnings", [])
        if not warnings_list:
            await interaction.followup.send(f"✅ {kullanıcı.mention} için uyarı bulunmuyor.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"⚠️ {kullanıcı.display_name} — Uyarılar",
            color=discord.Color.yellow(),
        )
        for i, w in enumerate(warnings_list[:10], 1):
            embed.add_field(
                name=f"#{w.get('id', i)} — {w.get('created_at', '?')[:10]}",
                value=f"**Sebep:** {w.get('reason', '?')}\n**Mod:** <@{w.get('mod_id', 0)}>",
                inline=False,
            )
        if len(warnings_list) > 10:
            embed.set_footer(text=f"... ve {len(warnings_list)-10} uyarı daha")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: DiscordBot):
    await bot.add_cog(ModerationCog(bot))
    log.info("ModerationCog loaded.")
