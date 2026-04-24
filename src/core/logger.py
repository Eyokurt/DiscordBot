"""
Discord Bot — Centralized Logging Factory

Adapted from the Centrum logger pattern.
All loggers are children of the 'discord_bot' namespace.

Usage:
    from src.core.logger import get_logger
    log = get_logger("music")       # → discord_bot.music
    log.info("Service started")
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

from src.core.config import LOG_LEVEL, LOG_DIR, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT

# ── Formatter ──────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── Singleton ──────────────────────────────────────────────────────────────
_initialized = False


def _setup_root():
    """One-time root logger configuration (called on first get_logger)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler (stdout with UTF-8 encoding for Windows compatibility)
    import io
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    console = logging.StreamHandler(utf8_stdout)
    console.setFormatter(formatter)

    # File handler (rotating)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
    except OSError:
        file_handler = None

    root = logging.getLogger("discord_bot")
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root.addHandler(console)
    if file_handler:
        root.addHandler(file_handler)

    # Prevent duplicate propagation
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the 'discord_bot' namespace.

    Examples:
        get_logger("core")     → discord_bot.core
        get_logger("music")    → discord_bot.music
        get_logger("db")       → discord_bot.db
    """
    _setup_root()
    return logging.getLogger(f"discord_bot.{name}")
