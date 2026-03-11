import json

from agent_control import control


async def _validate_request(request: dict) -> str:
    """Validate that the content request has required fields."""
    # The JSON evaluator on the server checks for topic, audience, content_type.
    # If they are present the control passes; if missing it denies.
    topic = request.get("topic", "")
    audience = request.get("audience", "")
    content_type = request.get("content_type", "")
    return json.dumps({
        "topic": topic,
        "audience": audience,
        "content_type": content_type,
        "valid": bool(topic and audience and content_type),
    })


_validate_request.name = "validate_request"            # type: ignore[attr-defined]
_validate_request.tool_name = "validate_request"        # type: ignore[attr-defined]
controlled_validate_request = control()(_validate_request)
