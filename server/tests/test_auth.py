"""Tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient

from agent_control_server.config import auth_settings

from .conftest import TEST_ADMIN_API_KEY, TEST_API_KEY


class TestHealthEndpoint:
    """Health endpoint should always be accessible without authentication."""

    def test_health_without_auth(self, unauthenticated_client: TestClient) -> None:
        """Given no API key, when requesting health, then returns 200 with healthy status."""
        # When
        response = unauthenticated_client.get("/health")

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_with_auth(self, client: TestClient) -> None:
        """Given valid API key, when requesting health, then returns 200."""
        # When
        response = client.get("/health")

        # Then
        assert response.status_code == 200


class TestProtectedEndpoints:
    """Protected endpoints require valid API key."""

    def test_missing_api_key_returns_401(self, unauthenticated_client: TestClient) -> None:
        """Given no API key, when requesting protected endpoint, then returns 401."""
        # When
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then
        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_invalid_api_key_returns_401(self, app: object) -> None:
        """Given invalid API key, when requesting protected endpoint, then returns 401."""
        # Given
        client = TestClient(
            app,
            raise_server_exceptions=True,
            headers={"X-API-Key": "wrong-key"},
        )

        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then
        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_valid_api_key_succeeds(self, client: TestClient) -> None:
        """Given valid API key, when requesting protected endpoint, then request is accepted."""
        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then (404 expected for non-existent resource, but NOT 401/403)
        assert response.status_code == 404

    def test_admin_key_works_on_protected_endpoints(self, admin_client: TestClient) -> None:
        """Given admin API key, when requesting protected endpoint, then request is accepted."""
        # When
        response = admin_client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then (404 expected for non-existent resource, but NOT 401/403)
        assert response.status_code == 404


class TestEvaluatorsEndpoint:
    """Evaluators endpoint requires valid API key (regular or admin)."""

    def test_regular_key_works_on_evaluators(self, client: TestClient) -> None:
        """Given regular API key, when listing evaluators, then returns 200."""
        # When
        response = client.get("/api/v1/evaluators")

        # Then
        assert response.status_code == 200

    def test_admin_key_works_on_evaluators(self, admin_client: TestClient) -> None:
        """Given admin API key, when listing evaluators, then returns 200."""
        # When
        response = admin_client.get("/api/v1/evaluators")

        # Then
        assert response.status_code == 200

    def test_missing_key_returns_401_on_evaluators(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Given no API key, when listing evaluators, then returns 401."""
        # When
        response = unauthenticated_client.get("/api/v1/evaluators")

        # Then
        assert response.status_code == 401


class TestAuthDisabled:
    """When auth is disabled, all requests should succeed."""

    @pytest.fixture(autouse=True)
    def disable_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disable auth for tests in this class."""
        monkeypatch.setattr(auth_settings, "api_key_enabled", False)

    def test_no_key_allowed_when_disabled(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Given auth disabled, when requesting without API key, then request succeeds."""
        # When
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_evaluators_accessible_when_disabled(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Given auth disabled, when listing evaluators without API key, then returns 200."""
        # When
        response = unauthenticated_client.get("/api/v1/evaluators")

        # Then
        assert response.status_code == 200


class TestMultipleApiKeys:
    """Test support for multiple API keys (key rotation)."""

    @pytest.fixture(autouse=True)
    def setup_multiple_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configure multiple API keys for key rotation testing."""
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "key1,key2,key3")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "admin1,admin2")
        # Clear cached properties so they get recomputed with new values
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

    def test_first_key_works(self, app: object) -> None:
        """Given multiple API keys configured, when using first key, then request succeeds."""
        # Given
        client = TestClient(app, headers={"X-API-Key": "key1"})

        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_second_key_works(self, app: object) -> None:
        """Given multiple API keys configured, when using second key, then request succeeds."""
        # Given
        client = TestClient(app, headers={"X-API-Key": "key2"})

        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_admin_key_works_as_regular_key(self, app: object) -> None:
        """Given admin API key, when requesting regular endpoint, then request succeeds."""
        # Given
        client = TestClient(app, headers={"X-API-Key": "admin1"})

        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_unlisted_key_rejected(self, app: object) -> None:
        """Given unlisted API key, when requesting endpoint, then returns 401."""
        # Given
        client = TestClient(app, headers={"X-API-Key": "key4"})

        # When
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then
        assert response.status_code == 401


class TestAuthMisconfiguration:
    """Test behavior when auth is misconfigured."""

    @pytest.fixture(autouse=True)
    def setup_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enable auth but configure no keys (misconfiguration)."""
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "")
        # Clear cached properties so they get recomputed with new values
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

    def test_misconfigured_returns_500(self, unauthenticated_client: TestClient) -> None:
        """Given auth enabled but no keys configured, when requesting, then returns 500."""
        # When
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then
        assert response.status_code == 500
        assert "misconfigured" in response.json()["detail"]

