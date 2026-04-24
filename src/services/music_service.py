"""
Discord Bot — Music Worker Service

Handles music-related workload as an independent ZMQ worker.
Manages per-guild music queues, search, and metadata extraction.

NOTE: This is the ZMQ skeleton. Voice channel connection and audio
streaming are handled by the music_cog in the bot process since
discord.py voice requires the bot's event loop.

Supported actions:
    SEARCH_MUSIC     — Search for a track (yt-dlp metadata)
    GET_QUEUE        — Return current queue for a guild
    ADD_TO_QUEUE     — Add track to a guild's queue
    SKIP_TRACK       — Skip current track
    CLEAR_QUEUE      — Clear a guild's queue
    SET_VOLUME       — Set playback volume

Usage:
    python -m src.services.music_service
"""

from __future__ import annotations

import sys
import os
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.services.base_service import BaseWorker
from src.core.protocol import ZMQMessage, Topic, make_response
from src.db.models import MusicTrack, MusicQueue


class MusicService(BaseWorker):
    """Music worker — manages queues and metadata extraction."""

    def __init__(self):
        super().__init__("music", [Topic.MUSIC])

        # Per-guild music queues: guild_id → MusicQueue
        self._queues: dict[int, MusicQueue] = {}

    def _get_queue(self, guild_id: int) -> MusicQueue:
        """Get or create a queue for a guild."""
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue(guild_id=guild_id)
        return self._queues[guild_id]

    def handle_message(self, topic: str, message: ZMQMessage):
        """Route incoming MUSIC messages to handlers."""
        action = message.action
        handler = getattr(self, f"_handle_{action.lower()}", None)

        if handler:
            handler(message)
        else:
            self.log.warning("Unknown MUSIC action: %s", action)

    # ── Action Handlers ────────────────────────────────────────────────

    def _handle_search_music(self, msg: ZMQMessage):
        """Search for a track using yt-dlp and return metadata."""
        query = msg.data.get("query", "")
        guild_id = msg.guild_id

        if not query:
            response = make_response(msg, data={"success": False, "error": "Arama sorgusu boş."})
            self.ebus.publish(Topic.BOT, response)
            return

        self.log.info("Searching: '%s' (guild=%s)", query, guild_id)

        try:
            # yt-dlp search (extract info without downloading)
            track_info = self._search_ytdlp(query)

            if track_info:
                response = make_response(msg, data={
                    "success": True,
                    "track": track_info,
                })
            else:
                response = make_response(msg, data={
                    "success": False,
                    "error": "Şarkı bulunamadı.",
                })
        except Exception as e:
            self.log.error("Search error: %s", e)
            response = make_response(msg, data={
                "success": False,
                "error": f"Arama hatası: {e}",
            })

        self.ebus.publish(Topic.BOT, response)

    def _handle_add_to_queue(self, msg: ZMQMessage):
        """Add a track to the guild's queue."""
        guild_id = msg.guild_id
        track_data = msg.data.get("track", {})

        track = MusicTrack(
            title=track_data.get("title", "Bilinmeyen"),
            url=track_data.get("url", ""),
            duration=track_data.get("duration", 0),
            requester_id=msg.user_id,
            guild_id=guild_id,
        )

        queue = self._get_queue(guild_id)
        queue.add(track)

        response = make_response(msg, data={
            "success": True,
            "position": len(queue.tracks),
            "track_title": track.title,
        })
        self.ebus.publish(Topic.BOT, response)
        self.log.info("Track added: '%s' → queue #%d (guild=%s)", track.title, len(queue.tracks), guild_id)

    def _handle_get_queue(self, msg: ZMQMessage):
        """Return the current queue for a guild."""
        guild_id = msg.guild_id
        queue = self._get_queue(guild_id)

        tracks = [
            {
                "title": t.title,
                "url": t.url,
                "duration": t.duration,
                "requester_id": t.requester_id,
            }
            for t in queue.tracks
        ]

        response = make_response(msg, data={
            "tracks": tracks,
            "current_index": queue.current_index,
            "is_playing": queue.is_playing,
            "volume": queue.volume,
        })
        self.ebus.publish(Topic.BOT, response)

    def _handle_skip_track(self, msg: ZMQMessage):
        """Skip to the next track in the queue."""
        guild_id = msg.guild_id
        queue = self._get_queue(guild_id)
        next_track = queue.skip()

        if next_track:
            response = make_response(msg, data={
                "success": True,
                "track": {
                    "title": next_track.title,
                    "url": next_track.url,
                    "duration": next_track.duration,
                },
            })
        else:
            response = make_response(msg, data={
                "success": False,
                "error": "Kuyrukta başka şarkı yok.",
            })

        self.ebus.publish(Topic.BOT, response)

    def _handle_clear_queue(self, msg: ZMQMessage):
        """Clear the guild's music queue."""
        guild_id = msg.guild_id
        queue = self._get_queue(guild_id)
        count = len(queue.tracks)
        queue.clear()

        response = make_response(msg, data={
            "success": True,
            "cleared_count": count,
        })
        self.ebus.publish(Topic.BOT, response)
        self.log.info("Queue cleared: %d tracks removed (guild=%s)", count, guild_id)

    def _handle_set_volume(self, msg: ZMQMessage):
        """Set the playback volume for a guild."""
        guild_id = msg.guild_id
        volume = msg.data.get("volume", 50)
        volume = max(0, min(100, int(volume)))

        queue = self._get_queue(guild_id)
        queue.volume = volume

        response = make_response(msg, data={
            "success": True,
            "volume": volume,
        })
        self.ebus.publish(Topic.BOT, response)

    # ── yt-dlp Integration ─────────────────────────────────────────────

    def _search_ytdlp(self, query: str) -> dict | None:
        """
        Search YouTube using yt-dlp and return track metadata.

        Returns:
            dict with keys: title, url, duration, thumbnail
            or None if not found.
        """
        try:
            import yt_dlp
        except ImportError:
            self.log.warning("yt-dlp not installed. Install with: pip install yt-dlp")
            return {
                "title": query,
                "url": f"https://www.youtube.com/results?search_query={query}",
                "duration": 0,
                "thumbnail": "",
            }

        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch",
            "extract_flat": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                if info and "entries" in info and info["entries"]:
                    entry = info["entries"][0]
                    return {
                        "title": entry.get("title", query),
                        "url": entry.get("webpage_url", ""),
                        "duration": entry.get("duration", 0),
                        "thumbnail": entry.get("thumbnail", ""),
                    }
        except Exception as e:
            self.log.error("yt-dlp extraction error: %s", e)

        return None


def run_music_service():
    """Entry point for the music worker process."""
    service = MusicService()
    service.run()


if __name__ == "__main__":
    run_music_service()
