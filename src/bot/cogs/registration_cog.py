"""
Discord Bot — Registration Cog

Provides a registration system. Automatically assigns an unregistered role to new members,
and allows staff members to register them with a command, changing their name and roles.

Commands:
    /kayit-ayarla - Set registration roles
    /kayit - Register a user
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.registration")


class RegistrationCog(commands.Cog, name="Kayıt Sistemi"):
    """Registration and onboarding commands."""

    def __init__(self, bot: DiscordBot):
        self.bot = bot

    async def get_settings(self, guild_id: int) -> dict:
        msg = make_request("GET_GUILD_SETTINGS", guild_id=guild_id)
        response = await self.bot.request(Topic.DB, msg, timeout=5.0)
        if response and response.data.get("settings"):
            return response.data["settings"]
        return {}

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically assign unregistered role if configured."""
        if member.bot:
            return

        settings = await self.get_settings(member.guild.id)
        unregistered_role_id = settings.get("unregistered_role_id")

        if unregistered_role_id:
            role = member.guild.get_role(unregistered_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Oto-Kayıtsız Rolü")
                    log.info("Gave unregistered role to %s in %s", member.id, member.guild.id)
                except discord.Forbidden:
                    log.error("Missing permissions to give role %s", unregistered_role_id)
                except discord.HTTPException as e:
                    log.error("Failed to give role: %s", e)

    @app_commands.command(name="kayit-ayarla", description="Kayıt sistemi rollerini ayarlar")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_registration(
        self,
        interaction: discord.Interaction,
        kayitsiz_rol: discord.Role,
        kayitli_rol: discord.Role,
        yetkili_rol: Optional[discord.Role] = None,
    ):
        """Kayıt rollerini veritabanına kaydeder."""
        if not interaction.guild:
            return await interaction.response.send_message("Bu komut sadece sunucularda çalışır.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Save unregistered role
        msg1 = make_request("SAVE_SETTING", guild_id=interaction.guild.id, data={"key": "unregistered_role_id", "value": kayitsiz_rol.id})
        await self.bot.request(Topic.DB, msg1, timeout=5.0)

        # Save registered role
        msg2 = make_request("SAVE_SETTING", guild_id=interaction.guild.id, data={"key": "registered_role_id", "value": kayitli_rol.id})
        await self.bot.request(Topic.DB, msg2, timeout=5.0)

        # Save staff role
        staff_id = yetkili_rol.id if yetkili_rol else None
        msg3 = make_request("SAVE_SETTING", guild_id=interaction.guild.id, data={"key": "staff_role_id", "value": staff_id})
        await self.bot.request(Topic.DB, msg3, timeout=5.0)

        embed = discord.Embed(title="Kayıt Ayarları Kaydedildi ✅", color=discord.Color.green())
        embed.add_field(name="Kayıtsız Rolü", value=kayitsiz_rol.mention, inline=False)
        embed.add_field(name="Kayıtlı Rolü", value=kayitli_rol.mention, inline=False)
        if yetkili_rol:
            embed.add_field(name="Kayıt Yetkilisi Rolü", value=yetkili_rol.mention, inline=False)
        else:
            embed.add_field(name="Kayıt Yetkilisi Rolü", value="Ayarlanmadı (Sadece Yönetici)", inline=False)

        await interaction.followup.send(embed=embed)

    async def check_staff(self, interaction: discord.Interaction) -> bool:
        settings = await self.get_settings(interaction.guild.id)
        staff_role_id = settings.get("staff_role_id")
        if staff_role_id:
            staff_role = interaction.guild.get_role(staff_role_id)
            if staff_role and staff_role in interaction.user.roles:
                return True
        return interaction.user.guild_permissions.manage_roles

    async def process_registration(
        self,
        interaction: discord.Interaction,
        kullanici: discord.Member,
        isim: str,
        yas: int,
    ):
        settings = await self.get_settings(interaction.guild.id)
        
        unregistered_role_id = settings.get("unregistered_role_id")
        registered_role_id = settings.get("registered_role_id")

        if not unregistered_role_id or not registered_role_id:
            return await interaction.followup.send("❌ Kayıt sistemi ayarlanmamış! Lütfen önce `/kayit-ayarla` komutunu kullanın.", ephemeral=True)

        unregistered_role = interaction.guild.get_role(unregistered_role_id)
        registered_role = interaction.guild.get_role(registered_role_id)

        if not registered_role:
            return await interaction.followup.send("❌ Kayıtlı rolü bulunamadı, silinmiş olabilir.", ephemeral=True)

        new_nickname = f"{isim}|{yas}"

        try:
            # Change nickname
            if interaction.guild.me.top_role.position > kullanici.top_role.position:
                await kullanici.edit(nick=new_nickname)
            
            # Roles
            roles_to_add = [registered_role]
            roles_to_remove = []
            if unregistered_role and unregistered_role in kullanici.roles:
                roles_to_remove.append(unregistered_role)
            
            if roles_to_remove:
                await kullanici.remove_roles(*roles_to_remove, reason=f"Kayıt işlemi ({interaction.user})")
            
            await kullanici.add_roles(*roles_to_add, reason=f"Kayıt işlemi ({interaction.user})")

            embed = discord.Embed(
                description=f"🎉 {kullanici.mention} başarıyla **{new_nickname}** olarak kaydedildi!",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Kayıt eden yetkili: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
            log.info("User %s registered by %s in %s", kullanici.id, interaction.user.id, interaction.guild.id)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ Yetkim yetersiz! Lütfen bot rolünün, kullanıcının rolünden veya kayıtlı rolünden yukarıda olduğundan emin olun.", ephemeral=True)
        except Exception as e:
            log.error("Error during registration: %s", e)
            await interaction.followup.send("❌ Beklenmeyen bir hata oluştu.", ephemeral=True)

    @app_commands.command(name="kayit", description="Bir kullanıcıyı sunucuya kaydeder")
    async def register_user(
        self,
        interaction: discord.Interaction,
        kullanici: discord.Member,
        isim: str,
        yas: int,
    ):
        """Kullanıcının ismini değiştirir, kayıtsız rolünü alıp kayıtlı rolünü verir."""
        if not interaction.guild:
            return await interaction.response.send_message("Bu komut sadece sunucularda çalışır.", ephemeral=True)

        if not await self.check_staff(interaction):
            return await interaction.response.send_message("❌ Bu komutu kullanmak için Kayıt Yetkilisi veya Rolleri Yönet yetkisine sahip olmalısınız.", ephemeral=True)

        await interaction.response.defer()
        await self.process_registration(interaction, kullanici, isim, yas)

    @app_commands.command(name="kayit-paneli", description="Kayıt kanalına kalıcı kayıt yönetim paneli gönderir")
    @app_commands.default_permissions(manage_guild=True)
    async def spawn_registration_panel(self, interaction: discord.Interaction):
        """Sends the persistent registration panel."""
        if not interaction.guild:
            return await interaction.response.send_message("Bu komut sadece sunucularda çalışır.", ephemeral=True)

        embed = discord.Embed(
            title="🛠️ Kayıt Yönetim Paneli",
            description="Lütfen yapmak istediğiniz işlemi aşağıdaki butonlardan seçin.",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Sadece Kayıt Yetkilileri kullanabilir.")

        view = RegistrationPanelView(self)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Panel oluşturuldu.", ephemeral=True)


# ── UI Classes ─────────────────────────────────────────────────────────────

class RegistrationModal(discord.ui.Modal, title="Kullanıcı Kayıt Formu"):
    user_id_input = discord.ui.TextInput(
        label="Kullanıcı ID",
        placeholder="Örn: 123456789012345678",
        style=discord.TextStyle.short,
        required=True,
    )
    name_input = discord.ui.TextInput(
        label="İsim",
        placeholder="Örn: Ahmet",
        style=discord.TextStyle.short,
        required=True,
    )
    age_input = discord.ui.TextInput(
        label="Yaş",
        placeholder="Örn: 22",
        style=discord.TextStyle.short,
        required=True,
    )

    def __init__(self, cog: RegistrationCog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            user_id = int(self.user_id_input.value.strip())
        except ValueError:
            return await interaction.followup.send("❌ Hatalı Kullanıcı ID formatı.", ephemeral=True)
            
        kullanici = interaction.guild.get_member(user_id)
        if not kullanici:
            return await interaction.followup.send("❌ Kullanıcı sunucuda bulunamadı.", ephemeral=True)

        try:
            yas = int(self.age_input.value.strip())
        except ValueError:
            return await interaction.followup.send("❌ Yaş sadece sayılardan oluşmalıdır.", ephemeral=True)

        await self.cog.process_registration(interaction, kullanici, self.name_input.value.strip(), yas)

class QueryModal(discord.ui.Modal, title="Kullanıcı Sorgula"):
    user_id_input = discord.ui.TextInput(
        label="Kullanıcı ID",
        placeholder="Örn: 123456789012345678",
        style=discord.TextStyle.short,
        required=True,
    )

    def __init__(self, cog: RegistrationCog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = int(self.user_id_input.value.strip())
        except ValueError:
            return await interaction.followup.send("❌ Hatalı Kullanıcı ID formatı.", ephemeral=True)

        member = interaction.guild.get_member(user_id)
        if not member:
            return await interaction.followup.send("❌ Kullanıcı sunucuda bulunamadı.", ephemeral=True)

        embed = discord.Embed(title="Kullanıcı Bilgileri", color=discord.Color.blue())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Kullanıcı Adı", value=member.name, inline=True)
        embed.add_field(name="Sunucu İçi Adı", value=member.display_name, inline=True)
        embed.add_field(name="Katılım Tarihi", value=member.joined_at.strftime("%d-%m-%Y %H:%M") if member.joined_at else "Bilinmiyor", inline=False)
        embed.add_field(name="Hesap Kurulum Tarihi", value=member.created_at.strftime("%d-%m-%Y %H:%M"), inline=False)
        
        # Check warnings via DB service
        msg = make_request("GET_WARNINGS", guild_id=interaction.guild.id, data={"target_user_id": member.id})
        resp = await self.cog.bot.request(Topic.DB, msg, timeout=5.0)
        warn_count = len(resp.data.get("warnings", [])) if resp and resp.data else 0
        embed.add_field(name="Uyarı Sayısı", value=str(warn_count), inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class RegistrationPanelView(discord.ui.View):
    def __init__(self, cog: RegistrationCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="📝 Kayıt Et", style=discord.ButtonStyle.success, custom_id="reg_panel_register")
    async def btn_register(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.check_staff(interaction):
            return await interaction.response.send_message("❌ Bu işlemi yapmak için yetkiniz yok.", ephemeral=True)
        await interaction.response.send_modal(RegistrationModal(self.cog))

    @discord.ui.button(label="👤 Sorgula", style=discord.ButtonStyle.primary, custom_id="reg_panel_query")
    async def btn_query(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.check_staff(interaction):
            return await interaction.response.send_message("❌ Bu işlemi yapmak için yetkiniz yok.", ephemeral=True)
        await interaction.response.send_modal(QueryModal(self.cog))

async def setup(bot: DiscordBot):
    """Load the RegistrationCog."""
    cog = RegistrationCog(bot)
    await bot.add_cog(cog)
    bot.add_view(RegistrationPanelView(cog))
    log.info("RegistrationCog loaded.")
