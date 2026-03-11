from agent_control import control


async def _research_topic(topic: str, audience: str) -> str:
    """Research a topic. Returns simulated research notes."""
    # Simulated output - the LIST control checks for banned sources in output.
    return (
        f"Research findings on '{topic}' for {audience}:\n\n"
        f"1. Industry reports from McKinsey and Gartner highlight growing adoption.\n"
        f"2. Academic papers from MIT and Stanford confirm key trends.\n"
        f"3. Government statistics (census.gov, bls.gov) provide baseline data.\n"
        f"4. Recent surveys show 73% of professionals consider this a priority.\n\n"
        f"Key insight: The intersection of {topic} and modern workflows is driving "
        f"measurable ROI for early adopters."
    )


_research_topic.name = "research_topic"                # type: ignore[attr-defined]
_research_topic.tool_name = "research_topic"            # type: ignore[attr-defined]
controlled_research = control()(_research_topic)
