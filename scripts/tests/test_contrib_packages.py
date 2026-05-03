"""Tests for contrib package discovery and verification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "contrib_packages.py"


def _load_module() -> ModuleType:
    """Load the contrib package script as a module for testing."""

    module_name = "contrib_packages_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, contents: str) -> None:
    """Write a text file, creating parent directories first."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).strip() + "\n")


def _write_fake_repo(
    root: Path,
    *,
    include_version_entry: bool = True,
    include_builtin_extra: bool = True,
    include_builtin_source: bool = True,
) -> None:
    """Create a minimal repo layout that exercises contrib package wiring."""

    version_entry = (
        '"evaluators/contrib/example/pyproject.toml:project.version"'
        if include_version_entry
        else ""
    )
    extra_entry = (
        'example = ["agent-control-evaluator-example>=1.0.0"]'
        if include_builtin_extra
        else ""
    )
    source_entry = (
        'agent-control-evaluator-example = { path = "../contrib/example", editable = true }'
        if include_builtin_source
        else ""
    )

    _write_text(
        root / "pyproject.toml",
        f"""
        [project]
        name = "agent-control"
        version = "1.0.0"

        [tool.semantic_release]
        version_toml = [
            "pyproject.toml:project.version",
            {version_entry}
        ]
        """,
    )
    _write_text(
        root / "evaluators" / "builtin" / "pyproject.toml",
        f"""
        [project]
        name = "agent-control-evaluators"
        version = "1.0.0"

        [project.optional-dependencies]
        dev = []
        {extra_entry}

        [tool.uv.sources]
        agent-control-models = {{ workspace = true }}
        {source_entry}
        """,
    )
    _write_text(
        root / "evaluators" / "contrib" / "example" / "pyproject.toml",
        """
        [project]
        name = "agent-control-evaluator-example"
        version = "1.0.0"

        [project.entry-points."agent_control.evaluators"]
        example = "agent_control_evaluator_example:ExampleEvaluator"
        """,
    )


def test_discover_contrib_packages_skips_template_and_non_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a fake repo with one real contrib package plus ignored directories
    module = _load_module()
    repo_root = tmp_path / "repo"
    _write_fake_repo(repo_root)
    (repo_root / "evaluators" / "contrib" / "template").mkdir(parents=True)
    (repo_root / "evaluators" / "contrib" / "notes").mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CONTRIB_ROOT", repo_root / "evaluators" / "contrib")

    # When: discovering contrib packages
    packages = module.discover_contrib_packages()

    # Then: only the real package is returned
    assert [package.name for package in packages] == ["example"]
    assert packages[0].directory == "evaluators/contrib/example"
    assert packages[0].package == "agent-control-evaluator-example"


def test_verify_contrib_packages_reports_missing_root_and_builtin_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a contrib package that is missing version, extra, and source wiring
    module = _load_module()
    repo_root = tmp_path / "repo"
    _write_fake_repo(
        repo_root,
        include_version_entry=False,
        include_builtin_extra=False,
        include_builtin_source=False,
    )
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CONTRIB_ROOT", repo_root / "evaluators" / "contrib")

    # When: verifying the contrib package wiring
    packages = module.discover_contrib_packages()
    errors = module.verify_contrib_packages(packages)

    # Then: the missing contract pieces are reported explicitly
    assert any("Missing semantic-release version wiring" in error for error in errors)
    assert any("Missing builtin extra" in error for error in errors)
    assert any("Missing uv source" in error for error in errors)


def test_verify_contrib_packages_accepts_complete_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a contrib package with complete root and builtin wiring
    module = _load_module()
    repo_root = tmp_path / "repo"
    _write_fake_repo(repo_root)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CONTRIB_ROOT", repo_root / "evaluators" / "contrib")

    # When: verifying the contrib package wiring
    packages = module.discover_contrib_packages()
    errors = module.verify_contrib_packages(packages)

    # Then: the wiring is accepted without errors
    assert errors == []
