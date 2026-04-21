"""Pydantic models for target management APIs.

Targets are typed, tenant-scoped, attachable objects. ``target_type`` is an
opaque string supplied by the caller (e.g. ``environment``); the server
treats it as data. The field is named ``target_type`` rather than ``type``
to avoid shadowing Python's builtin and keep greps for the field specific.

Path-safe identifier contracts: ``target_type`` and ``external_id`` may be
embedded in URL path segments for natural-key routes. To keep those routes
parse-safe, both values are restricted to charsets that do not require URL
encoding and do not collide with path-segment separators.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from .base import BaseModel

# ---------------------------------------------------------------------------
# Constrained string aliases
# ---------------------------------------------------------------------------

# target_type is a controlled slug. Lowercase letters plus digits and
# underscores, starting with a letter, up to 64 characters. Kept strict so
# operators cannot accidentally create target types that differ only in
# case or punctuation (``LogStream`` vs ``log_stream``) or that contain
# path-breaking characters.
TargetTypeStr = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]

# external_id is caller-supplied and may carry UUIDs, dotted segments, or
# short slugs. We permit the URL-safe "unreserved" charset from RFC 3986
# minus the tilde (rarely used, rejected to keep the surface small).
# Callers that need richer identifiers should hash or encode them before
# passing.
ExternalIdStr = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,255}$"),
]


class CreateTargetRequest(BaseModel):
    """Request body for creating a new target."""

    target_type: TargetTypeStr = Field(
        ...,
        description=(
            "Opaque target kind slug (e.g. 'environment'). "
            "Lowercase letters, digits, underscores; must start with a letter."
        ),
    )
    external_id: ExternalIdStr = Field(
        ...,
        description=(
            "Stable caller-supplied identifier. URL-safe: "
            "letters, digits, dot, underscore, hyphen."
        ),
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
    target_type: TargetTypeStr = Field(..., description="Opaque target kind slug.")
    external_id: ExternalIdStr = Field(..., description="Caller-supplied stable identifier.")
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


__all__ = [
    "TargetTypeStr",
    "ExternalIdStr",
    "CreateTargetRequest",
    "CreateTargetResponse",
    "TargetSummary",
    "ListTargetsResponse",
    "AttachTargetControlRequest",
    "ToggleTargetControlRequest",
    "TargetControlSummary",
    "ListTargetControlsResponse",
]
