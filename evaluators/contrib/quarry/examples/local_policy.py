"""Run an offline Quarry policy through Agent Control's cached evaluator factory."""

import asyncio

from agent_control_evaluators import get_evaluator_instance
from agent_control_models import EvaluatorSpec, Step

RULE = """rule "Read then send"
condition:
    has_sequence("read_secret", "send_http")
"""


async def main() -> None:
    guard = get_evaluator_instance(
        EvaluatorSpec(
            name="quarry.policy",
            config={
                "rule": RULE,
                # This session is an ordered conversation whose traces may be correlated.
                "session_mode": "continuous",
            },
        )
    )
    session = Step(
        type="session",
        name="demo",
        input=None,
        children=[
            Step(
                type="trace",
                name="read",
                input=None,
                children=[
                    Step(
                        type="tool", name="read_secret", input={"path": "demo.txt"}, output="demo"
                    ),
                ],
            ),
            Step(
                type="trace",
                name="send",
                input=None,
                children=[
                    Step(type="tool", name="send_http", input={"body": "demo"}, output="sent"),
                ],
            ),
        ],
    )
    result = await guard.evaluate(session)
    print(result.model_dump_json(indent=2))
    assert result.error is None
    assert result.matched is True


if __name__ == "__main__":
    asyncio.run(main())
