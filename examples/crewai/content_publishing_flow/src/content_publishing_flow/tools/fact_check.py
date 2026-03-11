from agent_control import control


async def _fact_check(research_text: str) -> str:
    """Fact-check research output. Returns simulated verification report."""
    # The REGEX control checks output for unverified-claim markers.
    return (
        "Fact-Check Report:\n"
        "- Claim 1 (industry reports): VERIFIED - matches published data.\n"
        "- Claim 2 (academic papers): VERIFIED - citations confirmed.\n"
        "- Claim 3 (government stats): VERIFIED - data matches official sources.\n"
        "- Claim 4 (survey data): VERIFIED - survey methodology reviewed.\n\n"
        "Overall assessment: All claims verified. No corrections needed."
    )


_fact_check.name = "fact_check"                        # type: ignore[attr-defined]
_fact_check.tool_name = "fact_check"                    # type: ignore[attr-defined]
controlled_fact_check = control()(_fact_check)
