from .base import BaseModel
from .controls import ControlDefinition, UnrenderedTemplateControl


class Control(BaseModel):
    """A control with identity and configuration.

    For rendered controls (raw or template-backed), ``control`` is a
    ``ControlDefinition``.  For unrendered template controls, ``control``
    is an ``UnrenderedTemplateControl``.
    """

    id: int
    name: str
    control: ControlDefinition | UnrenderedTemplateControl


class Policy(BaseModel):
    """A policy with its associated controls.

    Policies define a collection of controls that can be assigned to agents.
    Controls are directly associated with policies (no intermediate layer).
    """

    id: int
    name: str
    controls: list[Control]
