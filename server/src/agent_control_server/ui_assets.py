"""Serve an exported Agent Control UI bundle from the FastAPI server."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import ui_settings

logger = logging.getLogger(__name__)


def get_ui_dist_dir() -> Path | None:
    """Resolve the static UI bundle directory if one is available."""
    configured_dist_dir = ui_settings.dist_dir
    if configured_dist_dir:
        candidate = Path(configured_dist_dir).expanduser().resolve()
        if candidate.is_dir():
            return candidate
        logger.warning("Configured UI dist dir does not exist: %s", candidate)

    server_dir = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]
    candidates = (
        server_dir / "ui-dist",
        repo_root / "ui" / "out",
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    return None


def resolve_ui_asset_path(ui_dist_dir: Path, request_path: str) -> Path | None:
    """Resolve a request path to a concrete file inside the exported UI bundle."""
    stripped_path = request_path.lstrip("/")
    relative_path = PurePosixPath(stripped_path)

    if any(part == ".." for part in relative_path.parts):
        return None

    if stripped_path in {"", "."}:
        return ui_dist_dir / "index.html"

    direct_candidate = ui_dist_dir.joinpath(*relative_path.parts)
    if direct_candidate.is_file():
        return direct_candidate

    html_candidate = direct_candidate.with_suffix(".html")
    if html_candidate.is_file():
        return html_candidate

    index_candidate = ui_dist_dir.joinpath(*relative_path.parts, "index.html")
    if index_candidate.is_file():
        return index_candidate

    if direct_candidate.name and "." in direct_candidate.name:
        return None

    fallback_entrypoint = ui_dist_dir / "index.html"
    if fallback_entrypoint.is_file():
        return fallback_entrypoint

    return None


def configure_ui_routes(app: FastAPI, ui_dist_dir: Path | None = None) -> None:
    """Serve an exported UI bundle if one is available on disk."""
    dist_dir = ui_dist_dir or get_ui_dist_dir()
    if dist_dir is None:
        logger.info("No exported Agent Control UI bundle found; skipping static UI routes")
        return

    logger.info("Serving exported Agent Control UI bundle from %s", dist_dir)

    @app.get("/{ui_path:path}", include_in_schema=False)
    async def serve_ui(ui_path: str) -> FileResponse:
        request_path = f"/{ui_path}" if ui_path else "/"
        if request_path == "/api" or request_path.startswith("/api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        asset_path = resolve_ui_asset_path(dist_dir, request_path)
        if asset_path is None:
            raise HTTPException(status_code=404, detail="Not Found")

        return FileResponse(asset_path)
