"""Data selection logic for rule evaluation."""
from typing import Any

from agent_control_models import Step


def select_data(step: Step, path: str) -> Any:
    """
    Select data from the step using a dot-notation path.

    Args:
        step: The Step payload
        path: Dot-notation path (e.g., 'input', 'input.query', 'context.user_id')

    Returns:
        The selected value, or None if the path doesn't exist.
    """
    if not path or path == "*":
        return step.model_dump(mode="json")

    parts = path.split(".")
    current: Any = step

    for part in parts:
        if current is None:
            return None

        # 1. Try dictionary access
        if isinstance(current, dict):
            try:
                current = current[part]
                continue
            except KeyError:
                return None

        # 2. Try attribute access (Pydantic models or objects)
        if hasattr(current, part):
            current = getattr(current, part)
            continue

        # 3. If neither worked, path is invalid for this object
        return None

    return current
