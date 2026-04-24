"""
Discord Bot — Role Selection Cog

Provides a persistent panel for users to select their gender, name color, and games/interests.
Uses Discord UI Select menus.
"""

from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger

try:
    from src.bot.bot import DiscordBot
except ImportError:
    DiscordBot = discord.ext.commands.Bot

log = get_logger("cog.roles")

# ── Role Handlers ────────────────────────────────────────────────────────

async def handle_role_selection(
    interaction: discord.Interaction, 
    selected_names: list[str], 
    category: str, 
    all_options: list[discord.SelectOption]
):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    member = interaction.user
    
    category_role_names = [opt.label for opt in all_options]
    
    roles_to_add = []
    roles_to_remove = []
    
    color_map = {
        "Kırmızı": discord.Color.red(),
        "Mavi": discord.Color.blue(),
        "Yeşil": discord.Color.green(),
        "Sarı": discord.Color.gold(),
        "Mor": discord.Color.purple(),
        "Turuncu": discord.Color.orange(),
        "Siyah": discord.Color.from_rgb(10, 10, 10),
        "Beyaz": discord.Color.from_rgb(255, 255, 255),
    }
    
    for role_name in selected_names:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            color = color_map.get(role_name, discord.Color.default())
            try:
                role = await guild.create_role(
                    name=role_name, 
                    color=color,
                    reason=f"Rol alma sistemi ({category}) için otomatik oluşturuldu."
                )
                log.info("Created missing role: %s in guild %s", role_name, guild.id)
            except discord.Forbidden:
                return await interaction.followup.send("❌ Roller sunucuda yok ve botun yeni rol oluşturma yetkisi yok (Rolleri Yönet yetkisi gerekli).", ephemeral=True)
            except Exception as e:
                log.error("Failed to create role %s: %s", role_name, e)
                return await interaction.followup.send("❌ Yeni rol oluşturulurken bir hata meydana geldi.", ephemeral=True)
                
        if role not in member.roles:
            roles_to_add.append(role)
            
    for role_name in category_role_names:
        if role_name not in selected_names:
            role = discord.utils.get(guild.roles, name=role_name)
            if role and role in member.roles:
                roles_to_remove.append(role)

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f"{category} rolleri güncellendi")
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason=f"{category} rolleri güncellendi")
            
        await interaction.followup.send(f"✅ {category} rolleriniz başarıyla güncellendi!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Roller verilemedi. Botun 'Rolleri Yönet' yetkisi yetersiz veya verilmek istenen rol botun rolünden daha üstte.", ephemeral=True)
    except Exception as e:
        log.error("Error giving roles: %s", e)
        await interaction.followup.send("❌ Beklenmeyen bir hata oluştu.", ephemeral=True)


# ── UI Classes ─────────────────────────────────────────────────────────────

class GameSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Anime", emoji="🌸"),
            discord.SelectOption(label="Sanatçı", emoji="🎨"),
            discord.SelectOption(label="Counter-Strike 2", emoji="🔫"),
            discord.SelectOption(label="Valorant", emoji="🎯"),
            discord.SelectOption(label="Minecraft", emoji="⛏️"),
            discord.SelectOption(label="League of Legends", emoji="⚔️"),
            discord.SelectOption(label="Team Fight Tactics", emoji="♟️"),
            discord.SelectOption(label="Team Fortress 2", emoji="🎩"),
            discord.SelectOption(label="Rust", emoji="🏕️"),
            discord.SelectOption(label="Baloons TD 6", emoji="🎈"),
            discord.SelectOption(label="The Forest", emoji="🌲"),
            discord.SelectOption(label="Sons The Forest", emoji="🌳"),
            discord.SelectOption(label="Feign", emoji="🎭"),
            discord.SelectOption(label="Peak", emoji="⛰️"),
        ]
        super().__init__(
            placeholder="Oyun ve İlgi Alanları Seçin...", 
            min_values=0, 
            max_values=len(options), 
            options=options, 
            custom_id="role_select_games"
        )

    async def callback(self, interaction: discord.Interaction):
        await handle_role_selection(interaction, self.values, "Oyun/İlgi Alanı", self.options)

class ColorSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Kırmızı", emoji="🔴"),
            discord.SelectOption(label="Mavi", emoji="🔵"),
            discord.SelectOption(label="Yeşil", emoji="🟢"),
            discord.SelectOption(label="Sarı", emoji="🟡"),
            discord.SelectOption(label="Mor", emoji="🟣"),
            discord.SelectOption(label="Turuncu", emoji="🟠"),
            discord.SelectOption(label="Siyah", emoji="⚫"),
            discord.SelectOption(label="Beyaz", emoji="⚪"),
        ]
        super().__init__(
            placeholder="Renk Seçin...", 
            min_values=0, 
            max_values=1, 
            options=options, 
            custom_id="role_select_colors"
        )

    async def callback(self, interaction: discord.Interaction):
        await handle_role_selection(interaction, self.values, "Renk", self.options)

class GenderSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Erkek", emoji="👨"),
            discord.SelectOption(label="Kadın", emoji="👩"),
            discord.SelectOption(label="Belirtmek İstemiyorum", emoji="👤"),
        ]
        super().__init__(
            placeholder="Cinsiyet Seçin...", 
            min_values=0, 
            max_values=1, 
            options=options, 
            custom_id="role_select_gender"
        )

    async def callback(self, interaction: discord.Interaction):
        await handle_role_selection(interaction, self.values, "Cinsiyet", self.options)

class RoleSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GenderSelect())
        self.add_item(ColorSelect())
        self.add_item(GameSelect())


# ── Cog ────────────────────────────────────────────────────────────────────

class RolesCog(commands.Cog, name="Rol Alma Sistemi"):
    def __init__(self, bot: DiscordBot):
        self.bot = bot

    @app_commands.command(name="rol-alma", description="Rol seçme menüsünü gönderir.")
    @app_commands.default_permissions(manage_guild=True)
    async def spawn_role_panel(self, interaction: discord.Interaction):
        """Rol alma panelini kanala bırakır."""
        if not interaction.guild:
            return await interaction.response.send_message("Sadece sunucularda çalışır.", ephemeral=True)
            
        embed = discord.Embed(
            title="🎭 Rol Seçim Paneli",
            description="Aşağıdaki menüleri kullanarak profilinizi kişiselleştirebilirsiniz.\n\n"
                        "🎨 **Renk Rolleri:** İsminizin rengini belirler (Sadece 1 tane seçebilirsiniz).\n"
                        "⚧️ **Cinsiyet Rolleri:** Cinsiyetinizi belirtir (Sadece 1 tane seçebilirsiniz).\n"
                        "🎮 **Oyun & İlgi Alanları:** Oynadığınız oyunları ve ilgi alanlarınızı seçin.",
            color=discord.Color.purple()
        )
        embed.set_footer(text="İstediğiniz zaman seçimlerinizi menüden değiştirebilirsiniz.")
        
        view = RoleSelectionView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Rol seçim paneli oluşturuldu.", ephemeral=True)

async def setup(bot: DiscordBot):
    cog = RolesCog(bot)
    await bot.add_cog(cog)
    bot.add_view(RoleSelectionView())
    log.info("RolesCog loaded.")
