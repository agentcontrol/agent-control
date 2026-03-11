import json
import time

from agent_control import control


async def _publish_content(content: str, content_type: str) -> str:
    """Publish content. Final PII scan happens as a pre-check."""
    return json.dumps({
        "status": "published",
        "content_type": content_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content_preview": content[:200] + "..." if len(content) > 200 else content,
    })


_publish_content.name = "publish_content"              # type: ignore[attr-defined]
_publish_content.tool_name = "publish_content"          # type: ignore[attr-defined]
controlled_publish = control()(_publish_content)
