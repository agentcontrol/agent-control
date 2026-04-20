"""Pydantic models for target management APIs.

Targets are typed, tenant-scoped, attachable objects. ``target_type`` is an
opaque string supplied by the caller (e.g. ``environment``); the server
treats it as data. The field is named ``target_type`` rather than ``type``
to avoid shadowing Python's builtin and keep greps for the field specific.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import BaseModel


class CreateTargetRequest(BaseModel):
    """Request body for creating a new target."""

    target_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Opaque target kind (e.g. 'environment').",
    )
    external_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Stable caller-supplied identifier for the target.",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display name for the target.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional target metadata payload.",
    )


class CreateTargetResponse(BaseModel):
    """Response returned after creating a target."""

    target_id: int = Field(..., description="Identifier of the created target row.")


class TargetSummary(BaseModel):
    """Full target record returned from get/list endpoints."""

    id: int = Field(..., description="Internal target ID.")
    tenant_id: str = Field(..., description="Owning tenant.")
    target_type: str = Field(..., description="Opaque target kind.")
    external_id: str = Field(..., description="Caller-supplied stable identifier.")
    name: str | None = Field(default=None, description="Optional display name.")
    data: dict[str, Any] = Field(default_factory=dict, description="Target metadata payload.")
    created_at: str = Field(..., description="ISO 8601 timestamp when the target was created.")


class ListTargetsResponse(BaseModel):
    """Response for listing targets."""

    targets: list[TargetSummary] = Field(..., description="Targets visible to the current tenant.")


class AttachTargetControlRequest(BaseModel):
    """Optional body for attaching a control to a target."""

    enabled: bool = Field(
        default=True,
        description="Whether the attachment starts enabled. Defaults to true.",
    )


class ToggleTargetControlRequest(BaseModel):
    """Body for toggling an existing target-control attachment's enabled flag."""

    enabled: bool = Field(..., description="New enabled state for the attachment.")


class TargetControlSummary(BaseModel):
    """A single control attached to a target."""

    id: int = Field(..., description="target_controls row identifier.")
    control_id: int = Field(..., description="Attached control ID.")
    enabled: bool = Field(..., description="Whether the attachment is enabled.")


class ListTargetControlsResponse(BaseModel):
    """Response for listing controls attached to a target."""

    target_id: int = Field(..., description="Target whose controls are returned.")
    controls: list[TargetControlSummary] = Field(
        default_factory=list,
        description="Controls attached to the target.",
    )
