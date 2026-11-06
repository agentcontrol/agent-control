from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_control_server.config import settings
from agent_control_server.main import METRICS_PATH, add_prometheus_metrics


def test_metrics_endpoint_public(unauthenticated_client: TestClient) -> None:
    # Given: an unauthenticated client
    # When: requesting the metrics endpoint
    response = unauthenticated_client.get(METRICS_PATH)
    # Then: metrics are publicly accessible
    assert response.status_code == 200


def test_metrics_output_contains_default_prefix(unauthenticated_client: TestClient) -> None:
    # Given: default metrics are enabled with the configured prefix
    unauthenticated_client.get("/health")
    # When: requesting metrics output
    response = unauthenticated_client.get(METRICS_PATH)
    # Then: metrics include the configured prefix
    assert response.status_code == 200
    assert f"{settings.prometheus_metrics_prefix}_" in response.text


def test_metrics_output_contains_custom_prefix() -> None:
    # Given: a custom metrics prefix configured on a standalone app
    custom_prefix = "agent_control_server_test_metrics"
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    add_prometheus_metrics(app, custom_prefix)

    # When: exercising an endpoint and fetching metrics
    with TestClient(app) as client:
        client.get("/ping")
        response = client.get(METRICS_PATH)

    # Then: metrics include the custom prefix
    assert response.status_code == 200
    assert f"{custom_prefix}_" in response.text


def test_runtime_latency_buckets_resolve_the_500ms_slo() -> None:
    # Given: the public request histogram uses the server's configured boundaries.
    from agent_control_server.main import PROMETHEUS_BUCKETS

    # When: inspecting boundaries around the latency target.
    around_target = [x for x in PROMETHEUS_BUCKETS if 0.1 <= x <= 0.5]
    # Then: interpolation cannot span the previous 400 ms gap.
    assert around_target[0] == 0.1 and around_target[-1] == 0.5
    assert all(b - a <= 0.0250001 for a, b in zip(around_target, around_target[1:]))
