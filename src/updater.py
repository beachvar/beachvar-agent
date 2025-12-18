"""
Main updater logic for BeachVar Agent.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from .config import (
    CHECK_INTERVAL_SECONDS,
    COMPOSE_FILE_PATH,
    DEVICE_IMAGE,
    AGENT_IMAGE,
    GHCR_REGISTRY,
    GHCR_USER,
    VERSION_FILE,
)
from .backend import BackendClient
from .docker import DockerClient
from .registry import RegistryClient

logger = logging.getLogger(__name__)


class Updater:
    """Main updater class that checks for and applies updates."""

    def __init__(self):
        self.backend = BackendClient()
        self.docker = DockerClient()
        self.registry = RegistryClient(GHCR_REGISTRY)
        self.compose_file = Path(COMPOSE_FILE_PATH)
        self.versions = self._load_versions()

    def _load_versions(self) -> dict:
        """Load current versions from file."""
        if VERSION_FILE.exists():
            try:
                with open(VERSION_FILE) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error loading versions: {e}")
        return {"device": None, "agent": None}

    def _save_versions(self):
        """Save current versions to file."""
        try:
            VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(VERSION_FILE, "w") as f:
                json.dump(self.versions, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving versions: {e}")

    def _setup_registry_auth(self) -> bool:
        """Setup registry authentication using token from backend."""
        token = self.backend.get_registry_token()
        if not token:
            logger.error("Failed to get registry token from backend")
            return False

        # Set token for registry API calls
        self.registry.set_token(token)

        # Login to Docker for pull operations
        if not self.docker.login(GHCR_REGISTRY, GHCR_USER, token):
            logger.error("Failed to login to Docker registry")
            return False

        return True

    def check_device_update(self) -> str | None:
        """
        Check if beachvar-device needs update using docker manifest inspect.

        Returns:
            New digest if update is available, None otherwise
        """
        remote_digest = self.docker.get_remote_image_digest(DEVICE_IMAGE, "latest")
        if not remote_digest:
            logger.warning("Could not get remote device digest")
            return None

        local_digest = self.versions.get("device")
        if local_digest != remote_digest:
            logger.info(f"Device update available: {local_digest} -> {remote_digest}")
            return remote_digest

        logger.debug("Device is up to date")
        return None

    def check_agent_update(self) -> str | None:
        """
        Check if beachvar-agent needs update using docker manifest inspect.

        Returns:
            New digest if update is available, None otherwise
        """
        remote_digest = self.docker.get_remote_image_digest(AGENT_IMAGE, "latest")
        if not remote_digest:
            logger.warning("Could not get remote agent digest")
            return None

        local_digest = self.versions.get("agent")
        if local_digest != remote_digest:
            logger.info(f"Agent update available: {local_digest} -> {remote_digest}")
            return remote_digest

        logger.debug("Agent is up to date")
        return None

    def update_device(self, new_digest: str) -> bool:
        """
        Update beachvar-device container.

        Args:
            new_digest: The new digest to update to

        Returns:
            True if successful
        """
        logger.info("Updating beachvar-device...")

        # Pull new image
        if not self.docker.pull_image(DEVICE_IMAGE, "latest"):
            return False

        # Restart service
        if not self.docker.restart_service(self.compose_file, "device"):
            return False

        # Update version
        self.versions["device"] = new_digest
        self._save_versions()
        self.backend.report_version(device_version=new_digest)

        logger.info("Device updated successfully")
        return True

    def update_agent(self, new_digest: str) -> bool:
        """
        Update beachvar-agent (self-update).

        Args:
            new_digest: The new digest to update to

        Returns:
            True if successful (will restart after)
        """
        logger.info("Updating beachvar-agent (self)...")

        # Pull new image
        if not self.docker.pull_image(AGENT_IMAGE, "latest"):
            return False

        # Update version before restart
        self.versions["agent"] = new_digest
        self._save_versions()
        self.backend.report_version(agent_version=new_digest)

        # Restart self (will be recreated with new image)
        logger.info("Agent update complete - restarting...")
        if not self.docker.restart_service(self.compose_file, "agent"):
            logger.error("Failed to restart agent")
            return False

        # Exit so Docker restarts us with new image
        sys.exit(0)

    def run_once(self) -> bool:
        """
        Run a single update check cycle.

        Returns:
            True if any update was applied
        """
        # Setup registry authentication first
        if not self._setup_registry_auth():
            return False

        updated = False

        # Check and update device first
        device_digest = self.check_device_update()
        if device_digest:
            if self.update_device(device_digest):
                updated = True

        # Check and update agent (self)
        agent_digest = self.check_agent_update()
        if agent_digest:
            if self.update_agent(agent_digest):
                updated = True

        return updated

    def bootstrap(self) -> bool:
        """
        Bootstrap the device on first run.

        - Login to registry
        - Pull images
        - Start device container if not running

        Returns:
            True if bootstrap was successful
        """
        logger.info("=== Bootstrap: Initializing BeachVar Device ===")

        # Setup registry authentication
        if not self._setup_registry_auth():
            logger.error("Bootstrap: Failed to setup registry authentication")
            return False

        # Check if compose file exists
        if not self.compose_file.exists():
            logger.error(f"Bootstrap: Compose file not found at {self.compose_file}")
            return False

        # Check if device is already running
        if self.docker.is_container_running("beachvar-device"):
            logger.info("Bootstrap: Device container is already running")
        else:
            logger.info("Bootstrap: Device container not running, starting...")

            # Pull images first
            logger.info("Bootstrap: Pulling images...")
            if not self.docker.compose_pull(self.compose_file, "device"):
                logger.warning("Bootstrap: Failed to pull device image, will try to start anyway")

            # Start device container
            if not self.docker.compose_up(self.compose_file, "device"):
                logger.error("Bootstrap: Failed to start device container")
                return False

            logger.info("Bootstrap: Device container started successfully")

        # Get current digests and save (using docker manifest inspect)
        device_digest = self.docker.get_remote_image_digest(DEVICE_IMAGE, "latest")
        agent_digest = self.docker.get_remote_image_digest(AGENT_IMAGE, "latest")

        if device_digest:
            self.versions["device"] = device_digest
        if agent_digest:
            self.versions["agent"] = agent_digest

        self._save_versions()

        # Report versions to backend
        self.backend.report_version(
            device_version=device_digest,
            agent_version=agent_digest,
        )

        logger.info("=== Bootstrap complete ===")
        return True

    def run(self):
        """Run the updater in a loop."""
        logger.info("BeachVar Agent starting...")
        logger.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
        logger.info(f"Compose file: {COMPOSE_FILE_PATH}")

        # Bootstrap: ensure device is running
        if not self.bootstrap():
            logger.error("Bootstrap failed, will retry in next cycle")

        while True:
            try:
                # Check if device is still running, restart if needed
                if not self.docker.is_container_running("beachvar-device"):
                    logger.warning("Device container is not running, restarting...")
                    self.docker.compose_up(self.compose_file, "device")

                self.run_once()
            except Exception as e:
                logger.error(f"Error in update cycle: {e}")

            logger.debug(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
            time.sleep(CHECK_INTERVAL_SECONDS)

    def close(self):
        """Clean up resources."""
        self.backend.close()
        self.registry.close()
