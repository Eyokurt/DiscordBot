"""
Discord Bot — Music Commands Cog

Handles actual audio playback via FFmpegPCMAudio + queue management
through the Music Worker Service via ZMQ.

Commands:
    /çal <şarkı>   — Search and play a track
    /geç            — Skip current track
    /dur            — Stop playback and disconnect
    /kuyruk         — Show the current queue
    /ses <seviye>   — Set the volume
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord import app_commands

from src.core.logger import get_logger
from src.core.protocol import Topic, make_request, make_command

if TYPE_CHECKING:
    from src.bot.bot import DiscordBot

log = get_logger("cog.music")

# yt-dlp extraction options (run at play-time to get fresh stream URL)
YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    "nocheckcertificate": True,
}

# FFmpeg options for audio streaming
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -af loudnorm",
}


class MusicCog(commands.Cog, name="Müzik"):
    def __init__(self, bot: DiscordBot):
        self.bot = bot
        # Per-guild volume: guild_id → float (0.0 - 1.0)
        self._volumes: dict[int, float] = {}
        # Per-guild now-playing info
        self._now_playing: dict[int, dict] = {}

    def _get_volume(self, guild_id: int) -> float:
        return self._volumes.get(guild_id, 0.5)

    # ── Voice Helpers ──────────────────────────────────────────────────

    async def _ensure_voice(self, interaction: discord.Interaction):
        """Ensure bot is connected to the user's voice channel."""
        if not interaction.user.voice:
            await interaction.response.send_message("❌ Önce bir ses kanalına katılın!", ephemeral=True)
            return None
        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        if vc:
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        try:
            return await channel.connect()
        except Exception as e:
            log.error("Voice connect error: %s", e)
            await interaction.response.send_message("❌ Ses kanalına bağlanılamadı.", ephemeral=True)
            return None

    async def _play_track(self, guild: discord.Guild, track: dict):
        """
        Actually stream audio to the voice channel using FFmpeg.

        Uses yt-dlp to extract a fresh stream URL, then plays it
        through discord.py's FFmpegPCMAudio with volume control.
        """
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            log.warning("Cannot play — not connected to voice (guild=%s)", guild.id)
            return

        url = track.get("url", "")
        title = track.get("title", "Bilinmeyen")

        if not url:
            log.warning("Track has no URL: %s", title)
            return

        log.info("Playing: '%s' in guild %s", title, guild.id)

        try:
            # Extract fresh stream URL via yt-dlp (URLs expire quickly)
            stream_url = await self._extract_stream_url(url)
            if not stream_url:
                log.error("Failed to extract stream URL for: %s", url)
                return

            # Create FFmpeg audio source with volume control
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS)
            source = discord.PCMVolumeTransformer(source, volume=self._get_volume(guild.id))

            # Store now-playing info
            self._now_playing[guild.id] = track

            # Play with after-callback for queue advancement
            def after_callback(error):
                if error:
                    log.error("Playback error: %s", error)
                # Schedule next track on the bot's event loop
                asyncio.run_coroutine_threadsafe(
                    self._play_next(guild), self.bot.loop
                )

            vc.play(source, after=after_callback)
            log.info("Now playing: '%s' (guild=%s)", title, guild.id)

        except Exception as e:
            log.error("Failed to play '%s': %s", title, e, exc_info=True)

    async def _extract_stream_url(self, url: str) -> str | None:
        """Extract a direct audio stream URL using yt-dlp (async-safe)."""
        try:
            import yt_dlp
        except ImportError:
            log.error("yt-dlp not installed. Run: pip install yt-dlp")
            return None

        def _extract():
            try:
                with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        # If it's a search result, get first entry
                        if "entries" in info:
                            info = info["entries"][0]
                        return info.get("url") or info.get("webpage_url")
            except Exception as e:
                log.error("yt-dlp extract error: %s", e)
                return None

        # Run in thread pool to avoid blocking the event loop
        return await self.bot.loop.run_in_executor(None, _extract)

    async def _play_next(self, guild: discord.Guild):
        """Advance the queue and play the next track."""
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            self._now_playing.pop(guild.id, None)
            return

        # Ask music worker for the next track
        msg = make_request("SKIP_TRACK", guild_id=guild.id)
        response = await self.bot.request(Topic.MUSIC, msg, timeout=5.0)

        if response and response.data.get("success"):
            track = response.data.get("track")
            if track:
                await self._play_track(guild, track)
                return

        # No more tracks — clear state
        self._now_playing.pop(guild.id, None)
        log.info("Queue ended (guild=%s)", guild.id)

    # ── Slash Commands ─────────────────────────────────────────────────

    @app_commands.command(name="çal", description="Bir şarkı arar ve çalar")
    @app_commands.describe(şarkı="Şarkı adı veya YouTube URL'si")
    async def play(self, interaction: discord.Interaction, şarkı: str):
        """Search for a track, add to queue, and start playback if idle."""
        voice = await self._ensure_voice(interaction)
        if not voice:
            return

        await interaction.response.defer()

        # Search via music worker
        msg = make_request(
            "SEARCH_MUSIC",
            data={"query": şarkı},
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        response = await self.bot.request(Topic.MUSIC, msg, timeout=15.0)

        if not response or not response.data.get("success"):
            error = response.data.get("error", "Bilinmeyen hata") if response else "Servis yanıt vermedi"
            await interaction.followup.send(f"❌ {error}")
            return

        track = response.data["track"]

        # Add to queue via music worker
        queue_msg = make_request(
            "ADD_TO_QUEUE",
            data={"track": track},
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        queue_response = await self.bot.request(Topic.MUSIC, queue_msg, timeout=5.0)
        position = queue_response.data.get("position", 1) if queue_response else 1

        # Build response embed
        embed = discord.Embed(
            title="🎵 Şarkı Eklendi" if voice.is_playing() else "🎵 Şimdi Çalınıyor",
            color=discord.Color.from_str("#1DB954"),
        )
        embed.add_field(name="Şarkı", value=track.get("title", "Bilinmeyen"), inline=False)
        duration = track.get("duration", 0)
        if duration:
            m, s = divmod(duration, 60)
            embed.add_field(name="Süre", value=f"{m}:{s:02d}", inline=True)
        embed.add_field(name="İsteyen", value=interaction.user.mention, inline=True)
        if voice.is_playing():
            embed.add_field(name="Sıra", value=f"#{position}", inline=True)
        if track.get("thumbnail"):
            embed.set_thumbnail(url=track["thumbnail"])

        await interaction.followup.send(embed=embed)

        # If nothing is playing, start playback immediately
        if not voice.is_playing() and not voice.is_paused():
            await self._play_track(interaction.guild, track)

    @app_commands.command(name="geç", description="Şu anki şarkıyı geçer")
    async def skip(self, interaction: discord.Interaction):
        """Skip the current track — the after-callback handles the next one."""
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ Çalan şarkı yok.", ephemeral=True)
            return

        # Stopping triggers the after_callback which calls _play_next
        vc.stop()

        embed = discord.Embed(title="⏭️ Geçildi", description="Sıradaki şarkıya geçiliyor...", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dur", description="Müziği durdurur ve ayrılır")
    async def stop(self, interaction: discord.Interaction):
        """Stop playback, clear queue, and disconnect."""
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Bot ses kanalında değil.", ephemeral=True)
            return

        # Clear queue via ZMQ
        await self.bot.fire_and_forget(
            Topic.MUSIC,
            make_command("CLEAR_QUEUE", guild_id=interaction.guild_id),
        )

        # Clear local state
        self._now_playing.pop(interaction.guild_id, None)

        # Stop and disconnect
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()

        embed = discord.Embed(
            title="⏹️ Durduruldu",
            description="Kuyruk temizlendi ve ses kanalından ayrıldı.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kuyruk", description="Müzik kuyruğunu gösterir")
    async def queue(self, interaction: discord.Interaction):
        """Display the current music queue."""
        msg = make_request("GET_QUEUE", guild_id=interaction.guild_id, user_id=interaction.user.id)
        response = await self.bot.request(Topic.MUSIC, msg, timeout=5.0)
        if not response:
            await interaction.response.send_message("❌ Servis yanıt vermedi.", ephemeral=True)
            return
        tracks = response.data.get("tracks", [])
        if not tracks:
            await interaction.response.send_message("📭 Kuyruk boş.", ephemeral=True)
            return

        ci = response.data.get("current_index", 0)
        lines = []
        for i, t in enumerate(tracks[:15]):
            pfx = "▶️" if i == ci else f"`{i+1}.`"
            dur = t.get("duration", 0)
            ds = f" `[{dur//60}:{dur%60:02d}]`" if dur else ""
            lines.append(f"{pfx} **{t['title']}**{ds}")

        embed = discord.Embed(title="🎶 Kuyruk", description="\n".join(lines), color=discord.Color.from_str("#1DB954"))
        if len(tracks) > 15:
            embed.set_footer(text=f"... ve {len(tracks)-15} şarkı daha")

        # Now playing info
        np = self._now_playing.get(interaction.guild_id)
        if np:
            embed.add_field(name="▶️ Şu An", value=np.get("title", "?"), inline=False)

        embed.add_field(name="🔊 Ses", value=f"{int(self._get_volume(interaction.guild_id)*100)}%", inline=True)
        embed.add_field(name="📋 Toplam", value=str(len(tracks)), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ses", description="Ses seviyesini ayarlar (0-100)")
    @app_commands.describe(seviye="Ses seviyesi")
    async def volume(self, interaction: discord.Interaction, seviye: int):
        """Set the playback volume."""
        if not 0 <= seviye <= 100:
            await interaction.response.send_message("❌ 0-100 arası olmalı.", ephemeral=True)
            return

        vol = seviye / 100
        self._volumes[interaction.guild_id] = vol

        # Update live playback volume
        vc = interaction.guild.voice_client
        if vc and vc.source and hasattr(vc.source, "volume"):
            vc.source.volume = vol

        # Sync to music worker
        await self.bot.fire_and_forget(
            Topic.MUSIC,
            make_command("SET_VOLUME", data={"volume": seviye}, guild_id=interaction.guild_id),
        )

        emoji = "🔇" if seviye == 0 else "🔈" if seviye < 30 else "🔉" if seviye < 70 else "🔊"
        await interaction.response.send_message(f"{emoji} Ses: **{seviye}%**")

    # ── Auto-disconnect on empty channel ───────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Disconnect if the bot is left alone in a voice channel."""
        if member.bot:
            return
        vc = member.guild.voice_client
        if not vc or not vc.is_connected():
            return
        # If the bot's channel now has only the bot
        if len(vc.channel.members) == 1:
            log.info("Voice channel empty, disconnecting (guild=%s)", member.guild.id)
            await self.bot.fire_and_forget(
                Topic.MUSIC,
                make_command("CLEAR_QUEUE", guild_id=member.guild.id),
            )
            self._now_playing.pop(member.guild.id, None)
            await vc.disconnect()


async def setup(bot: DiscordBot):
    await bot.add_cog(MusicCog(bot))
    log.info("MusicCog loaded.")
