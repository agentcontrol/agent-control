from agent_control import control


async def _edit_content(content: str, include_executive_summary: bool = False) -> str:
    """Edit content for quality. REGEX blocks PII; STEER requires exec summary."""
    if include_executive_summary:
        summary_section = (
            "## Executive Summary\n\n"
            "This press release announces key developments that position the company "
            "for significant growth. Stakeholders should note the strategic partnerships "
            "and projected impact outlined below.\n\n"
        )
        # Insert after the first line (FOR IMMEDIATE RELEASE)
        lines = content.split("\n", 2)
        if len(lines) >= 3:
            return lines[0] + "\n" + summary_section + lines[2]
        return summary_section + content
    return content


_edit_content.name = "edit_content"                    # type: ignore[attr-defined]
_edit_content.tool_name = "edit_content"                # type: ignore[attr-defined]
controlled_edit_content = control()(_edit_content)
