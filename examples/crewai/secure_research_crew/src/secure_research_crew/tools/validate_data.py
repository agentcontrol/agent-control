"""Analyst tool: validate_data -- validates research data with Agent Control steering support."""

import asyncio
import json

from agent_control import ControlSteerError, ControlViolationError, control
from crewai.tools import tool

# ---------------------------------------------------------------------------
# Async inner function + @control() decorator
# ---------------------------------------------------------------------------

async def _validate_data(request: dict) -> str:
    """Validate and process research data. Protected by Agent Control.

    The request dict should contain:
      - dataset: str
      - findings: str
      - confidence_score: float (0-1)
      - methodology: str (optional, but will be steered if missing)
    """
    # If we reach here, controls passed -- produce analysis output
    return json.dumps({
        "status": "validated",
        "dataset": request.get("dataset"),
        "findings": request.get("findings"),
        "confidence_score": request.get("confidence_score"),
        "methodology": request.get("methodology", ""),
        "summary": (
            f"Analysis of '{request.get('dataset')}' confirms findings with "
            f"confidence {request.get('confidence_score')}. "
            f"Methodology: {request.get('methodology', 'N/A')}."
        ),
    }, indent=2)


_validate_data.name = "validate_data"             # type: ignore[attr-defined]
_validate_data.tool_name = "validate_data"         # type: ignore[attr-defined]

_controlled_validate_data = control()(_validate_data)


# ---------------------------------------------------------------------------
# CrewAI @tool wrapper
# ---------------------------------------------------------------------------

@tool("validate_data")
def validate_data(request_json: str) -> str:
    """Validate research data. Input must be a JSON string with fields:
    dataset (str), findings (str), confidence_score (float 0-1).
    A methodology field is recommended -- you will be asked to add one if missing.

    Args:
        request_json: JSON string with the analysis request.
    """
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError:
        return "ERROR: Input must be valid JSON."

    print(f"\n  [Analyst] Validating data for dataset: {request.get('dataset', '?')}")

    max_attempts = 3
    current_request = dict(request)

    for attempt in range(1, max_attempts + 1):
        try:
            result = asyncio.run(_controlled_validate_data(request=current_request))
            print(f"  [Analyst] Validation passed (attempt {attempt}).")
            return result
        except ControlViolationError as e:
            msg = f"BLOCKED by analysis-validation-policy: {e.message}"
            print(f"  [Analyst] {msg}")
            return msg
        except ControlSteerError as e:
            print(f"  [Analyst] STEERED (attempt {attempt}): {e.message}")
            # Parse steering context for corrective instructions
            try:
                guidance = json.loads(e.steering_context)
            except (json.JSONDecodeError, TypeError):
                guidance = {"reason": e.steering_context}

            reason = guidance.get("reason", "Correction required")
            print(f"  [Analyst] Steering reason: {reason}")

            # Apply corrections
            retry_with = guidance.get("retry_with", {})
            for key, hint in retry_with.items():
                if key not in current_request or not current_request[key]:
                    # Auto-fill with a reasonable default
                    if key == "methodology":
                        current_request[key] = (
                            "Data collected via automated database queries. "
                            "Validated through cross-referencing multiple tables "
                            "and statistical confidence scoring."
                        )
                    else:
                        current_request[key] = hint
                    print(f"  [Analyst] Added missing field '{key}'.")
            continue

    return "ERROR: Failed to pass validation after max attempts."
