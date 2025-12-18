"""
Docker operations for BeachVar Agent.
"""

import hashlib
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class DockerClient:
    """Client for Docker operations."""

    def __init__(self):
        self._check_docker()

    def _check_docker(self):
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError("Docker is not running")
            logger.debug(f"Docker version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError("Docker is not installed")

    def login(self, registry: str, username: str, password: str) -> bool:
        """
        Login to a Docker registry.

        Args:
            registry: Registry URL (e.g., "ghcr.io")
            username: Username
            password: Password/token

        Returns:
            True if successful
        """
        try:
            result = subprocess.run(
                ["docker", "login", registry, "-u", username, "--password-stdin"],
                input=password,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info(f"Logged in to {registry}")
                return True
            else:
                logger.error(f"Login failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error logging in: {e}")

        return False

    def get_local_image_digest(self, image: str, tag: str = "latest") -> str | None:
        """
        Get the digest of a local image.

        Args:
            image: Image name
            tag: Image tag

        Returns:
            Image digest or None if not found
        """
        try:
            result = subprocess.run(
                ["docker", "images", "--digests", "--format", "{{.Digest}}", f"{image}:{tag}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                digest = result.stdout.strip()
                if digest and digest != "<none>":
                    return digest
        except Exception as e:
            logger.error(f"Error getting local digest: {e}")

        return None

    def pull_image(self, image: str, tag: str = "latest") -> bool:
        """
        Pull an image from registry.

        Args:
            image: Image name
            tag: Image tag

        Returns:
            True if successful
        """
        try:
            logger.info(f"Pulling {image}:{tag}...")
            result = subprocess.run(
                ["docker", "pull", f"{image}:{tag}"],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max
            )
            if result.returncode == 0:
                logger.info(f"Successfully pulled {image}:{tag}")
                return True
            else:
                logger.error(f"Pull failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error pulling image: {e}")

        return False

    def compose_up(self, compose_file: Path, service: str | None = None) -> bool:
        """
        Run docker compose up for a service.

        Args:
            compose_file: Path to docker-compose.yml
            service: Service name (optional, default all)

        Returns:
            True if successful
        """
        try:
            cmd = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
            if service:
                cmd.append(service)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes
                cwd=compose_file.parent,
            )
            if result.returncode == 0:
                logger.info("Compose up successful")
                return True
            else:
                logger.error(f"Compose up failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error running compose: {e}")

        return False

    def compose_pull(self, compose_file: Path, service: str | None = None) -> bool:
        """
        Run docker compose pull for a service.

        Args:
            compose_file: Path to docker-compose.yml
            service: Service name (optional, default all)

        Returns:
            True if successful
        """
        try:
            cmd = ["docker", "compose", "-f", str(compose_file), "pull"]
            if service:
                cmd.append(service)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
                cwd=compose_file.parent,
            )
            if result.returncode == 0:
                logger.info("Compose pull successful")
                return True
            else:
                logger.error(f"Compose pull failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error running compose pull: {e}")

        return False

    def restart_service(self, compose_file: Path, service: str) -> bool:
        """
        Restart a docker compose service.

        Args:
            compose_file: Path to docker-compose.yml
            service: Service name

        Returns:
            True if successful
        """
        try:
            # Pull first
            if not self.compose_pull(compose_file, service):
                return False

            # Then recreate
            cmd = ["docker", "compose", "-f", str(compose_file), "up", "-d", "--force-recreate", service]
            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=compose_file.parent,
            )
            if result.returncode == 0:
                logger.info(f"Service {service} restarted")
                return True
            else:
                logger.error(f"Restart failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error restarting service: {e}")

        return False

    def is_container_running(self, container_name: str) -> bool:
        """
        Check if a container is running.

        Args:
            container_name: Name of the container

        Returns:
            True if running
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception as e:
            logger.debug(f"Error checking container: {e}")
            return False

    def container_exists(self, container_name: str) -> bool:
        """
        Check if a container exists (running or stopped).

        Args:
            container_name: Name of the container

        Returns:
            True if exists
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def start_container(self, container_name: str) -> bool:
        """
        Start an existing container.

        Args:
            container_name: Name of the container

        Returns:
            True if successful
        """
        try:
            result = subprocess.run(
                ["docker", "start", container_name],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"Container {container_name} started")
                return True
            else:
                logger.error(f"Start failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Error starting container: {e}")

        return False

    def get_remote_image_digest(self, image: str, tag: str = "latest") -> str | None:
        """
        Get the digest of a remote image using docker buildx imagetools inspect.

        This method uses buildx imagetools which doesn't cache manifests,
        ensuring we always get the latest digest from the registry.

        Args:
            image: Image name (e.g., "ghcr.io/beachvar/beachvar-device")
            tag: Image tag

        Returns:
            Image digest (sha256:...) or None if not found
        """
        try:
            # Use docker buildx imagetools inspect - no cache issues
            result = subprocess.run(
                ["docker", "buildx", "imagetools", "inspect", f"{image}:{tag}", "--raw"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                # The raw output is the manifest itself - hash it to get digest
                manifest_content = result.stdout.strip()
                digest = "sha256:" + hashlib.sha256(manifest_content.encode()).hexdigest()
                logger.debug(f"Remote digest for {image}:{tag}: {digest}")
                return digest
            else:
                # Fallback to docker manifest inspect if buildx not available
                logger.debug(f"Buildx failed, trying manifest inspect: {result.stderr.strip()}")
                return self._get_remote_image_digest_fallback(image, tag)
        except Exception as e:
            logger.error(f"Error getting remote digest: {e}")
            return self._get_remote_image_digest_fallback(image, tag)

    def _get_remote_image_digest_fallback(self, image: str, tag: str = "latest") -> str | None:
        """
        Fallback method using docker manifest inspect.
        Note: This may use cached manifests.
        """
        try:
            result = subprocess.run(
                ["docker", "manifest", "inspect", f"{image}:{tag}", "--verbose"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                # Parse JSON output to get digest
                data = json.loads(result.stdout)
                # For multi-arch images, it's a list; for single arch, it's an object
                if isinstance(data, list):
                    # Get the first manifest's digest
                    if data and "Descriptor" in data[0]:
                        return data[0]["Descriptor"].get("digest")
                elif isinstance(data, dict):
                    if "Descriptor" in data:
                        return data["Descriptor"].get("digest")
            else:
                logger.warning(f"Manifest inspect failed for {image}:{tag}: {result.stderr.strip()}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing manifest JSON: {e}")
        except Exception as e:
            logger.error(f"Error getting remote digest (fallback): {e}")

        return None
