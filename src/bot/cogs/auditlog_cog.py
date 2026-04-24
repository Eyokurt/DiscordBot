"""
Discord Bot — Audit Log Cog (Kapsamlı Sunucu Günlüğü)

Sunucuda olan HER ŞEYİ mod log kanalına yazar:
    - Üye giriş/çıkış
    - Mesaj düzenleme/silme
    - Ses kanalı giriş/çıkış/taşıma
    - Rol oluşturma/silme/düzenleme
    - Rol atama/kaldırma
    - Kanal oluşturma/silme/düzenleme
    - Yetki değişiklikleri
    - Ban/unban
    - Nickname değişiklikleri
    - Sunucu ayar değişiklikleri
    - Emoji/sticker değişiklikleri
    - Thread oluşturma/silme
    - Davet oluşturma/silme

Tüm olaylar renkli embed'ler ile mod_log_channel_id kanalına gönderilir.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.auditlog")

# Renk paleti
COLOR_JOIN = discord.Color.green()
COLOR_LEAVE = discord.Color.red()
COLOR_EDIT = discord.Color.orange()
COLOR_DELETE = discord.Color.dark_red()
COLOR_CREATE = discord.Color.blue()
COLOR_ROLE = discord.Color.purple()
COLOR_VOICE = discord.Color.teal()
COLOR_BAN = discord.Color.from_str("#FF0000")
COLOR_SETTINGS = discord.Color.gold()
COLOR_INFO = discord.Color.greyple()


class AuditLogCog(commands.Cog, name="Audit Log"):
    """Comprehensive server event logger — writes everything to mod log channel."""

    def __init__(self, bot: DiscordBot):
        self.bot = bot
        # Cache: guild_id → channel_id (None = not fetched yet)
        self._log_channels: dict[int, int | None] = {}

    async def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Get the mod log channel for a guild, fetching from DB if needed."""
        guild_id = guild.id

        if guild_id not in self._log_channels:
            # Fetch from DB via ZMQ
            msg = make_request("GET_GUILD_SETTINGS", guild_id=guild_id)
            response = await self.bot.request(Topic.DB, msg, timeout=3.0)
            if response and response.data.get("settings"):
                channel_id = response.data["settings"].get("mod_log_channel_id")
                self._log_channels[guild_id] = channel_id
            else:
                self._log_channels[guild_id] = None

        channel_id = self._log_channels.get(guild_id)
        if not channel_id:
            return None

        return guild.get_channel(channel_id)

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed):
        """Send a log embed to the guild's mod log channel."""
        channel = await self._get_log_channel(guild)
        if not channel:
            return
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning("No permission to send to log channel in guild %s", guild.id)
        except Exception as e:
            log.error("Failed to send log: %s", e)

    def _ts(self) -> str:
        """Current timestamp string."""
        return datetime.datetime.now().strftime("%H:%M:%S")

    # Invalidate cache when settings change
    @commands.Cog.listener()
    async def on_zmq_setting_changed(self, message):
        """Clear cached log channel when settings are updated."""
        guild_id = message.data.get("guild_id")
        if guild_id and message.data.get("key") == "mod_log_channel_id":
            self._log_channels.pop(guild_id, None)

    # ══════════════════════════════════════════════════════════════════
    #  ÜYE OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = discord.Embed(
            title="📥 Üye Katıldı",
            description=f"{member.mention} ({member})",
            color=COLOR_JOIN,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Hesap Oluşturma", value=member.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
        age = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
        embed.add_field(name="Hesap Yaşı", value=f"{age} gün", inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.set_footer(text=f"Toplam üye: {member.guild.member_count}")
        await self._send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        embed = discord.Embed(
            title="📤 Üye Ayrıldı",
            description=f"{member.mention} ({member})",
            color=COLOR_LEAVE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if roles:
            embed.add_field(name="Roller", value=" ".join(roles[:10]), inline=False)
        joined = member.joined_at
        if joined:
            days = (datetime.datetime.now(datetime.timezone.utc) - joined).days
            embed.add_field(name="Sunucuda", value=f"{days} gün", inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.set_footer(text=f"Toplam üye: {member.guild.member_count}")
        await self._send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        # Nickname değişikliği
        if before.nick != after.nick:
            embed = discord.Embed(
                title="✏️ Takma Ad Değişti",
                description=f"{after.mention}",
                color=COLOR_EDIT,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.add_field(name="Önceki", value=before.nick or before.name, inline=True)
            embed.add_field(name="Yeni", value=after.nick or after.name, inline=True)
            await self._send_log(guild, embed)

        # Rol değişiklikleri
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)

        if added_roles:
            embed = discord.Embed(
                title="➕ Rol Eklendi",
                description=f"{after.mention}",
                color=COLOR_ROLE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.add_field(name="Eklenen Roller", value=" ".join(r.mention for r in added_roles), inline=False)
            await self._send_log(guild, embed)

        if removed_roles:
            embed = discord.Embed(
                title="➖ Rol Kaldırıldı",
                description=f"{after.mention}",
                color=COLOR_ROLE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.add_field(name="Kaldırılan Roller", value=" ".join(r.mention for r in removed_roles), inline=False)
            await self._send_log(guild, embed)

        # Timeout değişikliği
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until and after.timed_out_until > datetime.datetime.now(datetime.timezone.utc):
                embed = discord.Embed(
                    title="🔇 Üye Susturuldu",
                    description=f"{after.mention}",
                    color=COLOR_BAN,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                embed.add_field(name="Bitiş", value=after.timed_out_until.strftime("%d/%m/%Y %H:%M"), inline=True)
            else:
                embed = discord.Embed(
                    title="🔊 Susturma Kaldırıldı",
                    description=f"{after.mention}",
                    color=COLOR_JOIN,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
            await self._send_log(guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  MESAJ OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        embed = discord.Embed(
            title="🗑️ Mesaj Silindi",
            description=f"**Kanal:** {message.channel.mention}",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Yazar", value=message.author.mention, inline=True)
        content = message.content[:1000] if message.content else "*İçerik yok (embed/dosya)*"
        embed.add_field(name="İçerik", value=content, inline=False)
        if message.attachments:
            files = "\n".join(a.filename for a in message.attachments)
            embed.add_field(name="Dosyalar", value=files, inline=False)
        embed.set_footer(text=f"Mesaj ID: {message.id}")
        await self._send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        embed = discord.Embed(
            title="🗑️ Toplu Mesaj Silindi",
            description=f"**{len(messages)}** mesaj silindi\n**Kanal:** {channel.mention}",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        embed = discord.Embed(
            title="✏️ Mesaj Düzenlendi",
            description=f"**Kanal:** {before.channel.mention} | [Mesaja Git]({after.jump_url})",
            color=COLOR_EDIT,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Yazar", value=before.author.mention, inline=True)
        embed.add_field(name="Önceki", value=before.content[:500] or "*Boş*", inline=False)
        embed.add_field(name="Yeni", value=after.content[:500] or "*Boş*", inline=False)
        embed.set_footer(text=f"Mesaj ID: {after.id}")
        await self._send_log(before.guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  SES KANALI OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        guild = member.guild

        # Ses kanalına katıldı
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊 Ses Kanalına Katıldı",
                description=f"{member.mention} → **{after.channel.name}**",
                color=COLOR_VOICE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        # Ses kanalından ayrıldı
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 Ses Kanalından Ayrıldı",
                description=f"{member.mention} ← **{before.channel.name}**",
                color=COLOR_INFO,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        # Kanal değiştirdi
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            embed = discord.Embed(
                title="🔀 Ses Kanalı Değişti",
                description=f"{member.mention}\n**{before.channel.name}** → **{after.channel.name}**",
                color=COLOR_VOICE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        # Mikrofon susturma
        if before.self_mute != after.self_mute:
            status = "🔇 Mikrofon Kapattı" if after.self_mute else "🔊 Mikrofon Açtı"
            embed = discord.Embed(
                title=status,
                description=f"{member.mention} — {after.channel.name if after.channel else '?'}",
                color=COLOR_INFO,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        # Sunucu tarafından susturma
        if before.mute != after.mute:
            status = "🔇 Sunucu Susturdu" if after.mute else "🔊 Sunucu Susturmayı Kaldırdı"
            embed = discord.Embed(
                title=status,
                description=f"{member.mention}",
                color=COLOR_BAN if after.mute else COLOR_JOIN,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        # Sunucu tarafından sağır yapma
        if before.deaf != after.deaf:
            status = "🔇 Sunucu Sağır Yaptı" if after.deaf else "🔊 Sunucu Sağırı Kaldırdı"
            embed = discord.Embed(
                title=status,
                description=f"{member.mention}",
                color=COLOR_BAN if after.deaf else COLOR_JOIN,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  ROL OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = discord.Embed(
            title="🆕 Rol Oluşturuldu",
            description=f"{role.mention} (`{role.name}`)",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Renk", value=str(role.color), inline=True)
        embed.add_field(name="Pozisyon", value=str(role.position), inline=True)
        embed.add_field(name="ID", value=str(role.id), inline=True)
        await self._send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        embed = discord.Embed(
            title="🗑️ Rol Silindi",
            description=f"`{role.name}`",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Renk", value=str(role.color), inline=True)
        embed.add_field(name="ID", value=str(role.id), inline=True)
        await self._send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"**İsim:** `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Renk:** `{before.color}` → `{after.color}`")
        if before.hoist != after.hoist:
            changes.append(f"**Ayrı Göster:** `{before.hoist}` → `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Bahsedilebilir:** `{before.mentionable}` → `{after.mentionable}`")
        if before.permissions != after.permissions:
            added = after.permissions.value & ~before.permissions.value
            removed = before.permissions.value & ~after.permissions.value
            if added:
                perms = discord.Permissions(added)
                plist = [p for p, v in perms if v]
                changes.append(f"**Yetki Eklendi:** `{', '.join(plist[:5])}`")
            if removed:
                perms = discord.Permissions(removed)
                plist = [p for p, v in perms if v]
                changes.append(f"**Yetki Kaldırıldı:** `{', '.join(plist[:5])}`")

        if not changes:
            return

        embed = discord.Embed(
            title="✏️ Rol Güncellendi",
            description=f"{after.mention}\n" + "\n".join(changes),
            color=COLOR_ROLE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(after.guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  KANAL OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(
            title="📁 Kanal Oluşturuldu",
            description=f"**{channel.name}** ({channel.type})",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if hasattr(channel, "category") and channel.category:
            embed.add_field(name="Kategori", value=channel.category.name, inline=True)
        embed.add_field(name="ID", value=str(channel.id), inline=True)
        await self._send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(
            title="🗑️ Kanal Silindi",
            description=f"**{channel.name}** ({channel.type})",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="ID", value=str(channel.id), inline=True)
        await self._send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        changes = []
        if before.name != after.name:
            changes.append(f"**İsim:** `{before.name}` → `{after.name}`")
        if hasattr(before, "topic") and hasattr(after, "topic"):
            if before.topic != after.topic:
                changes.append(f"**Konu:** `{before.topic or 'Yok'}` → `{after.topic or 'Yok'}`")
        if hasattr(before, "slowmode_delay") and hasattr(after, "slowmode_delay"):
            if before.slowmode_delay != after.slowmode_delay:
                changes.append(f"**Yavaş Mod:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if hasattr(before, "nsfw") and hasattr(after, "nsfw"):
            if before.nsfw != after.nsfw:
                changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")

        # Permission overwrites
        if before.overwrites != after.overwrites:
            changes.append("**Yetki ayarları değişti**")

        if not changes:
            return

        embed = discord.Embed(
            title="✏️ Kanal Güncellendi",
            description=f"**{after.name}**\n" + "\n".join(changes),
            color=COLOR_EDIT,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(after.guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  BAN OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(
            title="🔨 Üye Yasaklandı",
            description=f"{user.mention} ({user})",
            color=COLOR_BAN,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=str(user.id), inline=True)
        await self._send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(
            title="🔓 Yasak Kaldırıldı",
            description=f"{user.mention} ({user})",
            color=COLOR_JOIN,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=str(user.id), inline=True)
        await self._send_log(guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  SUNUCU OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"**İsim:** `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**İkon değişti**")
        if before.banner != after.banner:
            changes.append("**Banner değişti**")
        if before.owner_id != after.owner_id:
            changes.append(f"**Sahip:** <@{before.owner_id}> → <@{after.owner_id}>")
        if before.verification_level != after.verification_level:
            changes.append(f"**Doğrulama:** `{before.verification_level}` → `{after.verification_level}`")
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(f"**İçerik Filtresi:** `{before.explicit_content_filter}` → `{after.explicit_content_filter}`")

        if not changes:
            return

        embed = discord.Embed(
            title="⚙️ Sunucu Güncellendi",
            description="\n".join(changes),
            color=COLOR_SETTINGS,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(after, embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        added = set(after) - set(before)
        removed = set(before) - set(after)

        if added:
            embed = discord.Embed(
                title="😀 Emoji Eklendi",
                description=" ".join(str(e) for e in added),
                color=COLOR_CREATE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

        if removed:
            embed = discord.Embed(
                title="😢 Emoji Kaldırıldı",
                description=" ".join(f"`{e.name}`" for e in removed),
                color=COLOR_DELETE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await self._send_log(guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  THREAD OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        embed = discord.Embed(
            title="🧵 Thread Oluşturuldu",
            description=f"**{thread.name}** — {thread.parent.mention if thread.parent else '?'}",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if thread.owner:
            embed.add_field(name="Oluşturan", value=thread.owner.mention, inline=True)
        await self._send_log(thread.guild, embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        embed = discord.Embed(
            title="🗑️ Thread Silindi",
            description=f"**{thread.name}**",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(thread.guild, embed)

    # ══════════════════════════════════════════════════════════════════
    #  DAVET OLAYLARI
    # ══════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        embed = discord.Embed(
            title="🔗 Davet Oluşturuldu",
            description=f"`{invite.code}`",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if invite.inviter:
            embed.add_field(name="Oluşturan", value=invite.inviter.mention, inline=True)
        embed.add_field(name="Kanal", value=invite.channel.mention if invite.channel else "?", inline=True)
        embed.add_field(name="Max Kullanım", value=str(invite.max_uses or "∞"), inline=True)
        await self._send_log(invite.guild, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        embed = discord.Embed(
            title="🔗 Davet Silindi",
            description=f"`{invite.code}`",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._send_log(invite.guild, embed)


async def setup(bot: DiscordBot):
    await bot.add_cog(AuditLogCog(bot))
    log.info("AuditLogCog loaded.")
