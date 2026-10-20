"""Contracts for ownership-aware project control cleanup."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CleanupProjectControlsRequest(BaseModel):
    """Existing stream targets whose bindings belong to the deleted project."""

    model_config = ConfigDict(extra="forbid")

    target_ids: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(
        default_factory=list, max_length=1000
    )


class CleanupProjectControlsResponse(BaseModel):
    """Committed cleanup result; repeating cleanup may return zero counts."""

    owner_project_id: str
    state: Literal["deleted"] = "deleted"
    controls_deleted: int = Field(ge=0)
    bindings_deleted: int = Field(ge=0)
