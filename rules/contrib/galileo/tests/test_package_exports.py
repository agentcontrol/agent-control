"""Coverage for package-level exports and local-source metadata fallbacks."""

from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path


def test_package_version_falls_back_when_distribution_metadata_is_absent(
    monkeypatch,
) -> None:
    """Local source-tree imports should work before the package is installed."""

    def _raise_not_found(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError("agent-control-rule-galileo")

    monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)

    init_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_control_rule_galileo"
        / "__init__.py"
    )
    monkeypatch.syspath_prepend(str(init_path.parents[1]))
    spec = importlib.util.spec_from_file_location(
        "_agent_control_rule_galileo_version_probe",
        init_path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.__version__ == "0.0.0.dev"
