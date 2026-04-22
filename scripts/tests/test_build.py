import sys
import tomllib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build


def test_sync_dependency_floors_updates_internal_minimums(tmp_path: Path) -> None:
    # Given: a package manifest with mixed internal and external dependency constraints
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[project]
dependencies = [
    "agent-control-evaluators>=7.5.0",
    "agent-control-models>=7.5.0,<8.0.0",
    "httpx>=0.28.0",
]

[project.optional-dependencies]
galileo = ["agent-control-evaluator-galileo>=7.5.0"]
""".strip()
    )

    # When: syncing internal dependency floors for a new release
    build.sync_dependency_floors(
        pyproject_path,
        [
            "agent-control-evaluators",
            "agent-control-models",
            "agent-control-evaluator-galileo",
        ],
        "7.6.0",
    )

    # Then: only the internal minimum versions move to the release version
    assert pyproject_path.read_text() == (
        """
[project]
dependencies = [
    "agent-control-evaluators>=7.6.0",
    "agent-control-models>=7.6.0,<8.0.0",
    "httpx>=0.28.0",
]

[project.optional-dependencies]
galileo = ["agent-control-evaluator-galileo>=7.6.0"]
""".strip()
    )


def test_sync_dependency_floors_tolerates_whitespace_around_lower_bounds(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[project]
dependencies = [
    "agent-control-evaluators >= 7.5.0",
    "agent-control-models >= 7.5.0,<8.0.0",
]

[project.optional-dependencies]
galileo = ["agent-control-evaluator-galileo >= 7.5.0"]
""".strip()
    )

    build.sync_dependency_floors(
        pyproject_path,
        [
            "agent-control-evaluators",
            "agent-control-models",
            "agent-control-evaluator-galileo",
        ],
        "7.6.0",
    )

    assert pyproject_path.read_text() == (
        """
[project]
dependencies = [
    "agent-control-evaluators >= 7.6.0",
    "agent-control-models >= 7.6.0,<8.0.0",
]

[project.optional-dependencies]
galileo = ["agent-control-evaluator-galileo >= 7.6.0"]
""".strip()
    )


def test_builtin_evaluators_manifest_keeps_models_floor_rewritable() -> None:
    builtin_pyproject = SCRIPTS_DIR.parent / "evaluators" / "builtin" / "pyproject.toml"
    with builtin_pyproject.open("rb") as handle:
        manifest = tomllib.load(handle)

    dependencies = manifest["project"]["dependencies"]

    assert "agent-control-models>=7.5.0" in dependencies
