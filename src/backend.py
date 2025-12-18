"""
Backend API client for BeachVar Agent.
"""

import base64
import logging
import httpx

from .config import BACKEND_URL, DEVICE_ID, DEVICE_TOKEN

logger = logging.getLogger(__name__)


class BackendClient:
    """Client for communicating with BeachVar backend."""

    def __init__(
        self,
        base_url: str = BACKEND_URL,
        device_id: str = DEVICE_ID,
        device_token: str = DEVICE_TOKEN,
    ):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.device_token = device_token
        self._http_client: httpx.Client | None = None

    def _get_auth_headers(self) -> dict:
        """Get authentication headers for API requests using Basic Auth."""
        credentials = f"{self.device_id}:{self.device_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded}",
        }

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=30.0,
                headers=self._get_auth_headers(),
            )
        return self._http_client

    def get_registry_token(self) -> str | None:
        """
        Get GitHub registry token from backend.

        Returns:
            GitHub token or None if failed
        """
        try:
            response = self._client.get(f"{self.base_url}/api/v1/device/registry-token/")
            if response.status_code == 200:
                data = response.json()
                return data.get("token")
            elif response.status_code == 401:
                logger.error("Device authentication failed")
            elif response.status_code == 404:
                logger.error("Registry token endpoint not found")
            else:
                logger.error(f"Failed to get registry token: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting registry token: {e}")

        return None

    def get_update_windows(self) -> list[dict] | None:
        """
        Get update windows configuration from backend.

        Returns:
            List of update windows or None if failed.
            Each window has: name, start_time (HH:MM), end_time (HH:MM)
        """
        try:
            response = self._client.get(f"{self.base_url}/api/v1/device/config/")
            if response.status_code == 200:
                data = response.json()
                return data.get("update_windows", [])
            else:
                logger.warning(f"Failed to get config: {response.status_code}")
        except Exception as e:
            logger.warning(f"Error getting update windows: {e}")

        return None

    def is_update_allowed(self) -> bool:
        """
        Check if updates are allowed based on configured time windows.

        Returns:
            True if updates are allowed now, False otherwise.
            If no windows are configured or fetch fails, returns True (allow updates).
        """
        from datetime import datetime

        windows = self.get_update_windows()

        # If we couldn't fetch windows or none configured, allow updates
        if windows is None:
            logger.debug("Could not fetch update windows, allowing updates")
            return True

        if not windows:
            logger.debug("No update windows configured, allowing updates")
            return True

        # Get current time
        now = datetime.now().time()

        for window in windows:
            try:
                start_str = window.get("start_time", "")
                end_str = window.get("end_time", "")

                if not start_str or not end_str:
                    continue

                start_time = datetime.strptime(start_str, "%H:%M").time()
                end_time = datetime.strptime(end_str, "%H:%M").time()

                # Handle windows that cross midnight
                if start_time <= end_time:
                    # Normal window (e.g., 02:00 - 06:00)
                    if start_time <= now <= end_time:
                        logger.debug(f"Inside update window: {window.get('name', 'unnamed')}")
                        return True
                else:
                    # Window crosses midnight (e.g., 23:00 - 06:00)
                    if now >= start_time or now <= end_time:
                        logger.debug(f"Inside update window: {window.get('name', 'unnamed')}")
                        return True

            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid update window format: {window}, error: {e}")
                continue

        logger.info(f"Outside all update windows, skipping update check")
        return False

    def report_version(
        self,
        device_version: str | None = None,
        agent_version: str | None = None,
    ) -> bool:
        """
        Report current versions to backend.

        Args:
            device_version: Version/digest of beachvar-device
            agent_version: Version/digest of beachvar-agent

        Returns:
            True if successful
        """
        try:
            payload = {}
            if device_version:
                payload["device_version"] = device_version
            if agent_version:
                payload["agent_version"] = agent_version

            response = self._client.post(
                f"{self.base_url}/api/v1/device/version/",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(f"Version reported: {payload}")
                return True
            else:
                logger.error(f"Failed to report version: {response.status_code}")
        except Exception as e:
            logger.error(f"Error reporting version: {e}")

        return False

    def close(self):
        """Close the HTTP client."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None
