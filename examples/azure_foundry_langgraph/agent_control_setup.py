import httpx

import agent_control

from settings import settings


def check_server_health() -> None:
    """Fail fast if the Agent Control server is unreachable."""
    url = f"{settings.agent_control_url}/health"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Agent Control server not reachable at {url}: {exc}"
        ) from exc


def bootstrap_agent_control() -> None:
    """Initialize the Agent Control SDK and verify server connectivity."""
    check_server_health()

    init_kwargs = {
        "agent_name": settings.agent_name,
        "agent_description": "Customer support agent with Agent Control runtime guardrails",
        "server_url": settings.agent_control_url,
        "observability_enabled": True,
        "policy_refresh_interval_seconds": settings.policy_refresh_interval_seconds,
    }
    if settings.agent_control_api_key:
        init_kwargs["api_key"] = settings.agent_control_api_key

    agent_control.init(**init_kwargs)
