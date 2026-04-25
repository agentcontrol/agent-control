from typing import Any

from .base import BaseModel


class Control(BaseModel):
    """A control with identity and configuration.

    ``control`` contains the canonical payload after server-side validation.
    Forward-compatible stored fields are preserved so clients can round-trip
    historical snapshots without data loss.
    """

    id: int
    name: str
    control: dict[str, Any]


class Policy(BaseModel):
    """A policy with its associated controls.

    Policies define a collection of controls that can be assigned to agents.
    Controls are directly associated with policies (no intermediate layer).
    """

    id: int
    name: str
    controls: list[Control]
