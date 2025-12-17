"""
Configuration for BeachVar Agent.
"""

import os
from pathlib import Path

# API Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "https://api.beachvar.cainelli.xyz")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")

# Docker Configuration
GHCR_REGISTRY = "ghcr.io"
GHCR_USER = "beachvar"
DEVICE_IMAGE = f"{GHCR_REGISTRY}/{GHCR_USER}/beachvar-device"
AGENT_IMAGE = f"{GHCR_REGISTRY}/{GHCR_USER}/beachvar-agent"

# Update Configuration
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))  # 5 minutes
COMPOSE_FILE_PATH = os.getenv("COMPOSE_FILE_PATH", "/etc/beachvar/docker-compose.yml")

# Version file to track current versions
VERSION_FILE = Path("/etc/beachvar-agent/versions.json")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
