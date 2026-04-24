"""
Discord Bot — Database Connection & Schema Management

Provides an async SQLite database interface with automatic table creation.
Uses aiosqlite for non-blocking I/O compatible with asyncio.

Usage (async context):
    db = Database()
    await db.initialize()
    row = await db.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    await db.close()

Usage (sync context — for DB worker service):
    db = Database()
    db.initialize_sync()
    row = db.fetchone_sync("SELECT ...", (param,))
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

import aiosqlite

from src.core.config import DB_FULL_PATH
from src.core.logger import get_logger

log = get_logger("db")

# ── Schema Definitions ────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Guild-specific settings (one row per Discord server)
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id        INTEGER PRIMARY KEY,
    prefix          TEXT DEFAULT '!',
    language        TEXT DEFAULT 'tr',
    welcome_channel_id  INTEGER,
    welcome_message TEXT DEFAULT 'Sunucuya hoş geldin, {user}! 🎉',
    goodbye_channel_id  INTEGER,
    goodbye_message TEXT DEFAULT '{user} aramızdan ayrıldı. 👋',
    dj_role_id      INTEGER,
    mod_log_channel_id  INTEGER,
    auto_role_id    INTEGER,
    music_volume    INTEGER DEFAULT 50,
    unregistered_role_id INTEGER,
    registered_role_id   INTEGER,
    staff_role_id        INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User-specific settings (per guild per user)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id                 INTEGER NOT NULL,
    guild_id                INTEGER NOT NULL,
    notifications_enabled   BOOLEAN DEFAULT 1,
    custom_color            TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

-- Warning system
CREATE TABLE IF NOT EXISTS warnings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    mod_id      INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    message_link TEXT,
    message_content TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Music queue persistence (optional)
CREATE TABLE IF NOT EXISTS music_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    duration    INTEGER,
    played_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Triggers for auto-updating updated_at
CREATE TRIGGER IF NOT EXISTS guild_settings_update
    AFTER UPDATE ON guild_settings
    FOR EACH ROW
BEGIN
    UPDATE guild_settings SET updated_at = CURRENT_TIMESTAMP WHERE guild_id = OLD.guild_id;
END;

CREATE TRIGGER IF NOT EXISTS user_settings_update
    AFTER UPDATE ON user_settings
    FOR EACH ROW
BEGIN
    UPDATE user_settings SET updated_at = CURRENT_TIMESTAMP
    WHERE user_id = OLD.user_id AND guild_id = OLD.guild_id;
END;
"""


class Database:
    """
    Async/sync SQLite database wrapper with automatic schema migration.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_FULL_PATH
        self._async_conn: aiosqlite.Connection | None = None
        self._sync_conn: sqlite3.Connection | None = None

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    # ── Async Interface ────────────────────────────────────────────────

    async def initialize(self):
        """Open async connection and create tables."""
        self._async_conn = await aiosqlite.connect(self.db_path)
        self._async_conn.row_factory = aiosqlite.Row
        await self._async_conn.executescript(SCHEMA_SQL)
        
        # Migrations for new columns
        for col in ["unregistered_role_id", "registered_role_id", "staff_role_id"]:
            try:
                await self._async_conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass
                
        try:
            await self._async_conn.execute("ALTER TABLE warnings ADD COLUMN message_link TEXT")
        except sqlite3.OperationalError:
            pass
            
        try:
            await self._async_conn.execute("ALTER TABLE warnings ADD COLUMN message_content TEXT")
        except sqlite3.OperationalError:
            pass

        await self._async_conn.commit()
        log.info("Database initialized (async): %s", self.db_path)

    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self._async_conn.execute(query, params)

    async def executemany(self, query: str, params_list: list[tuple]):
        await self._async_conn.executemany(query, params_list)
        await self._async_conn.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        cursor = await self._async_conn.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        cursor = await self._async_conn.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def commit(self):
        await self._async_conn.commit()

    async def close(self):
        if self._async_conn:
            await self._async_conn.close()
            self._async_conn = None

    # ── Sync Interface (for DB worker service) ─────────────────────────

    def initialize_sync(self):
        """Open sync connection and create tables."""
        self._sync_conn = sqlite3.connect(self.db_path)
        self._sync_conn.row_factory = sqlite3.Row
        self._sync_conn.executescript(SCHEMA_SQL)

        # Migrations for new columns
        for col in ["unregistered_role_id", "registered_role_id", "staff_role_id"]:
            try:
                self._sync_conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass
                
        try:
            self._sync_conn.execute("ALTER TABLE warnings ADD COLUMN message_link TEXT")
        except sqlite3.OperationalError:
            pass
            
        try:
            self._sync_conn.execute("ALTER TABLE warnings ADD COLUMN message_content TEXT")
        except sqlite3.OperationalError:
            pass

        self._sync_conn.commit()
        log.info("Database initialized (sync): %s", self.db_path)

    def execute_sync(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        cursor = self._sync_conn.execute(query, params)
        self._sync_conn.commit()
        return cursor

    def fetchone_sync(self, query: str, params: tuple = ()) -> dict | None:
        cursor = self._sync_conn.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def fetchall_sync(self, query: str, params: tuple = ()) -> list[dict]:
        cursor = self._sync_conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

    def close_sync(self):
        if self._sync_conn:
            self._sync_conn.close()
            self._sync_conn = None

    # ── Guild Settings Helpers ─────────────────────────────────────────

    async def get_guild_settings(self, guild_id: int) -> dict:
        """Get or create guild settings row."""
        row = await self.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        if not row:
            await self.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
            )
            await self.commit()
            row = await self.fetchone(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
        return row

    async def update_guild_setting(self, guild_id: int, key: str, value: Any):
        """Update a single guild setting by column name."""
        # Whitelist columns to prevent SQL injection
        allowed = {
            "prefix", "language", "welcome_channel_id", "welcome_message",
            "goodbye_channel_id", "goodbye_message", "dj_role_id",
            "mod_log_channel_id", "auto_role_id", "music_volume",
            "unregistered_role_id", "registered_role_id", "staff_role_id",
        }
        if key not in allowed:
            raise ValueError(f"Invalid setting key: {key}")
        await self.execute(
            f"INSERT INTO guild_settings (guild_id, {key}) VALUES (?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {key} = ?",
            (guild_id, value, value),
        )
        await self.commit()

    def get_guild_settings_sync(self, guild_id: int) -> dict:
        """Sync version of get_guild_settings."""
        row = self.fetchone_sync(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        if not row:
            self.execute_sync(
                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
            )
            row = self.fetchone_sync(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
        return row

    def update_guild_setting_sync(self, guild_id: int, key: str, value: Any):
        """Sync version of update_guild_setting."""
        allowed = {
            "prefix", "language", "welcome_channel_id", "welcome_message",
            "goodbye_channel_id", "goodbye_message", "dj_role_id",
            "mod_log_channel_id", "auto_role_id", "music_volume",
            "unregistered_role_id", "registered_role_id", "staff_role_id",
        }
        if key not in allowed:
            raise ValueError(f"Invalid setting key: {key}")
        self.execute_sync(
            f"INSERT INTO guild_settings (guild_id, {key}) VALUES (?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {key} = ?",
            (guild_id, value, value),
        )
