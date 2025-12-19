"""
Docker operations for BeachVar Agent.

Provides Docker and Docker Compose management functions.
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

    def try_pull_without_auth(self, image: str, tag: str = "latest") -> bool:
        """
        Try to pull an image without authentication.
        This is useful for public images or when already logged in.

        Args:
            image: Image name
            tag: Image tag

        Returns:
            True if successful, False if auth might be needed
        """
        try:
            logger.debug(f"Trying to pull {image}:{tag} without explicit auth...")
            result = subprocess.run(
                ["docker", "pull", f"{image}:{tag}"],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                logger.info(f"Successfully pulled {image}:{tag} (no auth needed)")
                return True
            else:
                # Check if it's an auth error
                stderr = result.stderr.lower()
                if "unauthorized" in stderr or "denied" in stderr or "authentication" in stderr:
                    logger.debug(f"Pull requires authentication for {image}:{tag}")
                else:
                    logger.warning(f"Pull failed (non-auth error): {result.stderr}")
                return False
        except Exception as e:
            logger.debug(f"Error in unauthenticated pull: {e}")
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

    def _ensure_helper_image(self) -> bool:
        """
        Ensure the docker:cli helper image is available locally.

        Returns:
            True if image is available
        """
        try:
            # Check if image exists
            result = subprocess.run(
                ["docker", "images", "-q", "docker:cli"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True

            # Image doesn't exist, pull it
            logger.info("Pulling docker:cli helper image...")
            pull_result = subprocess.run(
                ["docker", "pull", "docker:cli"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if pull_result.returncode == 0:
                logger.info("Helper image pulled successfully")
                return True
            else:
                logger.error(f"Failed to pull helper image: {pull_result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error checking/pulling helper image: {e}")
            return False

    def _run_compose_via_docker_api(
        self,
        compose_file: Path,
        command: str,
        container_name: str = "beachvar-helper",
    ) -> bool:
        """
        Run a docker compose command using Docker API via Unix socket.

        Creates a temporary container via Docker API that runs the compose
        command. Since the API call returns immediately after creating the
        container, and the container is independent, it continues running
        even after the agent container is killed.

        Args:
            compose_file: Path to docker-compose.yml
            command: The compose command to run (e.g., "up -d device cloudflared ttyd")
            container_name: Name for the helper container

        Returns:
            True if container was created and started successfully
        """
        import socket
        import urllib.parse

        # Ensure helper image is available
        if not self._ensure_helper_image():
            logger.error("Helper image not available, falling back to subprocess")
            return False

        compose_dir = str(compose_file.parent)
        compose_filename = compose_file.name

        # Container configuration
        container_config = {
            "Image": "docker:cli",
            "Cmd": ["sh", "-c", f"docker compose -f {compose_filename} {command}"],
            "WorkingDir": compose_dir,
            "HostConfig": {
                "AutoRemove": True,
                "Binds": [
                    "/var/run/docker.sock:/var/run/docker.sock",
                    f"{compose_dir}:{compose_dir}:ro",
                ],
            },
        }

        try:
            # First, try to remove any existing container with the same name
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect("/var/run/docker.sock")
            delete_request = (
                f"DELETE /containers/{urllib.parse.quote(container_name)}?force=true HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            ).encode()
            sock.sendall(delete_request)
            sock.recv(4096)  # Ignore response
            sock.close()

            # Connect to Docker socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect("/var/run/docker.sock")

            # Create container
            body = json.dumps(container_config).encode()
            request = (
                f"POST /containers/create?name={urllib.parse.quote(container_name)} HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            sock.sendall(request)
            response = sock.recv(4096).decode()
            sock.close()

            # Check if container was created (201)
            if "201 Created" not in response:
                logger.error(f"Failed to create helper container: {response[:200]}")
                return False

            # Parse container ID
            body_start = response.find("\r\n\r\n") + 4
            response_body = response[body_start:]
            container_id = json.loads(response_body).get("Id", "")[:12]

            # Start the container
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect("/var/run/docker.sock")
            start_request = (
                f"POST /containers/{container_name}/start HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            ).encode()
            sock.sendall(start_request)
            start_response = sock.recv(4096).decode()
            sock.close()

            if "204 No Content" in start_response or "304 Not Modified" in start_response:
                logger.info(f"Helper container started via Docker API: {container_id}")
                return True
            else:
                logger.error(f"Failed to start helper container: {start_response[:200]}")
                return False

        except Exception as e:
            logger.error(f"Error using Docker API: {e}")
            return False

    def compose_up_detached(
        self,
        compose_file: Path,
        services: list[str] | None = None,
        force_recreate: bool = False,
    ) -> bool:
        """
        Start docker compose services using a detached helper container.

        This method uses the Docker API to spawn a helper container that
        runs 'docker compose up -d'. This is useful when the agent needs
        to start services without risking being killed itself.

        Args:
            compose_file: Path to docker-compose.yml
            services: List of service names to start (default: all except agent)
            force_recreate: If True, use --force-recreate to recreate containers

        Returns:
            True if helper container was started successfully
        """
        force_flag = "--force-recreate " if force_recreate else ""
        if services:
            services_str = " ".join(services)
            command = f"up -d {force_flag}{services_str}"
        else:
            # Start all services including agent (for self-updates)
            command = f"up -d {force_flag}agent device cloudflared ttyd"

        logger.info(f"Starting services via Docker API: {command}")
        return self._run_compose_via_docker_api(
            compose_file,
            command,
            container_name="beachvar-starter",
        )

    def restart_service_detached(self, compose_file: Path, service: str) -> bool:
        """
        Restart a docker compose service using Docker API via Unix socket.

        Creates a temporary container via Docker API that runs the compose
        command. Since the API call returns immediately after creating the
        container, and the container is independent, it continues running
        even after the agent container is killed.

        Args:
            compose_file: Path to docker-compose.yml
            service: Service name

        Returns:
            True if container was created successfully
        """
        command = f"up -d --force-recreate {service}"
        logger.info(f"Restarting service via Docker API: {service}")
        return self._run_compose_via_docker_api(
            compose_file,
            command,
            container_name="beachvar-agent-updater",
        )

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

        First tries exact name match, then falls back to partial match
        (for cases where Docker Compose prefixes container names).

        Args:
            container_name: Name of the container

        Returns:
            True if running
        """
        try:
            # First try exact name match
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                return True

            # If exact match fails, try finding container with name pattern
            # This handles cases where Docker prefixes container names
            result = subprocess.run(
                [
                    "docker", "ps", "--filter", f"name={container_name}",
                    "--format", "{{.State}}"
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                states = result.stdout.strip().split('\n')
                # Check if any container matching the name is running
                for state in states:
                    if state.lower() == "running":
                        return True

            return False
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
