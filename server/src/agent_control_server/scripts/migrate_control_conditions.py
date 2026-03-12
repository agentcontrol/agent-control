"""Rewrite stored control payloads into canonical condition-tree form."""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from agent_control_server.config import db_config
from agent_control_server.models import Control
from agent_control_server.services.control_migration import (
    ControlMigrationResult,
    migrate_control_payload,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate stored controls from legacy selector/evaluator fields "
            "to canonical condition trees."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze stored controls without writing changes (default).",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration after a clean analysis run.",
    )
    return parser.parse_args()


def _print_summary(
    *,
    total: int,
    unchanged: int,
    migrated: list[tuple[Control, ControlMigrationResult]],
    invalid: list[tuple[Control, ControlMigrationResult]],
    apply: bool,
) -> None:
    mode = "apply" if apply else "dry-run"
    print(f"Control condition migration summary ({mode})")
    print(f"Total controls: {total}")
    print(f"Already canonical: {unchanged}")
    print(f"Ready to migrate: {len(migrated)}")
    print(f"Invalid/corrupted: {len(invalid)}")

    if invalid:
        print("")
        print("Invalid controls:")
        for control, result in invalid:
            reason = result.reason or "Unknown validation error."
            print(f"- id={control.id} name={control.name}: {reason}")


def main() -> int:
    args = _parse_args()
    apply = bool(args.apply)

    engine = create_engine(db_config.get_url(), future=True)

    try:
        with Session(engine) as session:
            controls = list(session.execute(select(Control).order_by(Control.id)).scalars().all())
            migrated: list[tuple[Control, ControlMigrationResult]] = []
            invalid: list[tuple[Control, ControlMigrationResult]] = []
            unchanged = 0

            for control in controls:
                result = migrate_control_payload(control.data)
                if result.status == "unchanged":
                    unchanged += 1
                elif result.status == "migrated":
                    migrated.append((control, result))
                else:
                    invalid.append((control, result))

            _print_summary(
                total=len(controls),
                unchanged=unchanged,
                migrated=migrated,
                invalid=invalid,
                apply=apply,
            )

            if invalid:
                if apply:
                    print("")
                    print("Aborting apply because invalid controls must be fixed first.")
                return 1

            if not apply:
                return 0

            for control, result in migrated:
                assert result.payload is not None
                control.data = result.payload

            session.commit()
            print("")
            print(f"Applied migration to {len(migrated)} controls.")
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
