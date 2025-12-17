"""
Backend API client for BeachVar Agent.
"""

import logging
import httpx

from .config import BACKEND_URL, DEVICE_TOKEN

logger = logging.getLogger(__name__)


class BackendClient:
    """Client for communicating with BeachVar backend."""

    def __init__(self, base_url: str = BACKEND_URL, device_token: str = DEVICE_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token
        self._http_client: httpx.Client | None = None

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=30.0,
                headers={
                    "X-Device-Token": self.device_token,
                    "Content-Type": "application/json",
                },
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
