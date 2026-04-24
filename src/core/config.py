"""
Discord Bot — Central Configuration

Loads settings from config.yaml and .env with environment variable overrides.
Validated at import time — missing critical vars emit warnings.

Usage:
    from src.core.config import cfg, DISCORD_TOKEN, ZMQ_HOST
"""

import os
import sys
import logging

import yaml
from dotenv import load_dotenv

log = logging.getLogger("discord_bot.config")

# ── Paths ──────────────────────────────────────────────────────────────────
# src/core/config.py → src/core → src → project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ── YAML Config ────────────────────────────────────────────────────────────
_yaml_path = os.path.join(BASE_DIR, "config.yaml")
_raw: dict = {}

if os.path.isfile(_yaml_path):
    with open(_yaml_path, "r", encoding="utf-8") as f:
        _raw = yaml.safe_load(f) or {}
else:
    log.warning("config.yaml not found at %s — using defaults.", _yaml_path)


def _get(section: str, key: str, default=None, env_key: str | None = None):
    """Resolve a config value: ENV override → YAML → default."""
    if env_key and os.getenv(env_key):
        return os.getenv(env_key)
    return _raw.get(section, {}).get(key, default)


# ============================================================================
# DISCORD
# ============================================================================

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
DISCORD_GUILD_ID: int | None = (
    int(os.getenv("DISCORD_GUILD_ID"))
    if os.getenv("DISCORD_GUILD_ID")
    else None
)

BOT_PREFIX: str = _get("bot", "prefix", "!")
BOT_LANGUAGE: str = _get("bot", "default_language", "tr")
BOT_OWNER_IDS: list[int] = _get("bot", "owner_ids", [])

# ============================================================================
# ZEROMQ
# ============================================================================

ZMQ_HOST: str = _get("zmq", "host", "127.0.0.1")
ZMQ_PUB_PORT: int = int(_get("zmq", "pub_port", 5555))
ZMQ_PULL_PORT: int = int(_get("zmq", "pull_port", 5556))

# ============================================================================
# SERVICES
# ============================================================================

MUSIC_ENABLED: bool = _get("services", "music", {}).get("enabled", True) if isinstance(_get("services", "music", {}), dict) else True
MUSIC_MAX_QUEUE: int = _get("services", "music", {}).get("max_queue_size", 100) if isinstance(_get("services", "music", {}), dict) else 100
MUSIC_DEFAULT_VOLUME: int = _get("services", "music", {}).get("default_volume", 50) if isinstance(_get("services", "music", {}), dict) else 50

DB_ENABLED: bool = _get("services", "database", {}).get("enabled", True) if isinstance(_get("services", "database", {}), dict) else True
DB_PATH: str = _get("services", "database", {}).get("path", "data/bot.db") if isinstance(_get("services", "database", {}), dict) else "data/bot.db"
DB_FULL_PATH: str = os.path.join(BASE_DIR, DB_PATH)

# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL: str = os.getenv("LOG_LEVEL", _get("logging", "level", "INFO")).upper()
LOG_DIR: str = os.path.join(BASE_DIR, _get("logging", "dir", "logs"))
LOG_FILE: str = os.path.join(LOG_DIR, _get("logging", "file", "bot.log"))
LOG_MAX_BYTES: int = int(_get("logging", "max_bytes", 5 * 1024 * 1024))
LOG_BACKUP_COUNT: int = int(_get("logging", "backup_count", 3))

# ============================================================================
# ORCHESTRATOR
# ============================================================================

WATCHDOG_INTERVAL: int = int(_get("orchestrator", "watchdog_interval", 2))
MAX_RESTARTS_PER_MIN: int = int(_get("orchestrator", "max_restarts_per_min", 5))

# ============================================================================
# VALIDATION
# ============================================================================

def _validate_env():
    """Check critical environment variables at import time."""
    required = {
        "DISCORD_TOKEN": "Required for bot authentication",
    }
    missing = []
    for key, desc in required.items():
        if not os.getenv(key) or os.getenv(key) == "your_bot_token_here":
            missing.append(f"  {key}: {desc}")

    if missing:
        log.warning("=" * 60)
        log.warning("MISSING REQUIRED ENVIRONMENT VARIABLES:")
        for line in missing:
            log.warning(line)
        log.warning("Copy .env.example to .env and fill in your values.")
        log.warning("=" * 60)


_validate_env()


# ============================================================================
# FULL CONFIG DICT (for runtime inspection)
# ============================================================================

def get_config_dict() -> dict:
    """Return all configuration as a nested dictionary."""
    return {
        "discord": {
            "token": DISCORD_TOKEN[:8] + "..." if DISCORD_TOKEN else "",
            "guild_id": DISCORD_GUILD_ID,
            "prefix": BOT_PREFIX,
            "language": BOT_LANGUAGE,
        },
        "zmq": {
            "host": ZMQ_HOST,
            "pub_port": ZMQ_PUB_PORT,
            "pull_port": ZMQ_PULL_PORT,
        },
        "services": {
            "music_enabled": MUSIC_ENABLED,
            "db_enabled": DB_ENABLED,
            "db_path": DB_PATH,
        },
        "logging": {
            "level": LOG_LEVEL,
            "dir": LOG_DIR,
        },
    }
