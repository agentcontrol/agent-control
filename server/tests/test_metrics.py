from agent_control_server.config import settings
from agent_control_server.main import METRICS_PATH, add_prometheus_metrics
from agent_control_server.metrics import (
    observe_evaluation_stage,
    prometheus_evaluation_observer,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def test_metrics_output_contains_evaluation_timing_metrics(
    unauthenticated_client: TestClient,
) -> None:
    # Given: evaluation timing observations have been recorded
    observe_evaluation_stage(stage="engine", outcome="success", duration_seconds=0.001)
    prometheus_evaluation_observer.observe_evaluator_queue_duration(
        evaluator_name="test-evaluator",
        duration_seconds=0.001,
    )
    prometheus_evaluation_observer.observe_evaluator_duration(
        evaluator_name="test-evaluator",
        outcome="success",
        duration_seconds=0.002,
    )
    prometheus_evaluation_observer.observe_control_duration(
        action="observe",
        outcome="not_matched",
        duration_seconds=0.003,
    )

    # When: requesting metrics output
    response = unauthenticated_client.get(METRICS_PATH)

    # Then: the internal evaluation timing series are exported
    assert response.status_code == 200
    assert "agent_control_server_evaluation_stage_duration_seconds" in response.text
    assert "agent_control_server_engine_evaluator_queue_duration_seconds" in response.text
    assert "agent_control_server_engine_evaluator_duration_seconds" in response.text
    assert "agent_control_server_engine_control_duration_seconds" in response.text
