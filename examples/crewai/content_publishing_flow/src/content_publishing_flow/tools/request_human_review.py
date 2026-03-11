import json
import time

from agent_control import control


async def _request_human_review(content: str, content_type: str) -> str:
    """Submit content for human review. STEER control pauses for approval."""
    return json.dumps({
        "status": "pending_review",
        "content_type": content_type,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


_request_human_review.name = "request_human_review"    # type: ignore[attr-defined]
_request_human_review.tool_name = "request_human_review"  # type: ignore[attr-defined]
controlled_human_review = control()(_request_human_review)
