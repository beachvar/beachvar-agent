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
        self.github_token: str | None = None
        self._http_client: httpx.Client | None = None
        self._bearer_token_cache: dict[str, str] = {}

    def set_token(self, token: str):
        """Set the GitHub PAT for authentication."""
        self.github_token = token
        # Clear cache when token changes
        self._bearer_token_cache.clear()

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30.0)
        return self._http_client

    def _get_bearer_token(self, image: str) -> str | None:
        """
        Get a bearer token for accessing the registry.

        Uses the GitHub PAT to authenticate and get a scoped bearer token.

        Args:
            image: Image name (e.g., "beachvar/beachvar-device")

        Returns:
            Bearer token or None if failed
        """
        if image in self._bearer_token_cache:
            return self._bearer_token_cache[image]

        if not self.github_token:
            logger.warning("No GitHub token set for registry authentication")
            return None

        # ghcr.io uses token-based auth - we request a token for the specific scope
        # For private images, we need to authenticate with the GitHub PAT
        token_url = f"https://{self.registry}/token"
        params = {
            "scope": f"repository:{image}:pull",
        }

        # Use Basic auth with the GitHub PAT to get a bearer token
        credentials = base64.b64encode(f"beachvar:{self.github_token}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        try:
            response = self._client.get(token_url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                token = data.get("token")
                if token:
                    self._bearer_token_cache[image] = token
                    logger.debug(f"Got bearer token for {image}")
                    return token
            else:
                logger.warning(f"Failed to get bearer token for {image}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting bearer token: {e}")

        return None

    def get_image_digest(self, image: str, tag: str = "latest") -> str | None:
        """
        Get the digest of an image tag from the registry.

        Uses anonymous bearer token authentication for public images.

        Args:
            image: Image name (e.g., "beachvar/beachvar-device")
            tag: Image tag (default: "latest")

        Returns:
            Image digest (sha256:...) or None if not found
        """
        # Get bearer token for this image
        bearer_token = self._get_bearer_token(image)
        if not bearer_token:
            logger.warning(f"Could not get bearer token for {image}")
            return None

        url = f"https://{self.registry}/v2/{image}/manifests/{tag}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            # Accept both manifest list (multi-arch) and single manifest formats
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
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
                logger.error(f"Authentication failed for {image}:{tag}")
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
        # Get bearer token for this image
        bearer_token = self._get_bearer_token(image)
        if not bearer_token:
            logger.warning(f"Could not get bearer token for {image}")
            return []

        url = f"https://{self.registry}/v2/{image}/tags/list"
        headers = {"Authorization": f"Bearer {bearer_token}"}

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
