"""
Configuration for BeachVar Agent.
"""

import os
from pathlib import Path

# API Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "https://api.beachvar.cainelli.xyz")
DEVICE_ID = os.getenv("DEVICE_ID", "")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")

# Docker Configuration
GHCR_REGISTRY = "ghcr.io"
GHCR_USER = "beachvar"
DEVICE_IMAGE = f"{GHCR_REGISTRY}/{GHCR_USER}/beachvar-device"
AGENT_IMAGE = f"{GHCR_REGISTRY}/{GHCR_USER}/beachvar-agent"

# Debug mode: faster update checks for development
DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")

# Update Configuration
# Health check: verify device is running (fast loop)
HEALTH_CHECK_INTERVAL_SECONDS = 5

# Version check: check for updates (slow loop, respects update windows)
# In debug mode, check every 30 seconds; otherwise every 5 minutes
DEFAULT_UPDATE_CHECK_INTERVAL = 30 if DEBUG else 300
UPDATE_CHECK_INTERVAL_SECONDS = int(os.getenv("UPDATE_CHECK_INTERVAL_SECONDS", str(DEFAULT_UPDATE_CHECK_INTERVAL)))

# Config sync: run docker compose up -d to apply any config changes
# In debug mode, sync every 2 minutes; otherwise every 30 minutes
DEFAULT_CONFIG_SYNC_INTERVAL = 120 if DEBUG else 1800
CONFIG_SYNC_INTERVAL_SECONDS = int(os.getenv("CONFIG_SYNC_INTERVAL_SECONDS", str(DEFAULT_CONFIG_SYNC_INTERVAL)))

# Legacy alias for backwards compatibility
CHECK_INTERVAL_SECONDS = UPDATE_CHECK_INTERVAL_SECONDS
COMPOSE_FILE_PATH = os.getenv("COMPOSE_FILE_PATH", "/etc/beachvar/docker-compose.yml")

# Version file to track current versions
VERSION_FILE = Path("/etc/beachvar-agent/versions.json")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
