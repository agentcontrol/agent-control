import json

from agent_control import control


async def _legal_review(content: str) -> str:
    """Legal review of content. Returns JSON with disclaimer and approval."""
    # The JSON control checks output for required fields: disclaimer, legal_reviewed.
    return json.dumps({
        "disclaimer": (
            "This content has been reviewed for legal compliance. "
            "Forward-looking statements are subject to change."
        ),
        "legal_reviewed": True,
        "notes": "No legal issues found. Approved for publication.",
        "reviewed_content": content,
    })


_legal_review.name = "legal_review"                    # type: ignore[attr-defined]
_legal_review.tool_name = "legal_review"                # type: ignore[attr-defined]
controlled_legal_review = control()(_legal_review)
