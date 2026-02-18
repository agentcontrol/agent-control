from typing import Literal

from agent_control_evaluators import EvaluatorConfig


class LLMRelevanceConfig(EvaluatorConfig):
    """Config for LLM-as-judge relevance scoring.

    - model: LLM model name
    - threshold: minimum score (0-1) required to pass
    - api_key_env: env var that holds the API key
    - base_url: OpenAI-compatible base URL (e.g., https://api.openai.com/v1)
    - on_error: allow (fail open) or deny (fail closed)
    """

    model: str = "gpt-4o-mini"
    threshold: float = 0.7
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    on_error: Literal["allow", "deny"] = "allow"
