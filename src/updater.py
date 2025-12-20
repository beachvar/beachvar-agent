"""
Main updater logic for BeachVar Agent.

Handles self-updates, device updates, and container health checks.
"""

import json
import logging
import os
import time
from pathlib import Path

from .config import (
    HEALTH_CHECK_INTERVAL_SECONDS,
    UPDATE_CHECK_INTERVAL_SECONDS,
    CONFIG_SYNC_INTERVAL_SECONDS,
    COMPOSE_FILE_PATH,
    DEBUG,
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
        self._agent_update_pending = False  # Flag to track if agent needs recreation

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

    def _ensure_registry_auth(self) -> bool:
        """Ensure registry authentication is set up (lazy initialization)."""
        if not hasattr(self, "_auth_setup_done"):
            self._auth_setup_done = False

        if not self._auth_setup_done:
            self._auth_setup_done = self._setup_registry_auth()

        return self._auth_setup_done

    def _pull_with_fallback(self, image: str, tag: str = "latest") -> bool:
        """
        Try to pull an image, falling back to authenticated pull if needed.

        First tries without explicit auth (uses cached credentials if any),
        then falls back to getting fresh token from backend.

        Args:
            image: Image name
            tag: Image tag

        Returns:
            True if pull succeeded
        """
        # Try pulling without explicit authentication first
        if self.docker.try_pull_without_auth(image, tag):
            return True

        # If that failed, try with fresh authentication
        logger.info("Pull failed, trying with fresh authentication...")
        if self._ensure_registry_auth():
            return self.docker.pull_image(image, tag)

        return False

    def _get_remote_digest_via_api(self, image: str, tag: str = "latest") -> str | None:
        """
        Get remote image digest using HTTP API (no docker CLI needed).

        Uses the RegistryClient to fetch the digest directly from ghcr.io.
        This is more reliable and faster than docker manifest inspect.

        Args:
            image: Full image name (e.g., "ghcr.io/beachvar/beachvar-device")
            tag: Image tag

        Returns:
            Image digest or None if failed
        """
        # Extract the image path without registry prefix for the API call
        # e.g., "ghcr.io/beachvar/beachvar-device" -> "beachvar/beachvar-device"
        image_path = image.replace(f"{GHCR_REGISTRY}/", "")

        # Ensure we have auth set up
        if not self._ensure_registry_auth():
            logger.warning("Could not set up registry authentication")
            return None

        # Use RegistryClient to get digest via HTTP API
        digest = self.registry.get_image_digest(image_path, tag)
        if digest:
            logger.debug(f"Got digest for {image}:{tag} via API: {digest[:19]}...")
            return digest

        logger.warning(f"Could not get digest for {image}:{tag} via API")
        return None

    def _get_remote_digest_with_auth_fallback(self, image: str, tag: str = "latest") -> str | None:
        """
        Get remote image digest, trying API first, then falling back to docker CLI.

        Args:
            image: Image name
            tag: Image tag

        Returns:
            Image digest or None if failed
        """
        # Try via HTTP API first (faster and more reliable)
        remote_digest = self._get_remote_digest_via_api(image, tag)
        if remote_digest:
            return remote_digest

        # Fallback to docker CLI if API failed
        logger.info("API digest check failed, falling back to docker CLI...")
        remote_digest = self.docker.get_remote_image_digest(image, tag)
        if remote_digest:
            return remote_digest

        # If that also failed, try with fresh authentication
        logger.info("Docker digest check failed, trying with fresh authentication...")
        if self._ensure_registry_auth():
            return self.docker.get_remote_image_digest(image, tag)

        return None

    def check_device_update(self) -> str | None:
        """
        Check if beachvar-device needs update.

        Uses HTTP API to ghcr.io (falls back to docker CLI if needed).

        Returns:
            New digest if update is available, None otherwise
        """
        remote_digest = self._get_remote_digest_with_auth_fallback(DEVICE_IMAGE, "latest")
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
        Check if beachvar-agent needs update.

        Uses HTTP API to ghcr.io (falls back to docker CLI if needed).

        Returns:
            New digest if update is available, None otherwise
        """
        remote_digest = self._get_remote_digest_with_auth_fallback(AGENT_IMAGE, "latest")
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

        # Pull new image (try without auth first, then with auth)
        if not self._pull_with_fallback(DEVICE_IMAGE, "latest"):
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

        Strategy: Pull new image, save version. The container will be recreated
        by the periodic config sync (docker compose up -d) which runs externally.

        Args:
            new_digest: The new digest to update to

        Returns:
            True if update was prepared successfully
        """
        logger.info("Updating beachvar-agent (self)...")

        # Pull new image (try without auth first, then with auth)
        if not self._pull_with_fallback(AGENT_IMAGE, "latest"):
            return False

        # Update version
        self.versions["agent"] = new_digest
        self._save_versions()
        self.backend.report_version(agent_version=new_digest)

        # Mark that agent update is pending - next sync_config will recreate the agent
        self._agent_update_pending = True

        logger.info("Agent update prepared - will be applied on next config sync")
        return True

    def run_once(self) -> bool:
        """
        Run a single update check cycle.

        Returns:
            True if any update was applied
        """
        # Check if we're inside an update window first
        # This saves resources by not checking for updates outside allowed times
        if not self.backend.is_update_allowed():
            logger.debug("Outside update window, skipping update check")
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

        - Check for updates and apply them (auth is done lazily if needed)
        - Start device container if not running

        Returns:
            True if bootstrap was successful
        """
        logger.info("=== Bootstrap: Initializing BeachVar Device ===")

        # Check if compose file exists
        if not self.compose_file.exists():
            logger.error(f"Bootstrap: Compose file not found at {self.compose_file}")
            return False

        # Always check for device updates first
        logger.info("Bootstrap: Checking for device updates...")
        device_digest = self.check_device_update()
        if device_digest:
            logger.info("Bootstrap: Device update available, applying...")
            if self.update_device(device_digest):
                logger.info("Bootstrap: Device updated successfully")
            else:
                logger.warning("Bootstrap: Failed to update device")
        else:
            # No update needed, but ensure all containers are running
            if not self.docker.is_container_running("beachvar-device"):
                logger.info("Bootstrap: Device container not running, starting...")

                # Try to pull images (will use auth fallback if needed)
                logger.info("Bootstrap: Pulling images...")
                if not self._pull_with_fallback(DEVICE_IMAGE, "latest"):
                    logger.warning("Bootstrap: Failed to pull device image, will try to start anyway")

            # Start all containers via Docker API (device, cloudflared, ttyd)
            # Using detached mode to avoid issues if agent gets recreated
            logger.info("Bootstrap: Starting containers via Docker API...")
            if not self.docker.compose_up_detached(self.compose_file):
                logger.error("Bootstrap: Failed to start containers")
                return False

            logger.info("Bootstrap: Containers started successfully")

        # Get current digests and save (using docker manifest inspect)
        remote_device_digest = self.docker.get_remote_image_digest(DEVICE_IMAGE, "latest")
        remote_agent_digest = self.docker.get_remote_image_digest(AGENT_IMAGE, "latest")

        if remote_device_digest:
            self.versions["device"] = remote_device_digest
        if remote_agent_digest:
            self.versions["agent"] = remote_agent_digest

        self._save_versions()

        # Report versions to backend
        self.backend.report_version(
            device_version=remote_device_digest,
            agent_version=remote_agent_digest,
        )

        logger.info("=== Bootstrap complete ===")
        return True

    def ensure_containers_running(self) -> bool:
        """
        Check if all containers are running and start them if not.

        Uses Docker API to spawn a helper container that starts the services
        with --force-recreate to handle cases where container names are
        corrupted or there are conflicts.

        Returns:
            True if all containers are now running
        """
        # Check which containers are down
        containers_to_start = []
        container_checks = [
            ("beachvar-device", "device"),
            ("beachvar-cloudflared", "cloudflared"),
            ("beachvar-ttyd", "ttyd"),
        ]

        for container_name, service_name in container_checks:
            if not self.docker.is_container_running(container_name):
                logger.warning(f"{container_name} is not running")
                containers_to_start.append(service_name)

        if not containers_to_start:
            return True

        # Start all down containers via Docker API with --force-recreate
        # This ensures containers are properly recreated even if there are naming conflicts
        logger.info(f"Recreating containers via Docker API: {', '.join(containers_to_start)}")
        return self.docker.compose_up_detached(
            self.compose_file, containers_to_start, force_recreate=True
        )

    def sync_config(self) -> bool:
        """
        Sync docker-compose configuration by running 'docker compose up -d'.

        This ensures any configuration changes in docker-compose.yml are applied
        to running containers (e.g., environment variables, volumes, etc.).

        If an agent update is pending, uses --force-recreate to apply it.

        Returns:
            True if sync was successful
        """
        if self._agent_update_pending:
            logger.info("Syncing docker-compose configuration (with agent update)...")
            # Use force-recreate to apply the agent update
            result = self.docker.compose_up_detached(self.compose_file, force_recreate=True)
            if result:
                self._agent_update_pending = False
                logger.info("Config sync completed - agent will be recreated")
            else:
                logger.warning("Config sync failed")
        else:
            logger.info("Syncing docker-compose configuration...")
            # Normal sync without force-recreate (won't kill agent)
            result = self.docker.compose_up_detached(self.compose_file, force_recreate=False)
            if result:
                logger.info("Config sync completed successfully")
            else:
                logger.warning("Config sync failed")

        return result

    def run(self):
        """Run the updater with three loops: fast health check, slow update check, config sync."""
        logger.info("BeachVar Agent starting...")
        if DEBUG:
            logger.info("DEBUG MODE: Using faster intervals")
        logger.info(f"Health check interval: {HEALTH_CHECK_INTERVAL_SECONDS} seconds")
        logger.info(f"Update check interval: {UPDATE_CHECK_INTERVAL_SECONDS} seconds")
        logger.info(f"Config sync interval: {CONFIG_SYNC_INTERVAL_SECONDS} seconds")
        logger.info(f"Compose file: {COMPOSE_FILE_PATH}")

        # Bootstrap: ensure device is running
        if not self.bootstrap():
            logger.error("Bootstrap failed, will retry in next cycle")

        # Track when we last checked for updates and synced config
        # Initialize with current time to avoid immediate sync after bootstrap
        last_update_check = 0
        last_config_sync = time.time()

        while True:
            try:
                # Fast loop: ensure all containers are running (every 5 seconds)
                self.ensure_containers_running()

                now = time.time()

                # Slow loop: check for updates (every 5 minutes, respects update windows)
                if now - last_update_check >= UPDATE_CHECK_INTERVAL_SECONDS:
                    self.run_once()
                    last_update_check = now

                # Config sync loop: apply docker-compose.yml changes (every 30 minutes)
                if now - last_config_sync >= CONFIG_SYNC_INTERVAL_SECONDS:
                    self.sync_config()
                    last_config_sync = now

            except Exception as e:
                logger.error(f"Error in update cycle: {e}")

            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

    def close(self):
        """Clean up resources."""
        self.backend.close()
        self.registry.close()
