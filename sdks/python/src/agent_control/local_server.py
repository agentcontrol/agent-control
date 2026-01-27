"""
Local Docker server helper for Agent Control.

This module provides a simple way to start the Agent Control server and its
PostgreSQL dependency using Docker, then wait until the server is healthy.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

DEFAULT_IMAGE = "galileoai/agent-control-server:latest"
DEFAULT_NETWORK = "agent-control-local"
DEFAULT_SERVER_CONTAINER = "agent-control-server"
DEFAULT_POSTGRES_CONTAINER = "agent-control-postgres"
DEFAULT_POSTGRES_VOLUME = "agent-control-pgdata"


@dataclass(frozen=True)
class LocalServerHandle:
    """Handle for a locally running server container."""

    base_url: str
    server_container: str
    postgres_container: str | None

    def stop(self, *, remove: bool = True, stop_postgres: bool = False) -> None:
        """Stop the server container (and optionally postgres)."""
        _stop_container(self.server_container, remove=remove)
        if stop_postgres and self.postgres_container:
            _stop_container(self.postgres_container, remove=remove)

    def logs(self, *, tail: int = 200) -> str:
        """Return the latest logs from the server container."""
        result = _run_command(
            ["docker", "logs", "--tail", str(tail), self.server_container],
            capture_output=True,
        )
        return result.stdout


def run_local_server(
    *,
    image: str = DEFAULT_IMAGE,
    host: str = "127.0.0.1",
    port: int = 8000,
    api_key: str | None = None,
    timeout: float = 30.0,
    pull: bool = True,
    start_postgres: bool = True,
    db_url: str | None = None,
    migrate: bool = True,
    replace_existing: bool = True,
    network_name: str = DEFAULT_NETWORK,
    server_container: str = DEFAULT_SERVER_CONTAINER,
    postgres_container: str = DEFAULT_POSTGRES_CONTAINER,
    postgres_volume: str = DEFAULT_POSTGRES_VOLUME,
) -> LocalServerHandle:
    """
    Start the Agent Control server Docker image locally.

    This will optionally start a PostgreSQL container, run migrations, and wait
    for the server health endpoint to become available.

    Args:
        image: Docker image tag to run.
        host: Local host to bind the server to.
        port: Local port to bind the server to.
        api_key: Optional API key to enable server auth.
        timeout: Seconds to wait for readiness checks.
        pull: If True, pull the image before running.
        start_postgres: If True, start a local PostgreSQL container.
        db_url: Optional DB URL override (disables postgres container if set).
        migrate: If True, run alembic migrations after start.
        replace_existing: If True, replace existing containers with same names.
        network_name: Docker network to use for local containers.
        server_container: Server container name.
        postgres_container: Postgres container name.
        postgres_volume: Named volume for postgres data.

    Returns:
        LocalServerHandle with base URL and container names.

    Raises:
        RuntimeError: If docker is unavailable or server fails to start.
    """
    _ensure_docker_available()

    if not start_postgres and not db_url:
        raise ValueError("db_url is required when start_postgres is False.")

    if pull:
        _run_command(["docker", "pull", image], capture_output=False)

    _ensure_network(network_name)

    final_db_url = db_url
    started_postgres = False
    if start_postgres and not db_url:
        _start_postgres(
            container_name=postgres_container,
            volume_name=postgres_volume,
            network_name=network_name,
            replace_existing=replace_existing,
        )
        started_postgres = True
        final_db_url = (
            f"postgresql+psycopg://agent_control:agent_control@{postgres_container}:5432/"
            "agent_control"
        )
        _wait_for_postgres(postgres_container, timeout=timeout)

    if replace_existing:
        _stop_container(server_container, remove=True)

    env_vars = {
        "HOST": "0.0.0.0",
        "PORT": "8000",
    }
    if final_db_url:
        env_vars["DB_URL"] = final_db_url
    if api_key:
        env_vars["AGENT_CONTROL_API_KEY_ENABLED"] = "true"
        env_vars["AGENT_CONTROL_API_KEYS"] = api_key

    run_args = [
        "docker",
        "run",
        "-d",
        "--name",
        server_container,
        "--network",
        network_name,
        "-p",
        f"{host}:{port}:8000",
    ]
    for key, value in env_vars.items():
        run_args.extend(["-e", f"{key}={value}"])
    run_args.append(image)

    _run_command(run_args, capture_output=False)

    if migrate:
        _run_migrations(server_container)

    base_url = f"http://{host}:{port}"
    _wait_for_health(base_url, timeout=timeout)

    return LocalServerHandle(
        base_url=base_url,
        server_container=server_container,
        postgres_container=postgres_container if started_postgres else None,
    )


def _ensure_docker_available() -> None:
    if _run_command(["docker", "info"], check=False).returncode != 0:
        raise RuntimeError(
            "Docker is not available. Please install Docker Desktop and ensure it is running."
        )


def _ensure_network(network_name: str) -> None:
    result = _run_command(
        ["docker", "network", "ls", "--filter", f"name=^{network_name}$", "--format", "{{.Name}}"],
        check=False,
    )
    if network_name not in result.stdout.splitlines():
        _run_command(["docker", "network", "create", network_name], capture_output=False)


def _start_postgres(
    *,
    container_name: str,
    volume_name: str,
    network_name: str,
    replace_existing: bool,
) -> None:
    if replace_existing:
        _stop_container(container_name, remove=True)

    if _container_exists(container_name):
        if not _container_running(container_name):
            _run_command(["docker", "start", container_name], capture_output=False)
        return

    _run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            network_name,
            "-e",
            "POSTGRES_DB=agent_control",
            "-e",
            "POSTGRES_USER=agent_control",
            "-e",
            "POSTGRES_PASSWORD=agent_control",
            "-v",
            f"{volume_name}:/var/lib/postgresql/data",
            "postgres:16-alpine",
        ],
        capture_output=False,
    )


def _wait_for_postgres(container_name: str, *, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _run_command(
            [
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-U",
                "agent_control",
                "-d",
                "agent_control",
            ],
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready in time.")


def _run_migrations(server_container: str) -> None:
    _run_command(
        ["docker", "exec", server_container, "sh", "-c", "cd /app/server && alembic upgrade head"],
        capture_output=False,
    )


def _wait_for_health(base_url: str, *, timeout: float) -> None:
    deadline = time.time() + timeout
    url = f"{base_url}/health"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(1)
    raise RuntimeError(f"Server did not become healthy in time at {url}.")


def _stop_container(container_name: str, *, remove: bool) -> None:
    if not _container_exists(container_name):
        return
    _run_command(["docker", "stop", container_name], check=False, capture_output=False)
    if remove:
        _run_command(["docker", "rm", container_name], check=False, capture_output=False)


def _container_exists(container_name: str) -> bool:
    result = _run_command(
        ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return container_name in result.stdout.splitlines()


def _container_running(container_name: str) -> bool:
    result = _run_command(
        ["docker", "ps", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return container_name in result.stdout.splitlines()


def _run_command(
    args: list[str],
    *,
    check: bool = True,
    capture_output: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=capture_output,
        env=env,
    )


def _parse_args() -> tuple[int, str | None]:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Agent Control server locally via Docker."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Local port to bind (default: 8000).",
    )
    parser.add_argument("--api-key", type=str, default=None, help="Optional API key for auth.")
    args = parser.parse_args()
    return args.port, args.api_key


def main() -> None:
    """CLI entrypoint for quick local server start."""
    port, api_key = _parse_args()
    handle = run_local_server(port=port, api_key=api_key)
    print(f"Agent Control server running at {handle.base_url}")


if __name__ == "__main__":
    main()
