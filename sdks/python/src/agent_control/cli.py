"""CLI for Agent Control SDK.

Usage:
    agent-control install-skill          # Detect tools & install SKILL.md
    agent-control install-skill --project # Install to current project
    agent-control --version              # Show version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOL_CONFIGS: dict[str, dict[str, str]] = {
    "claude-code": {
        "display_name": "Claude Code",
        "detect_dir": ".claude",
        "global_skill_path": ".claude/skills/agent-control/SKILL.md",
        "project_skill_path": ".claude/skills/agent-control/SKILL.md",
    },
    "codex": {
        "display_name": "Codex",
        "detect_dir": ".agents",
        "global_skill_path": ".agents/skills/agent-control/SKILL.md",
        "project_skill_path": ".agents/skills/agent-control/SKILL.md",
    },
    "gemini-cli": {
        "display_name": "Gemini CLI",
        "detect_dir": ".gemini",
        "global_skill_path": ".gemini/skills/agent-control/SKILL.md",
        "project_skill_path": ".gemini/skills/agent-control/SKILL.md",
    },
    "cursor": {
        "display_name": "Cursor",
        "detect_dir": ".cursor",
        "global_skill_path": ".cursor/skills/agent-control/SKILL.md",
        "project_skill_path": ".cursor/skills/agent-control/SKILL.md",
    },
    "github-copilot": {
        "display_name": "GitHub Copilot",
        "detect_dir": ".config/github-copilot",
        "global_skill_path": ".github/skills/agent-control/SKILL.md",
        "project_skill_path": ".github/skills/agent-control/SKILL.md",
    },
}

TOOL_NAMES = ", ".join(TOOL_CONFIGS)


def _get_skill_content() -> str:
    """Load SKILL.md content from package data."""
    from importlib.resources import files

    return files("agent_control").joinpath("data", "SKILL.md").read_text(encoding="utf-8")


def _detect_tools(home: Path) -> list[str]:
    """Detect which AI coding tools are installed by checking config directories."""
    detected = []
    for tool_id, config in TOOL_CONFIGS.items():
        if (home / config["detect_dir"]).is_dir():
            detected.append(tool_id)
    return detected


def _confirm(prompt: str) -> bool:
    """Ask user for yes/no confirmation."""
    while True:
        response = input(f"{prompt} [Y/n] ").strip().lower()
        if response in ("", "y", "yes"):
            return True
        if response in ("n", "no"):
            return False


def _install_skill(target_path: Path, content: str, *, force: bool = False) -> bool:
    """Write SKILL.md to target path. Returns True if written, False if skipped."""
    if target_path.exists() and not force:
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return True


def cmd_install_skill(args: argparse.Namespace) -> int:
    """Handle the install-skill subcommand."""
    home = Path.home()
    is_project = args.project

    if is_project:
        base = Path.cwd()
        mode = "project"
    else:
        base = home
        mode = "global"

    # Resolve which tools to install for
    if args.tools:
        selected = []
        for t in args.tools:
            if t not in TOOL_CONFIGS:
                print(f"Error: Unknown tool '{t}'. Available: {TOOL_NAMES}")
                return 1
            selected.append(t)
    else:
        selected = _detect_tools(home)
        if not selected:
            print("No AI coding tools detected.")
            print(f"Looked for: {', '.join(c['display_name'] for c in TOOL_CONFIGS.values())}")
            print(f"\nSpecify tools explicitly with --tools, e.g.:")
            print(f"  agent-control install-skill --tools claude-code cursor")
            return 1

        print("Detected AI coding tools:")
        for tool_id in selected:
            print(f"  - {TOOL_CONFIGS[tool_id]['display_name']}")

        if not args.yes and not _confirm(f"\nInstall Agent Control skill for these tools ({mode})?"):
            print("Cancelled.")
            return 0

    content = _get_skill_content()
    installed = 0

    for tool_id in selected:
        config = TOOL_CONFIGS[tool_id]
        path_key = "project_skill_path" if is_project else "global_skill_path"
        target = base / config[path_key]

        if _install_skill(target, content, force=args.force):
            print(f"  {config['display_name']}: {target}")
            installed += 1
        else:
            print(f"  {config['display_name']}: already exists (use --force to overwrite)")

    print(f"\nInstalled for {installed} tool(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agent-control",
        description="Agent Control SDK CLI",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser(
        "install-skill",
        help="Install SKILL.md for AI coding tools",
    )
    install_parser.add_argument(
        "--project",
        action="store_true",
        help="Install to current project directory instead of ~/",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing SKILL.md files",
    )
    install_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    install_parser.add_argument(
        "--tools",
        nargs="+",
        metavar="TOOL",
        help=f"Specify tools explicitly ({TOOL_NAMES})",
    )

    args = parser.parse_args(argv)

    if args.version:
        from importlib.metadata import PackageNotFoundError, version

        try:
            print(f"agent-control-sdk {version('agent-control-sdk')}")
        except PackageNotFoundError:
            print("agent-control-sdk (dev)")
        return 0

    if args.command == "install-skill":
        return cmd_install_skill(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
