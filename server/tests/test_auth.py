"""Tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient

from agent_control_server.config import auth_settings

from .conftest import TEST_ADMIN_API_KEY, TEST_API_KEY


class TestHealthEndpoint:
    """Health endpoint should always be accessible without authentication."""

    def test_health_without_auth(self, unauthenticated_client: TestClient) -> None:
        """Given no API key, when requesting health, then returns 200 with healthy status."""
        # When:
        response = unauthenticated_client.get("/health")

        # Then:
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_with_auth(self, client: TestClient) -> None:
        """Given valid API key, when requesting health, then returns 200."""
        # When:
        response = client.get("/health")

        # Then:
        assert response.status_code == 200


class TestProtectedEndpoints:
    """Protected endpoints require valid API key."""

    def test_missing_api_key_returns_401(self, unauthenticated_client: TestClient) -> None:
        """Given no API key, when requesting protected endpoint, then returns 401."""
        # When:
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then:
        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_invalid_api_key_returns_401(self, app: object) -> None:
        """Given invalid API key, when requesting protected endpoint, then returns 401."""
        # Given:
        client = TestClient(
            app,
            raise_server_exceptions=True,
            headers={"X-API-Key": "wrong-key"},
        )

        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then:
        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_valid_api_key_succeeds(self, client: TestClient) -> None:
        """Given valid API key, when requesting protected endpoint, then request is accepted."""
        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then: (404 expected for non-existent resource, but NOT 401/403)
        assert response.status_code == 404

    def test_admin_key_works_on_protected_endpoints(self, admin_client: TestClient) -> None:
        """Given admin API key, when requesting protected endpoint, then request is accepted."""
        # When:
        response = admin_client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then: (404 expected for non-existent resource, but NOT 401/403)
        assert response.status_code == 404


class TestEvaluatorsEndpoint:
    """Evaluators endpoint requires valid API key (regular or admin)."""

    def test_regular_key_works_on_evaluators(self, client: TestClient) -> None:
        """Given regular API key, when listing evaluators, then returns 200."""
        # When:
        response = client.get("/api/v1/evaluators")

        # Then:
        assert response.status_code == 200

    def test_admin_key_works_on_evaluators(self, admin_client: TestClient) -> None:
        """Given admin API key, when listing evaluators, then returns 200."""
        # When:
        response = admin_client.get("/api/v1/evaluators")

        # Then:
        assert response.status_code == 200

    def test_missing_key_returns_401_on_evaluators(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Given no API key, when listing evaluators, then returns 401."""
        # When:
        response = unauthenticated_client.get("/api/v1/evaluators")

        # Then:
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
        # When:
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then: (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_evaluators_accessible_when_disabled(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Given auth disabled, when listing evaluators without API key, then returns 200."""
        # When:
        response = unauthenticated_client.get("/api/v1/evaluators")

        # Then:
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
        # Given:
        client = TestClient(app, headers={"X-API-Key": "key1"})

        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then: (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_second_key_works(self, app: object) -> None:
        """Given multiple API keys configured, when using second key, then request succeeds."""
        # Given:
        client = TestClient(app, headers={"X-API-Key": "key2"})

        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then: (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_admin_key_works_as_regular_key(self, app: object) -> None:
        """Given admin API key, when requesting regular endpoint, then request succeeds."""
        # Given:
        client = TestClient(app, headers={"X-API-Key": "admin1"})

        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then: (404 for non-existent resource, but NOT 401)
        assert response.status_code == 404

    def test_unlisted_key_rejected(self, app: object) -> None:
        """Given unlisted API key, when requesting endpoint, then returns 401."""
        # Given:
        client = TestClient(app, headers={"X-API-Key": "key4"})

        # When:
        response = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")

        # Then:
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
        # When:
        response = unauthenticated_client.get(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000"
        )

        # Then:
        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "AUTH_MISCONFIGURED"
        assert body["detail"] == "Server authentication is misconfigured. Contact administrator."


class TestOptionalApiKey:
    """Behavioral tests for optional_api_key dependency."""

    def _make_optional_app(self) -> TestClient:
        from fastapi import Depends, FastAPI
        from agent_control_server.auth import optional_api_key

        app = FastAPI()

        @app.get("/maybe-auth")
        def maybe_auth(client=Depends(optional_api_key)) -> dict[str, object]:
            return {
                "auth": client is not None,
                "is_admin": client.is_admin if client else False,
                "key_id": client.key_id if client else None,
            }

        return TestClient(app)

    def test_optional_api_key_auth_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given: auth disabled
        monkeypatch.setattr(auth_settings, "api_key_enabled", False)

        # When: calling endpoint with optional auth
        client = self._make_optional_app()
        response = client.get("/maybe-auth")

        # Then: client is treated as unauthenticated
        assert response.status_code == 200
        assert response.json()["auth"] is False

    def test_optional_api_key_missing_header_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given: auth enabled with configured keys
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "user-key")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "admin-key")
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

        # When: calling endpoint without header
        client = self._make_optional_app()
        response = client.get("/maybe-auth")

        # Then: client is treated as unauthenticated
        assert response.status_code == 200
        assert response.json()["auth"] is False

    def test_optional_api_key_invalid_header_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given: auth enabled with configured keys
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "user-key")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "admin-key")
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

        # When: calling endpoint with invalid header
        client = self._make_optional_app()
        response = client.get("/maybe-auth", headers={"X-API-Key": "invalid-key"})

        # Then: client is treated as unauthenticated
        assert response.status_code == 200
        assert response.json()["auth"] is False

    def test_optional_api_key_admin_header_sets_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given: auth enabled with admin key
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "user-key")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "admin-key-123456789")
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

        # When: calling endpoint with admin header
        client = self._make_optional_app()
        response = client.get("/maybe-auth", headers={"X-API-Key": "admin-key-123456789"})

        # Then: client is authenticated as admin with masked key id
        assert response.status_code == 200
        body = response.json()
        assert body["auth"] is True
        assert body["is_admin"] is True
        assert body["key_id"].endswith("...")

    def test_require_admin_key_rejects_non_admin(
        self, app: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given: auth enabled with a non-admin key
        monkeypatch.setattr(auth_settings, "api_key_enabled", True)
        monkeypatch.setattr(auth_settings, "api_keys", "user-key")
        monkeypatch.setattr(auth_settings, "admin_api_keys", "admin-key")
        for attr in ("_parsed_api_keys", "_parsed_admin_api_keys", "_all_valid_keys"):
            auth_settings.__dict__.pop(attr, None)

        # When: requiring admin key on an endpoint
        from fastapi import Depends, FastAPI
        from agent_control_server.auth import require_admin_key

        local_app = FastAPI()

        @local_app.get("/admin", dependencies=[Depends(require_admin_key)])
        def admin_route() -> dict[str, bool]:
            return {"ok": True}

        client = TestClient(local_app, headers={"X-API-Key": "user-key"})
        response = client.get("/admin")

        # Then: forbidden is returned
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()


class TestApiKeyHelpers:
    """Behavioral tests for API key helper utilities."""

    def test_authenticated_client_key_id_masks_short_key(self) -> None:
        # Given: a client with a short key
        from agent_control_server.auth import AuthenticatedClient, AuthLevel

        client = AuthenticatedClient(api_key="short", is_admin=False, auth_level=AuthLevel.API_KEY)

        # When: accessing key_id
        key_id = client.key_id

        # Then: key is masked
        assert key_id == "***"

    def test_get_api_key_from_header_extracts_value(self) -> None:
        # Given: a route that returns raw API key header
        from fastapi import Depends, FastAPI
        from agent_control_server.auth import get_api_key_from_header

        app = FastAPI()

        @app.get("/raw")
        def raw_key(key: str | None = Depends(get_api_key_from_header)) -> dict[str, str | None]:
            return {"key": key}

        client = TestClient(app)

        # When: sending a request with API key header
        response = client.get("/raw", headers={"X-API-Key": "raw-key"})

        # Then: raw key is returned
        assert response.status_code == 200
        assert response.json()["key"] == "raw-key"

    def test_get_api_key_from_header_allows_missing(self) -> None:
        # Given: a route that returns raw API key header
        from fastapi import Depends, FastAPI
        from agent_control_server.auth import get_api_key_from_header

        app = FastAPI()

        @app.get("/raw")
        def raw_key(key: str | None = Depends(get_api_key_from_header)) -> dict[str, str | None]:
            return {"key": key}

        client = TestClient(app)

        # When: sending a request without API key header
        response = client.get("/raw")

        # Then: key is None
        assert response.status_code == 200
        assert response.json()["key"] is None
