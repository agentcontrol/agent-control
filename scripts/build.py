#!/usr/bin/env python3
"""Build packages for PyPI distribution.

This script builds all publishable packages. For SDK and server, it copies internal
packages into the source directories before building, then cleans up afterward. This
allows the published wheels to be self-contained.

Usage:
    python scripts/build.py [models|evaluators|sdk|server|galileo|all]
"""

import shutil
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def get_global_version() -> str:
    """Read version from root pyproject.toml."""
    content = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in root pyproject.toml")
    return match.group(1)


def set_package_version(pyproject_path: Path, version: str) -> None:
    """Update version in a pyproject.toml file."""
    content = pyproject_path.read_text()
    updated = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{version}"',
        content,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(updated)


def inject_bundle_metadata(init_file: Path, package_name: str, version: str) -> None:
    """Add bundling metadata to __init__.py for conflict detection."""
    content = init_file.read_text()

    # Only add if not already present
    if "__bundled_by__" in content:
        return

    metadata = f'''__bundled_by__ = "{package_name}"
__bundled_version__ = "{version}"

'''
    init_file.write_text(metadata + content)


def build_models() -> None:
    """Build agent-control-models (standalone, no vendoring needed)."""
    version = get_global_version()
    models_dir = ROOT / "models"

    print(f"Building agent-control-models v{version}")

    # Clean previous builds
    dist_dir = models_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Set version
    set_package_version(models_dir / "pyproject.toml", version)

    subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=models_dir, check=True)
    print(f"  Built agent-control-models v{version}")


def build_sdk() -> None:
    """Build agent-control-sdk with vendored packages."""
    version = get_global_version()
    sdk_dir = ROOT / "sdks" / "python"
    sdk_src = sdk_dir / "src"

    print(f"Building agent-control-sdk v{version}")

    # Clean previous builds and vendored code
    for pkg in ["agent_control_models", "agent_control_engine", "agent_control_evaluators"]:
        target = sdk_src / pkg
        if target.exists():
            shutil.rmtree(target)

    dist_dir = sdk_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Copy vendored packages
    shutil.copytree(
        ROOT / "models" / "src" / "agent_control_models",
        sdk_src / "agent_control_models",
    )
    shutil.copytree(
        ROOT / "engine" / "src" / "agent_control_engine",
        sdk_src / "agent_control_engine",
    )
    shutil.copytree(
        ROOT / "evaluators" / "builtin" / "src" / "agent_control_evaluators",
        sdk_src / "agent_control_evaluators",
    )

    # Inject bundle metadata for conflict detection
    inject_bundle_metadata(
        sdk_src / "agent_control_models" / "__init__.py",
        "agent-control-sdk",
        version,
    )
    inject_bundle_metadata(
        sdk_src / "agent_control_engine" / "__init__.py",
        "agent-control-sdk",
        version,
    )
    inject_bundle_metadata(
        sdk_src / "agent_control_evaluators" / "__init__.py",
        "agent-control-sdk",
        version,
    )

    # Set version
    set_package_version(sdk_dir / "pyproject.toml", version)

    try:
        subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=sdk_dir, check=True)
        print(f"  Built agent-control-sdk v{version}")
    finally:
        # Clean up vendored code (don't commit it)
        for pkg in ["agent_control_models", "agent_control_engine", "agent_control_evaluators"]:
            target = sdk_src / pkg
            if target.exists():
                shutil.rmtree(target)


def build_server() -> None:
    """Build agent-control-server with vendored packages.

    Note: evaluators are NOT vendored - server uses agent-control-evaluators as a
    runtime dependency to avoid duplicate module conflicts with galileo extras.
    """
    version = get_global_version()
    server_dir = ROOT / "server"
    server_src = server_dir / "src"

    print(f"Building agent-control-server v{version}")

    # Clean previous builds and vendored code
    for pkg in ["agent_control_models", "agent_control_engine"]:
        target = server_src / pkg
        if target.exists():
            shutil.rmtree(target)

    dist_dir = server_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Copy vendored packages (models and engine only, NOT evaluators)
    shutil.copytree(
        ROOT / "models" / "src" / "agent_control_models",
        server_src / "agent_control_models",
    )
    shutil.copytree(
        ROOT / "engine" / "src" / "agent_control_engine",
        server_src / "agent_control_engine",
    )

    # Inject bundle metadata for conflict detection
    inject_bundle_metadata(
        server_src / "agent_control_models" / "__init__.py",
        "agent-control-server",
        version,
    )
    inject_bundle_metadata(
        server_src / "agent_control_engine" / "__init__.py",
        "agent-control-server",
        version,
    )

    # Set version
    set_package_version(server_dir / "pyproject.toml", version)

    try:
        subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=server_dir, check=True)
        print(f"  Built agent-control-server v{version}")
    finally:
        # Clean up vendored code (don't commit it)
        for pkg in ["agent_control_models", "agent_control_engine"]:
            target = server_src / pkg
            if target.exists():
                shutil.rmtree(target)


def build_evaluators() -> None:
    """Build agent-control-evaluators (standalone, no vendoring needed)."""
    version = get_global_version()
    evaluators_dir = ROOT / "evaluators" / "builtin"

    print(f"Building agent-control-evaluators v{version}")

    # Clean previous builds
    dist_dir = evaluators_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Set version
    set_package_version(evaluators_dir / "pyproject.toml", version)

    subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=evaluators_dir, check=True)
    print(f"  Built agent-control-evaluators v{version}")


def build_evaluator_galileo() -> None:
    """Build agent-control-evaluator-galileo (standalone, no vendoring needed)."""
    version = get_global_version()
    galileo_dir = ROOT / "evaluators" / "contrib" / "galileo"

    print(f"Building agent-control-evaluator-galileo v{version}")

    # Clean previous builds
    dist_dir = galileo_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Set version
    set_package_version(galileo_dir / "pyproject.toml", version)

    subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=galileo_dir, check=True)
    print(f"  Built agent-control-evaluator-galileo v{version}")


def build_all() -> None:
    """Build all packages."""
    print(f"Building all packages (version {get_global_version()})\n")
    build_models()
    build_evaluators()
    build_sdk()
    build_server()
    build_evaluator_galileo()
    print("\nAll packages built successfully!")


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "models":
        build_models()
    elif target == "evaluators":
        build_evaluators()
    elif target == "sdk":
        build_sdk()
    elif target == "server":
        build_server()
    elif target == "galileo":
        build_evaluator_galileo()
    elif target == "all":
        build_all()
    else:
        print("Usage: python scripts/build.py [models|evaluators|sdk|server|galileo|all]")
        sys.exit(1)
