"""
Discord Bot — Message Protocol Definitions

Defines the standard message envelope used across all ZMQ communication.
All services speak this protocol — enforced via helper functions.

Multipart ZMQ frame layout:
    Frame 0: topic (bytes)   — e.g. b"MUSIC", b"DB", b"BOT"
    Frame 1: payload (bytes) — JSON-encoded ZMQMessage dict
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ── Topic Constants ────────────────────────────────────────────────────────

class Topic:
    """ZMQ topic namespace constants."""
    SYSTEM = "SYSTEM"       # Service lifecycle (READY, SHUTDOWN, HEARTBEAT)
    BOT    = "BOT"          # Messages targeting the Discord bot core
    MUSIC  = "MUSIC"        # Music service commands/responses
    DB     = "DB"           # Database service commands/responses
    SETTINGS = "SETTINGS"   # Settings change notifications


# ── Message Types ──────────────────────────────────────────────────────────

class MessageType(str, Enum):
    """Classifies the intent of a ZMQ message."""
    COMMAND  = "COMMAND"    # Request an action (fire-and-forget)
    REQUEST  = "REQUEST"    # Request expecting a RESPONSE
    RESPONSE = "RESPONSE"   # Reply to a REQUEST
    EVENT    = "EVENT"      # Broadcast notification


# ── Message Envelope ───────────────────────────────────────────────────────

@dataclass
class ZMQMessage:
    """
    Standard message envelope for all inter-service communication.

    Attributes:
        action:      The operation name (e.g. "PLAY_MUSIC", "SAVE_SETTING").
        msg_type:    One of MessageType values.
        data:        Arbitrary payload dict for the action.
        request_id:  UUID for correlating REQUEST → RESPONSE pairs.
        guild_id:    Discord guild context (0 if global).
        user_id:     Discord user who triggered the action (0 if system).
        source:      Name of the originating service.
        timestamp:   ISO-8601 creation time.
    """
    action: str
    msg_type: str = MessageType.COMMAND
    data: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    guild_id: int = 0
    user_id: int = 0
    source: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    # ── Serialization ──────────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        """Serialize to JSON bytes for ZMQ transmission."""
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> ZMQMessage:
        """Deserialize from JSON bytes received via ZMQ."""
        d = json.loads(raw.decode("utf-8"))
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ZMQMessage:
        return cls(**d)


# ── Factory Helpers ────────────────────────────────────────────────────────

def make_command(action: str, data: dict | None = None, **kwargs) -> ZMQMessage:
    """Create a fire-and-forget COMMAND message."""
    return ZMQMessage(
        action=action,
        msg_type=MessageType.COMMAND,
        data=data or {},
        **kwargs,
    )


def make_request(action: str, data: dict | None = None, **kwargs) -> ZMQMessage:
    """Create a REQUEST message expecting a RESPONSE."""
    return ZMQMessage(
        action=action,
        msg_type=MessageType.REQUEST,
        data=data or {},
        **kwargs,
    )


def make_response(request: ZMQMessage, data: dict | None = None, **kwargs) -> ZMQMessage:
    """Create a RESPONSE message correlated to the original REQUEST."""
    return ZMQMessage(
        action=request.action,
        msg_type=MessageType.RESPONSE,
        data=data or {},
        request_id=request.request_id,
        guild_id=request.guild_id,
        user_id=request.user_id,
        **kwargs,
    )


def make_event(action: str, data: dict | None = None, **kwargs) -> ZMQMessage:
    """Create a broadcast EVENT message."""
    return ZMQMessage(
        action=action,
        msg_type=MessageType.EVENT,
        data=data or {},
        **kwargs,
    )
