"""
Discord Bot — Database Worker Service

Handles all database operations as an independent ZMQ worker.
Receives DB commands from the bot/cogs and executes them synchronously.

This isolates all SQLite I/O in its own process, preventing the Discord
bot's asyncio loop from blocking on disk operations.

Supported actions:
    GET_GUILD_SETTINGS  — Fetch guild config
    SAVE_SETTING        — Update a single guild setting
    GET_WARNINGS        — Fetch warnings for a user
    ADD_WARNING         — Add a new warning
    DELETE_WARNING      — Remove a warning

Usage:
    python -m src.services.db_service
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.services.base_service import BaseWorker
from src.core.protocol import ZMQMessage, Topic, make_response, make_event
from src.db.database import Database


class DBService(BaseWorker):
    """Database worker — processes DB topic messages."""

    def __init__(self):
        super().__init__("db", [Topic.DB])
        self.db = Database()

    def setup(self):
        """Initialize the database connection and schema."""
        self.db.initialize_sync()
        self.log.info("Database connection established.")

    def teardown(self):
        """Close the database connection."""
        self.db.close_sync()
        self.log.info("Database connection closed.")

    def handle_message(self, topic: str, message: ZMQMessage):
        """Route incoming DB messages to the appropriate handler."""
        action = message.action
        handler = getattr(self, f"_handle_{action.lower()}", None)

        if handler:
            handler(message)
        else:
            self.log.warning("Unknown DB action: %s", action)

    # ── Action Handlers ────────────────────────────────────────────────

    def _handle_get_guild_settings(self, msg: ZMQMessage):
        """Fetch guild settings and publish the result."""
        guild_id = msg.guild_id or msg.data.get("guild_id")
        if not guild_id:
            self.log.warning("GET_GUILD_SETTINGS missing guild_id")
            return

        settings = self.db.get_guild_settings_sync(guild_id)
        response = make_response(msg, data={"settings": settings})
        self.ebus.publish(Topic.BOT, response)

    def _handle_save_setting(self, msg: ZMQMessage):
        """Update a single guild setting."""
        guild_id = msg.guild_id or msg.data.get("guild_id")
        key = msg.data.get("key")
        value = msg.data.get("value")

        if not guild_id or not key:
            self.log.warning("SAVE_SETTING missing guild_id or key")
            return

        try:
            self.db.update_guild_setting_sync(guild_id, key, value)
            response = make_response(msg, data={
                "success": True,
                "key": key,
                "value": value,
            })
            self.log.info("Setting saved: guild=%s key=%s", guild_id, key)
        except ValueError as e:
            response = make_response(msg, data={
                "success": False,
                "error": str(e),
            })
            self.log.error("Invalid setting: %s", e)

        self.ebus.publish(Topic.BOT, response)

        # Broadcast settings change event to all services
        self.ebus.publish(
            Topic.SETTINGS,
            make_event("SETTING_CHANGED", {
                "guild_id": guild_id,
                "key": key,
                "value": value,
            }),
        )

    def _handle_get_warnings(self, msg: ZMQMessage):
        """Fetch all warnings for a user in a guild."""
        guild_id = msg.guild_id or msg.data.get("guild_id")
        user_id = msg.data.get("target_user_id", msg.user_id)

        warnings = self.db.fetchall_sync(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        )

        response = make_response(msg, data={"warnings": warnings})
        self.ebus.publish(Topic.BOT, response)

    def _handle_add_warning(self, msg: ZMQMessage):
        """Add a new warning for a user."""
        guild_id = msg.guild_id or msg.data.get("guild_id")
        user_id = msg.data.get("target_user_id")
        mod_id = msg.user_id or msg.data.get("mod_id")
        reason = msg.data.get("reason", "Sebep belirtilmedi")

        self.db.execute_sync(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, mod_id, reason),
        )

        # Get updated warning count
        count_row = self.db.fetchone_sync(
            "SELECT COUNT(*) as count FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

        response = make_response(msg, data={
            "success": True,
            "warning_count": count_row["count"] if count_row else 0,
        })
        self.ebus.publish(Topic.BOT, response)
        self.log.info("Warning added: guild=%s user=%s reason=%s", guild_id, user_id, reason)

    def _handle_delete_warning(self, msg: ZMQMessage):
        """Delete a specific warning by ID."""
        warning_id = msg.data.get("warning_id")
        guild_id = msg.guild_id or msg.data.get("guild_id")

        self.db.execute_sync(
            "DELETE FROM warnings WHERE id = ? AND guild_id = ?",
            (warning_id, guild_id),
        )

        response = make_response(msg, data={"success": True, "deleted_id": warning_id})
        self.ebus.publish(Topic.BOT, response)


def run_db_service():
    """Entry point for the DB worker process."""
    service = DBService()
    service.run()


if __name__ == "__main__":
    run_db_service()
