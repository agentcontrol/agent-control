"""Packaging regression tests for the published SDK wheel."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SDK_DIR = ROOT / "sdks" / "python"
SDK_SRC = SDK_DIR / "src"
DIST_DIR = SDK_DIR / "dist"


def test_sdk_wheel_bundles_engine_and_evaluators() -> None:
    """The SDK wheel should vendor engine and evaluator source packages."""
    subprocess.run(["make", "build-sdk"], cwd=ROOT, check=True)

    wheels = sorted(DIST_DIR.glob("agent_control_sdk-*.whl"))
    assert wheels, "Expected make build-sdk to produce a wheel"

    wheel_path = max(wheels, key=lambda path: path.stat().st_mtime)
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

        assert "agent_control_engine/__init__.py" in names
        assert "agent_control_evaluators/__init__.py" in names

        engine_init = wheel.read("agent_control_engine/__init__.py").decode()
        evaluators_init = wheel.read("agent_control_evaluators/__init__.py").decode()
        assert '__bundled_by__ = "agent-control-sdk"' in engine_init
        assert '__bundled_by__ = "agent-control-sdk"' in evaluators_init

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode()
        assert "Requires-Dist: agent-control-evaluators" not in metadata

    assert not (SDK_SRC / "agent_control_engine").exists()
    assert not (SDK_SRC / "agent_control_evaluators").exists()
