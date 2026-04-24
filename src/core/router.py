"""
Discord Bot — ZMQ Broker (Message Router)

Runs a PULL/PUB proxy that sits at the center of the service mesh.
All services PUSH messages to this broker, and the broker PUBs them
to all subscribers based on topic matching.

This is the exact same pattern used in Centrum/Marmarai and is
battle-tested for multi-process communication.

Architecture:
    [Service A] --PUSH--> [PULL :5556] --proxy--> [PUB :5555] --SUB--> [Service B]
    [Service B] --PUSH--> [PULL :5556] --proxy--> [PUB :5555] --SUB--> [Service A]

Usage:
    python -m src.core.router
"""

import sys
import os

import zmq

# Allow running as standalone module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.config import ZMQ_HOST, ZMQ_PUB_PORT, ZMQ_PULL_PORT
from src.core.logger import get_logger

log = get_logger("router")


def run_broker():
    """
    Runs the central ZMQ PULL/PUB message broker.

    - PULL socket: receives multipart messages [topic, payload] from all services.
    - PUB socket: broadcasts those messages to all subscribers.
    - zmq.proxy: native C-level forwarding (zero-copy, minimal latency).
    """
    context = zmq.Context()

    # Receiver — services PUSH messages here
    receiver = context.socket(zmq.PULL)
    receiver.bind(f"tcp://{ZMQ_HOST}:{ZMQ_PULL_PORT}")

    # Publisher — broadcasts to all SUB sockets
    publisher = context.socket(zmq.PUB)
    publisher.bind(f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}")

    log.info(
        "ZMQ Broker started — PULL:%s / PUB:%s on %s",
        ZMQ_PULL_PORT, ZMQ_PUB_PORT, ZMQ_HOST,
    )

    try:
        # zmq.proxy runs in C and is extremely efficient
        zmq.proxy(receiver, publisher)
    except KeyboardInterrupt:
        log.info("Broker interrupted by user.")
    except Exception as e:
        log.error("Broker proxy error: %s", e)
    finally:
        receiver.close()
        publisher.close()
        context.term()
        log.info("Broker stopped.")


if __name__ == "__main__":
    run_broker()
