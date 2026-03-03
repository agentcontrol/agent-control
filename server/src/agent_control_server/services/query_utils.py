def escape_like_pattern(value: str) -> str:
    """Escape special SQL LIKE pattern characters in user-provided input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
