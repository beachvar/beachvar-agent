#!/usr/bin/env python3
"""
BeachVar Agent - Auto-update service for BeachVar devices.

Monitors for updates and manages container lifecycle via Docker API.
"""

import logging
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

from src.config import LOG_LEVEL
from src.updater import Updater

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Global updater instance for signal handling
updater: Updater | None = None


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, shutting down...")
    if updater:
        updater.close()
    sys.exit(0)


def main():
    global updater

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        updater = Updater()
        updater.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if updater:
            updater.close()


if __name__ == "__main__":
    main()
