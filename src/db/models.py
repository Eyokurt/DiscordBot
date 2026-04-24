"""
Discord Bot — Data Models

Typed dataclasses representing domain objects.
These are used for type-safe data exchange between services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GuildSettings:
    """Represents a Discord guild's bot configuration."""
    guild_id: int
    prefix: str = "!"
    language: str = "tr"
    welcome_channel_id: int | None = None
    welcome_message: str = "Sunucuya hoş geldin, {user}! 🎉"
    goodbye_channel_id: int | None = None
    goodbye_message: str = "{user} aramızdan ayrıldı. 👋"
    dj_role_id: int | None = None
    mod_log_channel_id: int | None = None
    auto_role_id: int | None = None
    music_volume: int = 50

    @classmethod
    def from_dict(cls, d: dict) -> GuildSettings:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    # Human-readable field names (for Discord UI)
    FIELD_LABELS = {
        "prefix": "Komut Prefix'i",
        "language": "Dil",
        "welcome_channel_id": "Hoşgeldin Kanalı",
        "welcome_message": "Hoşgeldin Mesajı",
        "goodbye_channel_id": "Veda Kanalı",
        "goodbye_message": "Veda Mesajı",
        "dj_role_id": "DJ Rolü",
        "mod_log_channel_id": "Mod Log Kanalı",
        "auto_role_id": "Otomatik Rol",
        "music_volume": "Müzik Ses Seviyesi",
    }


@dataclass
class UserSettings:
    """Represents a user's per-guild preferences."""
    user_id: int
    guild_id: int
    notifications_enabled: bool = True
    custom_color: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> UserSettings:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Warning:
    """Represents a moderation warning."""
    id: int | None = None
    guild_id: int = 0
    user_id: int = 0
    mod_id: int = 0
    reason: str = ""
    created_at: str = ""


@dataclass
class MusicTrack:
    """Represents a music track in the queue."""
    title: str
    url: str
    duration: int = 0  # seconds
    requester_id: int = 0
    guild_id: int = 0


@dataclass
class MusicQueue:
    """Per-guild music queue state."""
    guild_id: int
    tracks: list[MusicTrack] = field(default_factory=list)
    current_index: int = 0
    volume: int = 50
    is_playing: bool = False
    is_looping: bool = False

    @property
    def current_track(self) -> MusicTrack | None:
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def add(self, track: MusicTrack):
        self.tracks.append(track)

    def skip(self) -> MusicTrack | None:
        self.current_index += 1
        return self.current_track

    def clear(self):
        self.tracks.clear()
        self.current_index = 0
