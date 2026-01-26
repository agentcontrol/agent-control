from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_control_server.config import settings
from agent_control_server.main import METRICS_PATH, add_prometheus_metrics


def test_metrics_endpoint_public(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get(METRICS_PATH)
    assert response.status_code == 200


def test_metrics_output_contains_default_prefix(unauthenticated_client: TestClient) -> None:
    unauthenticated_client.get("/health")
    response = unauthenticated_client.get(METRICS_PATH)
    assert response.status_code == 200
    assert f"{settings.prometheus_metrics_prefix}_" in response.text


def test_metrics_output_contains_custom_prefix() -> None:
    custom_prefix = "agent_control_server_test_metrics"
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    add_prometheus_metrics(app, custom_prefix)

    with TestClient(app) as client:
        client.get("/ping")
        response = client.get(METRICS_PATH)

    assert response.status_code == 200
    assert f"{custom_prefix}_" in response.text
