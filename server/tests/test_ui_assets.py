from __future__ import annotations

from pathlib import Path

from agent_control_server.ui_assets import (
    configure_ui_routes,
    get_ui_dist_dir,
    resolve_ui_asset_path,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_ui_bundle(root: Path) -> Path:
    (root / "agents").mkdir(parents=True)
    (root / "_next" / "static").mkdir(parents=True)

    (root / "index.html").write_text("<html><body>home</body></html>")
    (root / "agents" / "index.html").write_text("<html><body>agents</body></html>")
    (root / "_next" / "static" / "app.js").write_text("console.log('agent-control');")
    (root / "site.webmanifest").write_text('{"name":"agent-control"}')

    return root


def test_get_ui_dist_dir_prefers_configured_directory(
    monkeypatch, tmp_path: Path
) -> None:
    ui_bundle = _create_ui_bundle(tmp_path / "configured-ui")

    from agent_control_server.config import ui_settings

    monkeypatch.setattr(ui_settings, "dist_dir", str(ui_bundle))

    assert get_ui_dist_dir() == ui_bundle.resolve()


def test_resolve_ui_asset_path_serves_route_specific_index(tmp_path: Path) -> None:
    ui_bundle = _create_ui_bundle(tmp_path / "ui")

    assert resolve_ui_asset_path(ui_bundle, "/") == ui_bundle / "index.html"
    assert (
        resolve_ui_asset_path(ui_bundle, "/agents")
        == ui_bundle / "agents" / "index.html"
    )
    assert (
        resolve_ui_asset_path(ui_bundle, "/_next/static/app.js")
        == ui_bundle / "_next" / "static" / "app.js"
    )
    assert (
        resolve_ui_asset_path(ui_bundle, "/site.webmanifest")
        == ui_bundle / "site.webmanifest"
    )


def test_resolve_ui_asset_path_falls_back_to_root_index_for_unknown_routes(
    tmp_path: Path,
) -> None:
    ui_bundle = _create_ui_bundle(tmp_path / "ui")

    assert (
        resolve_ui_asset_path(ui_bundle, "/does-not-exist")
        == ui_bundle / "index.html"
    )
    assert resolve_ui_asset_path(ui_bundle, "/missing.js") is None


def test_configure_ui_routes_preserves_api_404s(tmp_path: Path) -> None:
    ui_bundle = _create_ui_bundle(tmp_path / "ui")
    app = FastAPI()
    configure_ui_routes(app, ui_bundle)

    with TestClient(app) as client:
        response = client.get("/api/not-found")

    assert response.status_code == 404


def test_configure_ui_routes_serves_exported_assets_and_pages(tmp_path: Path) -> None:
    ui_bundle = _create_ui_bundle(tmp_path / "ui")
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    configure_ui_routes(app, ui_bundle)

    with TestClient(app) as client:
        agents_page = client.get("/agents")
        static_asset = client.get("/_next/static/app.js")
        health = client.get("/health")
        unknown_route = client.get("/new-route")

    assert agents_page.status_code == 200
    assert "agents" in agents_page.text

    assert static_asset.status_code == 200
    assert "agent-control" in static_asset.text

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    assert unknown_route.status_code == 200
    assert "home" in unknown_route.text
