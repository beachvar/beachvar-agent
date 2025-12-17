"""
GitHub Container Registry client.
"""

import base64
import logging
import httpx

logger = logging.getLogger(__name__)


class RegistryClient:
    """Client for interacting with GitHub Container Registry."""

    def __init__(self, registry: str = "ghcr.io"):
        self.registry = registry
        self.token: str | None = None
        self._http_client: httpx.Client | None = None

    def set_token(self, token: str):
        """Set the authentication token."""
        self.token = token

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30.0)
        return self._http_client

    def _get_auth_header(self) -> dict[str, str]:
        """Get authorization header for registry requests."""
        if not self.token:
            return {}
        # ghcr.io uses Basic auth with username:token
        credentials = base64.b64encode(f"beachvar:{self.token}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    def get_image_digest(self, image: str, tag: str = "latest") -> str | None:
        """
        Get the digest of an image tag from the registry.

        Args:
            image: Image name (e.g., "beachvar/beachvar-device")
            tag: Image tag (default: "latest")

        Returns:
            Image digest (sha256:...) or None if not found
        """
        url = f"https://{self.registry}/v2/{image}/manifests/{tag}"
        headers = {
            **self._get_auth_header(),
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
        }

        try:
            response = self._client.get(url, headers=headers)
            if response.status_code == 200:
                # Digest is in the Docker-Content-Digest header
                digest = response.headers.get("Docker-Content-Digest")
                if digest:
                    return digest
                # Fallback to calculating from response
                import hashlib
                return f"sha256:{hashlib.sha256(response.content).hexdigest()}"
            elif response.status_code == 401:
                logger.error("Authentication failed - check GitHub token")
            elif response.status_code == 404:
                logger.warning(f"Image {image}:{tag} not found")
            else:
                logger.error(f"Failed to get manifest: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting image digest: {e}")

        return None

    def list_tags(self, image: str) -> list[str]:
        """
        List all tags for an image.

        Args:
            image: Image name (e.g., "beachvar/beachvar-device")

        Returns:
            List of tags
        """
        url = f"https://{self.registry}/v2/{image}/tags/list"
        headers = self._get_auth_header()

        try:
            response = self._client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("tags", [])
            else:
                logger.error(f"Failed to list tags: {response.status_code}")
        except Exception as e:
            logger.error(f"Error listing tags: {e}")

        return []

    def close(self):
        """Close the HTTP client."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None
