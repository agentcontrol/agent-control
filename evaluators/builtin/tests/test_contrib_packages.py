"""Tests for repo contrib package discovery wiring."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "contrib_packages.py"
MODULE_NAME = "agent_control_repo_contrib_packages"


def load_contrib_packages_module() -> ModuleType:
    """Load the repo contrib-packages script as a module for testing."""

    module = sys.modules.get(MODULE_NAME)
    if module is not None:
        return module

    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def test_discover_contrib_packages_returns_expected_metadata() -> None:
    """Test that real contrib packages are discovered with stable metadata."""

    module = load_contrib_packages_module()

    packages = module.discover_contrib_packages()

    assert [(package.name, package.package, package.extra) for package in packages] == [
        ("budget", "agent-control-evaluator-budget", "budget"),
        ("cisco", "agent-control-evaluator-cisco", "cisco"),
        ("galileo", "agent-control-evaluator-galileo", "galileo"),
    ]


def test_verify_contrib_packages_has_no_repo_wiring_drift() -> None:
    """Test that contrib package wiring stays aligned with repo metadata."""

    module = load_contrib_packages_module()

    packages = module.discover_contrib_packages()

    assert module.verify_contrib_packages(packages) == []
