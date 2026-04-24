"""
Discord Bot — ZMQ Event Bus Client

Provides both synchronous and asynchronous ZMQ clients for inter-service
communication through the central PULL/PUB broker.

Two classes:
    ZMQEventBus      — Sync version for worker services (multiprocessing)
    AsyncZMQEventBus — Async version for the Discord bot (asyncio event loop)

Both use the same wire protocol: multipart [topic_bytes, payload_json_bytes]
and leverage the ZMQMessage envelope from protocol.py.
"""

from __future__ import annotations

import json
from typing import Any

import zmq
import zmq.asyncio

from src.core.config import ZMQ_HOST, ZMQ_PUB_PORT, ZMQ_PULL_PORT
from src.core.logger import get_logger
from src.core.protocol import ZMQMessage

log = get_logger("zmq")


# ============================================================================
# SYNCHRONOUS EVENT BUS (for worker services running in separate processes)
# ============================================================================

class ZMQEventBus:
    """
    Synchronous ZMQ client using PUSH/SUB through the central broker.

    Usage:
        ebus = ZMQEventBus(service_name="music")
        ebus.subscribe("MUSIC")
        ebus.publish("BOT", make_command("PLAY_STARTED", {"title": "..."}))

        # Polling loop
        topic, msg = ebus.receive(flags=zmq.NOBLOCK)

    Supports context manager:
        with ZMQEventBus("db") as ebus:
            ...
    """

    def __init__(self, service_name: str = "unknown"):
        self.service_name = service_name
        self.context = zmq.Context()
        self._closed = False

        # PUSH → Broker PULL (send messages)
        self.push_socket = self.context.socket(zmq.PUSH)
        self.push_socket.setsockopt(zmq.LINGER, 1000)
        self.push_socket.setsockopt(zmq.SNDHWM, 100)
        self.push_socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PULL_PORT}")

        # SUB ← Broker PUB (receive messages)
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.setsockopt(zmq.LINGER, 0)
        self.sub_socket.setsockopt(zmq.RCVHWM, 100)
        self.sub_socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}")

    def subscribe(self, topic: str):
        """Subscribe to a ZMQ topic for receiving messages."""
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)

    def publish(self, topic: str, message: ZMQMessage):
        """
        PUSH a message to the broker.

        Args:
            topic:   Target topic string (e.g. "MUSIC", "DB").
            message: ZMQMessage envelope to send.
        """
        if self._closed:
            log.warning("[%s] Attempted publish on closed bus", self.service_name)
            return
        message.source = self.service_name
        self.push_socket.send_multipart([
            topic.encode("utf-8"),
            message.to_bytes(),
        ])

    def publish_raw(self, topic: str, payload: dict):
        """
        PUSH a raw dict payload (backward-compatible convenience method).
        Wraps the dict in a minimal ZMQMessage.
        """
        msg = ZMQMessage(
            action=payload.get("action", "UNKNOWN"),
            data=payload,
            source=self.service_name,
        )
        self.publish(topic, msg)

    def receive(self, flags: int = 0) -> tuple[str | None, ZMQMessage | None]:
        """
        Receive a multipart message: [topic, payload].

        Args:
            flags: zmq flags (e.g. zmq.NOBLOCK for non-blocking).

        Returns:
            (topic_str, ZMQMessage) or (None, None) if no message.
        """
        try:
            parts = self.sub_socket.recv_multipart(flags=flags)
            if len(parts) == 2:
                topic = parts[0].decode("utf-8")
                message = ZMQMessage.from_bytes(parts[1])
                return topic, message
        except zmq.Again:
            pass  # Non-blocking empty queue
        return None, None

    def cleanup(self):
        """Close sockets and terminate context. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        self.push_socket.setsockopt(zmq.LINGER, 0)
        self.sub_socket.setsockopt(zmq.LINGER, 0)
        self.push_socket.close()
        self.sub_socket.close()
        self.context.term()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()


# ============================================================================
# ASYNCHRONOUS EVENT BUS (for the Discord bot running on asyncio)
# ============================================================================

class AsyncZMQEventBus:
    """
    Async ZMQ client for use within the Discord.py asyncio event loop.

    Uses zmq.asyncio sockets so that receive() is non-blocking and
    integrates cleanly with asyncio.create_task().

    Usage:
        ebus = AsyncZMQEventBus(service_name="bot")
        ebus.subscribe("BOT")
        await ebus.publish("MUSIC", make_request("SEARCH", {"query": "..."}))
        topic, msg = await ebus.receive()
    """

    def __init__(self, service_name: str = "bot"):
        self.service_name = service_name
        self.context = zmq.asyncio.Context()
        self._closed = False

        # PUSH → Broker PULL
        self.push_socket = self.context.socket(zmq.PUSH)
        self.push_socket.setsockopt(zmq.LINGER, 1000)
        self.push_socket.setsockopt(zmq.SNDHWM, 100)
        self.push_socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PULL_PORT}")

        # SUB ← Broker PUB
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.setsockopt(zmq.LINGER, 0)
        self.sub_socket.setsockopt(zmq.RCVHWM, 100)
        self.sub_socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}")

    def subscribe(self, topic: str):
        """Subscribe to a ZMQ topic."""
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)

    async def publish(self, topic: str, message: ZMQMessage):
        """Async PUSH a message to the broker."""
        if self._closed:
            log.warning("[%s] Attempted publish on closed async bus", self.service_name)
            return
        message.source = self.service_name
        await self.push_socket.send_multipart([
            topic.encode("utf-8"),
            message.to_bytes(),
        ])

    async def publish_raw(self, topic: str, payload: dict):
        """Async PUSH a raw dict payload."""
        msg = ZMQMessage(
            action=payload.get("action", "UNKNOWN"),
            data=payload,
            source=self.service_name,
        )
        await self.publish(topic, msg)

    async def receive(self) -> tuple[str | None, ZMQMessage | None]:
        """
        Async receive a multipart message.
        Awaits until a message arrives (cooperative with asyncio).
        """
        try:
            parts = await self.sub_socket.recv_multipart()
            if len(parts) == 2:
                topic = parts[0].decode("utf-8")
                message = ZMQMessage.from_bytes(parts[1])
                return topic, message
        except zmq.ZMQError as e:
            log.error("[%s] ZMQ receive error: %s", self.service_name, e)
        return None, None

    def receive_nowait(self) -> tuple[str | None, ZMQMessage | None]:
        """Non-blocking receive (useful for drain loops)."""
        try:
            parts = self.sub_socket.recv_multipart(flags=zmq.NOBLOCK)
            if len(parts) == 2:
                topic = parts[0].decode("utf-8")
                message = ZMQMessage.from_bytes(parts[1])
                return topic, message
        except zmq.Again:
            pass
        return None, None

    def cleanup(self):
        """Close sockets and terminate context."""
        if self._closed:
            return
        self._closed = True
        self.push_socket.setsockopt(zmq.LINGER, 0)
        self.sub_socket.setsockopt(zmq.LINGER, 0)
        self.push_socket.close()
        self.sub_socket.close()
        self.context.term()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
