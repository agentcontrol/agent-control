"""Base models and utilities for Agent Control."""

from typing import Any

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict


class BaseModel(PydanticBaseModel):
    """
    Base model for all Agent Control models.

    Provides common configuration and utilities for JSON serialization
    and Pydantic compatibility.
    """

    model_config = ConfigDict(
        # Allow both snake_case and camelCase in JSON
        populate_by_name=True,
        # Use enum values in JSON output
        use_enum_values=True,
        # Validate on assignment
        validate_assignment=True,
        # Allow extra fields to be ignored (forward compatibility)
        extra="ignore",
    )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert model to dictionary.

        Returns:
            Dictionary representation of the model
        """
        return self.model_dump(mode="python", exclude_none=True)

    def to_json(self) -> str:
        """
        Convert model to JSON string.

        Returns:
            JSON string representation of the model
        """
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BaseModel":
        """
        Create model instance from dictionary.

        Args:
            data: Dictionary containing model data

        Returns:
            New model instance
        """
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "BaseModel":
        """
        Create model instance from JSON string.

        Args:
            json_str: JSON string containing model data

        Returns:
            New model instance
        """
        return cls.model_validate_json(json_str)

