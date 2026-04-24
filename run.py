"""
Discord Bot — Service Orchestrator

Manages the lifecycle of all microservices:
    1. ZMQ Broker (router)  — CRITICAL
    2. DB Worker Service     — NON-CRITICAL (restartable)
    3. Music Worker Service  — NON-CRITICAL (restartable)
    4. Discord Bot Core      — CRITICAL

Adapted from the Centrum/Marmarai run_services.py pattern:
    - Process watchdog with exponential backoff
    - Critical service failure → full shutdown
    - Restart rate limiting (max 5/min)
    - Graceful SIGINT/SIGTERM handling

Usage:
    python run.py
"""

import multiprocessing
import time
import sys
import os
import signal

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.core.logger import get_logger
from src.core.config import (
    WATCHDOG_INTERVAL,
    MAX_RESTARTS_PER_MIN,
    MUSIC_ENABLED,
    DB_ENABLED,
)

log = get_logger("orchestrator")


# ── Service Entry Points ──────────────────────────────────────────────────

def start_router():
    from src.core.router import run_broker
    run_broker()


def start_bot():
    from src.bot.bot import run_bot
    run_bot()


def start_db_service():
    from src.services.db_service import run_db_service
    run_db_service()


def start_music_service():
    from src.services.music_service import MusicService
    service = MusicService()
    service.run()


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Discord Bot Orchestrator — Starting...")
    log.info("=" * 60)

    # Service definitions: {name: {target, critical}}
    services = {
        "ZMQ_Broker": {"target": start_router, "critical": True},
    }

    if DB_ENABLED:
        services["DB_Worker"] = {"target": start_db_service, "critical": False}

    if MUSIC_ENABLED:
        services["Music_Worker"] = {"target": start_music_service, "critical": False}

    # Bot is always last and always critical
    services["Discord_Bot"] = {"target": start_bot, "critical": True}

    processes = {}
    restart_counts = {}
    restart_times = {}

    # ── Start a Service ───────────────────────────────────────────────

    def start_service(name):
        info = services[name]
        p = multiprocessing.Process(target=info["target"], name=name)
        p.start()
        processes[name] = p
        log.info("Started %s (pid=%s)", name, p.pid)
        return p

    # Start broker first, then wait for it to bind
    start_service("ZMQ_Broker")
    time.sleep(1)

    # Start remaining services
    for name in services:
        if name != "ZMQ_Broker":
            start_service(name)
            time.sleep(0.5)  # Stagger starts

    # ── Signal Handling ───────────────────────────────────────────────

    _shutdown = [False]

    def _handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        log.info("Received %s, initiating shutdown...", sig_name)
        _shutdown[0] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ── Watchdog Loop ─────────────────────────────────────────────────

    log.info("All services started. Watchdog active (interval=%ds).", WATCHDOG_INTERVAL)

    try:
        while not _shutdown[0]:
            for name, info in services.items():
                p = processes.get(name)
                if p is None or p.is_alive():
                    continue

                # Process died
                exit_code = p.exitcode
                log.warning("%s died (exit code=%s).", name, exit_code)

                # Critical → shut everything down
                if info["critical"]:
                    log.critical("%s is CRITICAL. Terminating all services.", name)
                    _shutdown[0] = True
                    break

                # Rate limiting
                now = time.time()
                restart_times.setdefault(name, [])
                restart_times[name] = [t for t in restart_times[name] if now - t < 60]

                if len(restart_times[name]) >= MAX_RESTARTS_PER_MIN:
                    log.critical(
                        "%s restarted %d times in 60s. Giving up.",
                        name, MAX_RESTARTS_PER_MIN,
                    )
                    _shutdown[0] = True
                    break

                # Exponential backoff
                restart_counts[name] = restart_counts.get(name, 0) + 1
                backoff = min(2 ** restart_counts[name], 30)
                log.warning(
                    "Restarting %s in %.0fs (attempt #%d)...",
                    name, backoff, restart_counts[name],
                )
                time.sleep(backoff)

                restart_times[name].append(time.time())
                start_service(name)

            time.sleep(WATCHDOG_INTERVAL)

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received.")

    # ── Graceful Shutdown ─────────────────────────────────────────────

    log.info("Shutting down all services...")
    for name, p in processes.items():
        if p.is_alive():
            log.info("Terminating %s (pid=%s)...", name, p.pid)
            p.terminate()

    for name, p in processes.items():
        p.join(timeout=5)
        if p.is_alive():
            log.warning("%s did not stop in 5s — killing.", name)
            p.kill()
            p.join(timeout=2)

    log.info("All services stopped. Goodbye.")
