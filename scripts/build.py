#!/usr/bin/env python3
"""Build packages for PyPI distribution.

This script builds all publishable packages. For SDK and server, it copies internal
packages (models, engine, telemetry) into the source directories before building,
then cleans up afterward. This allows the published wheels to be self-contained.

Usage:
    python scripts/build.py [models|evaluators|sdk|server|contrib|all|<contrib-name>]
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from contrib_packages import ContribPackage, discover_contrib_packages

ROOT = Path(__file__).resolve().parent.parent


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


def sync_dependency_floors(pyproject_path: Path, dependency_names: list[str], version: str) -> None:
    """Update internal dependency lower bounds to the release version."""
    content = pyproject_path.read_text()
    updated = content
    for dependency_name in dependency_names:
        updated = re.sub(
            rf'("{re.escape(dependency_name)}\s*>=\s*)([^",;\]\s]+)',
            rf"\g<1>{version}",
            updated,
        )

    if updated != content:
        pyproject_path.write_text(updated)


def inject_bundle_metadata(init_file: Path, package_name: str, version: str) -> None:
    """Add bundling metadata to __init__.py for conflict detection."""
    content = init_file.read_text()

    if "__bundled_by__" in content:
        return

    metadata = f'''__bundled_by__ = "{package_name}"
__bundled_version__ = "{version}"

'''
    init_file.write_text(metadata + content)


def clean_dist_dir(package_dir: Path) -> Path:
    """Remove any previous build output and return the dist directory path."""
    dist_dir = package_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    return dist_dir


def build_python_package(
    distribution_name: str,
    package_dir: Path,
    version: str,
    dependency_names: list[str] | None = None,
) -> None:
    """Build a standalone Python package into its local dist directory."""
    print(f"Building {distribution_name} v{version}")
    dist_dir = clean_dist_dir(package_dir)
    pyproject_path = package_dir / "pyproject.toml"
    set_package_version(pyproject_path, version)
    if dependency_names:
        sync_dependency_floors(pyproject_path, dependency_names, version)
    subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=package_dir, check=True)
    print(f"  Built {distribution_name} v{version}")


def discover_contrib_by_name() -> dict[str, ContribPackage]:
    """Return discovered contrib packages keyed by contrib name."""
    return {package.name: package for package in discover_contrib_packages()}


def discover_contrib_distribution_names() -> list[str]:
    """Return the distribution names for all discovered contrib packages."""
    return [package.package for package in discover_contrib_packages()]


def build_models() -> None:
    """Build agent-control-models (standalone, no vendoring needed)."""
    build_python_package("agent-control-models", ROOT / "models", get_global_version())


def build_sdk() -> None:
    """Build agent-control-sdk with vendored packages."""
    version = get_global_version()
    sdk_dir = ROOT / "sdks" / "python"
    sdk_src = sdk_dir / "src"

    print(f"Building agent-control-sdk v{version}")

    for pkg in ["agent_control_models", "agent_control_engine", "agent_control_telemetry"]:
        target = sdk_src / pkg
        if target.exists():
            shutil.rmtree(target)

    dist_dir = clean_dist_dir(sdk_dir)

    shutil.copytree(
        ROOT / "models" / "src" / "agent_control_models",
        sdk_src / "agent_control_models",
    )
    shutil.copytree(
        ROOT / "engine" / "src" / "agent_control_engine",
        sdk_src / "agent_control_engine",
    )
    shutil.copytree(
        ROOT / "telemetry" / "src" / "agent_control_telemetry",
        sdk_src / "agent_control_telemetry",
    )

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
        sdk_src / "agent_control_telemetry" / "__init__.py",
        "agent-control-sdk",
        version,
    )

    sdk_pyproject = sdk_dir / "pyproject.toml"
    set_package_version(sdk_pyproject, version)
    sync_dependency_floors(
        sdk_pyproject,
        ["agent-control-evaluators", *discover_contrib_distribution_names()],
        version,
    )

    try:
        subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=sdk_dir, check=True)
        print(f"  Built agent-control-sdk v{version}")
    finally:
        for pkg in ["agent_control_models", "agent_control_engine", "agent_control_telemetry"]:
            target = sdk_src / pkg
            if target.exists():
                shutil.rmtree(target)


def build_server() -> None:
    """Build agent-control-server with vendored packages.

    Note: evaluators are NOT vendored - server uses agent-control-evaluators as a
    runtime dependency to avoid duplicate module conflicts with contrib extras.
    """
    version = get_global_version()
    server_dir = ROOT / "server"
    server_src = server_dir / "src"

    print(f"Building agent-control-server v{version}")

    for pkg in ["agent_control_models", "agent_control_engine", "agent_control_telemetry"]:
        target = server_src / pkg
        if target.exists():
            shutil.rmtree(target)

    dist_dir = clean_dist_dir(server_dir)

    shutil.copytree(
        ROOT / "models" / "src" / "agent_control_models",
        server_src / "agent_control_models",
    )
    shutil.copytree(
        ROOT / "engine" / "src" / "agent_control_engine",
        server_src / "agent_control_engine",
    )
    shutil.copytree(
        ROOT / "telemetry" / "src" / "agent_control_telemetry",
        server_src / "agent_control_telemetry",
    )

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
    inject_bundle_metadata(
        server_src / "agent_control_telemetry" / "__init__.py",
        "agent-control-server",
        version,
    )

    server_pyproject = server_dir / "pyproject.toml"
    set_package_version(server_pyproject, version)
    sync_dependency_floors(
        server_pyproject,
        ["agent-control-evaluators", *discover_contrib_distribution_names()],
        version,
    )

    try:
        subprocess.run(["uv", "build", "-o", str(dist_dir)], cwd=server_dir, check=True)
        print(f"  Built agent-control-server v{version}")
    finally:
        for pkg in ["agent_control_models", "agent_control_engine", "agent_control_telemetry"]:
            target = server_src / pkg
            if target.exists():
                shutil.rmtree(target)


def build_evaluators() -> None:
    """Build agent-control-evaluators (standalone, no vendoring needed)."""
    build_python_package(
        "agent-control-evaluators",
        ROOT / "evaluators" / "builtin",
        get_global_version(),
        ["agent-control-models", *discover_contrib_distribution_names()],
    )


def build_contrib_package(package: ContribPackage, version: str) -> None:
    """Build a discovered contrib evaluator package."""
    build_python_package(
        package.package,
        ROOT / Path(package.directory),
        version,
        ["agent-control-evaluators", "agent-control-models"],
    )


def build_contrib() -> None:
    """Build all discovered contrib evaluator packages."""
    version = get_global_version()
    packages = discover_contrib_packages()
    if not packages:
        print("No contrib evaluator packages discovered.")
        return

    package_names = ", ".join(package.name for package in packages)
    print(f"Building discovered contrib packages ({package_names})")
    for package in packages:
        build_contrib_package(package, version)


def build_named_contrib_package(target: str) -> None:
    """Build one discovered contrib evaluator package by name."""
    packages = discover_contrib_by_name()
    package = packages.get(target)
    if package is None:
        available_targets = ", ".join(sorted(packages))
        raise ValueError(
            "Unknown build target "
            f"{target!r}. Available contrib targets: {available_targets or '(none)'}"
        )
    build_contrib_package(package, get_global_version())


def build_all() -> None:
    """Build all packages."""
    print(f"Building all packages (version {get_global_version()})\n")
    build_models()
    build_evaluators()
    build_contrib()
    build_sdk()
    build_server()
    print("\nAll packages built successfully!")


def usage() -> str:
    """Return the CLI usage string."""
    return (
        "Usage: python scripts/build.py "
        "[models|evaluators|sdk|server|contrib|all|<contrib-name>]"
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "models":
        build_models()
    elif target == "evaluators":
        build_evaluators()
    elif target == "sdk":
        build_sdk()
    elif target == "server":
        build_server()
    elif target == "contrib":
        build_contrib()
    elif target == "all":
        build_all()
    else:
        try:
            build_named_contrib_package(target)
        except ValueError as error:
            print(error)
            print(usage())
            sys.exit(1)
