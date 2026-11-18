"""Validate the target pair forwarded to management authorization."""

from collections.abc import Mapping

_MAX_TARGET_FIELD_LENGTH = 255


def complete_target_context(
    context: Mapping[str, object] | None,
    *,
    max_length: int | None = _MAX_TARGET_FIELD_LENGTH,
) -> dict[str, str] | None:
    """Return a usable target pair without changing the caller's values.

    Body-bearing binding models limit fields to 255 characters. The GET list
    endpoint has no such limit, so its caller passes ``max_length=None``.
    """
    if context is None:
        return None
    target_type = context.get("target_type")
    target_id = context.get("target_id")
    if not isinstance(target_type, str) or not isinstance(target_id, str):
        return None
    if not target_type.strip() or not target_id.strip():
        return None
    if max_length is not None and (
        len(target_type) > max_length or len(target_id) > max_length
    ):
        return None
    return {"target_type": target_type, "target_id": target_id}
