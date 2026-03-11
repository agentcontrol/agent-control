"""Writer tool: write_report -- generates reports with Agent Control PII protection and citation check."""

import asyncio
import json

from agent_control import ControlSteerError, ControlViolationError, control
from crewai.tools import tool

# ---------------------------------------------------------------------------
# Async inner function + @control() decorator
# ---------------------------------------------------------------------------

async def _write_report(content: str, sources: str = "") -> str:
    """Generate a formatted report. Protected by Agent Control.

    The @control decorator sends the output to the server for PII checking.
    """
    # Build the report body
    report = f"""Research Report
{'=' * 40}

{content}
"""
    if sources:
        report += f"""
Sources:
{sources}
"""
    return report


_write_report.name = "write_report"               # type: ignore[attr-defined]
_write_report.tool_name = "write_report"           # type: ignore[attr-defined]

_controlled_write_report = control()(_write_report)


# ---------------------------------------------------------------------------
# CrewAI @tool wrapper
# ---------------------------------------------------------------------------

@tool("write_report")
def write_report(content: str) -> str:
    """Generate the final research report. The content should NOT contain
    PII (social security numbers, email addresses, phone numbers).
    Include a 'Sources:' section at the end for citations.

    Args:
        content: The report body text, including a Sources section.
    """
    # Split content and sources if the LLM included them together
    sources = ""
    for marker in ["Sources:", "References:", "Citations:"]:
        if marker in content:
            parts = content.split(marker, 1)
            content = parts[0].strip()
            sources = parts[1].strip()
            break

    print(f"\n  [Writer] Generating report ({len(content)} chars)...")

    max_attempts = 3
    current_content = content
    current_sources = sources

    for attempt in range(1, max_attempts + 1):
        try:
            result = asyncio.run(
                _controlled_write_report(content=current_content, sources=current_sources)
            )

            # Client-side citation check: steer if no sources section
            if not current_sources:
                print(f"  [Writer] STEERED (attempt {attempt}): Report lacks source citations.")
                current_sources = "Internal database queries (employees, projects, quarterly_metrics tables)"
                print("  [Writer] Added default citation sources.")
                # Re-run with sources added
                result = asyncio.run(
                    _controlled_write_report(content=current_content, sources=current_sources)
                )

            print(f"  [Writer] Report generated successfully (attempt {attempt}).")
            return result

        except ControlViolationError as e:
            msg = f"BLOCKED by content-safety-policy: {e.message}"
            print(f"  [Writer] {msg}")
            return msg

        except ControlSteerError as e:
            print(f"  [Writer] STEERED (attempt {attempt}): {e.message}")
            try:
                guidance = json.loads(e.steering_context)
            except (json.JSONDecodeError, TypeError):
                guidance = {"reason": e.steering_context}
            print(f"  [Writer] Steering reason: {guidance.get('reason', e.steering_context)}")
            continue

    return "ERROR: Failed to generate report after max attempts."
