from .base import BaseModel
from .controls import ControlDefinition


class Control(BaseModel):
    """A control with identity and configuration.

    Note: Only fully-configured controls (with valid ControlDefinition)
    are returned from API endpoints. Unconfigured controls are filtered out.
    """

    id: int
    name: str
    control: ControlDefinition
