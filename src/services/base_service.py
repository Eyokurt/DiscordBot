"""
Discord Bot — Abstract Base Worker Service

All worker services (music, database, etc.) inherit from this class.
Provides the standard ZMQ lifecycle:
    1. Connect to broker
    2. Subscribe to relevant topics
    3. Send SERVICE_READY handshake
    4. Run poller-based message loop
    5. Dispatch to handle_message()
    6. Graceful cleanup on shutdown

Usage:
    class MusicService(BaseWorker):
        def __init__(self):
            super().__init__("music", ["MUSIC"])

        def handle_message(self, topic, message):
            if message.action == "SEARCH":
                ...

    service = MusicService()
    service.run()
"""

from __future__ import annotations

import signal
import sys
import os
from abc import ABC, abstractmethod

import zmq

# Allow running as standalone module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.zmq_client import ZMQEventBus
from src.core.protocol import ZMQMessage, Topic, make_event
from src.core.logger import get_logger


class BaseWorker(ABC):
    """
    Abstract base class for all ZMQ worker services.

    Subclasses must implement:
        handle_message(topic: str, message: ZMQMessage) -> None
    """

    def __init__(self, service_name: str, topics: list[str]):
        """
        Args:
            service_name: Human-readable service identifier (e.g. "music", "db").
            topics: List of ZMQ topics to subscribe to.
        """
        self.name = service_name
        self.topics = topics
        self.running = True
        self.log = get_logger(service_name)

        # Initialize ZMQ event bus
        self.ebus = ZMQEventBus(service_name=service_name)

        # Subscribe to service-specific topics + SYSTEM
        for topic in topics:
            self.ebus.subscribe(topic)
        self.ebus.subscribe(Topic.SYSTEM)

        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.log.info("Received signal %s, shutting down...", signum)
        self.running = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def _handshake(self):
        """Announce service readiness to the broker."""
        self.ebus.publish(
            Topic.SYSTEM,
            make_event("SERVICE_READY", {"service": self.name}),
        )
        self.log.info("Service '%s' ready — handshake sent.", self.name)

    def setup(self):
        """
        Optional override: Called once before the main loop starts.
        Use for database connections, resource loading, etc.
        """
        pass

    def teardown(self):
        """
        Optional override: Called once after the main loop exits.
        Use for cleanup (close files, connections, etc.).
        """
        pass

    @abstractmethod
    def handle_message(self, topic: str, message: ZMQMessage):
        """
        Process an incoming ZMQ message.

        Args:
            topic:   The ZMQ topic string (e.g. "MUSIC", "DB").
            message: The deserialized ZMQMessage envelope.
        """
        ...

    # ── Main Loop ──────────────────────────────────────────────────────

    def run(self):
        """
        Start the service: setup → handshake → poller loop → teardown.

        The poller loop uses zmq.Poller for CPU-efficient waiting:
        - Blocks for up to 100ms per iteration
        - Drains all queued messages in a burst when data arrives
        - Near-zero CPU when idle
        """
        self.log.info("Starting service '%s'...", self.name)

        try:
            self.setup()
            self._handshake()

            # Event-driven poller (same pattern as Centrum audio_service)
            poller = zmq.Poller()
            poller.register(self.ebus.sub_socket, zmq.POLLIN)

            while self.running:
                events = dict(poller.poll(timeout=100))

                if self.ebus.sub_socket in events:
                    # Drain all queued messages in one burst
                    while True:
                        topic, message = self.ebus.receive(flags=zmq.NOBLOCK)
                        if topic is None:
                            break

                        # Handle system messages internally
                        if topic == Topic.SYSTEM:
                            self._handle_system_message(message)
                            continue

                        # Dispatch to subclass handler
                        try:
                            self.handle_message(topic, message)
                        except Exception as e:
                            self.log.error(
                                "Error handling message [%s/%s]: %s",
                                topic, message.action, e,
                                exc_info=True,
                            )

        except KeyboardInterrupt:
            self.log.info("Interrupted by user.")
        finally:
            self.teardown()
            self.ebus.cleanup()
            self.log.info("Service '%s' stopped.", self.name)

    def _handle_system_message(self, message: ZMQMessage):
        """Process SYSTEM topic messages (shutdown, heartbeat, etc.)."""
        if message.action == "SHUTDOWN":
            self.log.info("Received SHUTDOWN command.")
            self.running = False
        elif message.action == "HEARTBEAT":
            # Respond with alive signal
            self.ebus.publish(
                Topic.SYSTEM,
                make_event("HEARTBEAT_ACK", {"service": self.name}),
            )
