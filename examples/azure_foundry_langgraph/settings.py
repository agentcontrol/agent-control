import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_name: str = "customer-support-agent"
    agent_control_url: str = "http://localhost:8000"
    agent_control_api_key: str = ""
    policy_refresh_interval_seconds: int = 2

    azure_ai_project_endpoint: str = ""
    model_deployment_name: str = "gpt-4.1-mini"

    model_config = {"env_file": ".env", "extra": "ignore"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Foundry Hosted Agents set these env vars - use them as fallbacks
        if not self.azure_ai_project_endpoint:
            self.azure_ai_project_endpoint = os.environ.get(
                "AZURE_OPENAI_ENDPOINT", ""
            )
        if not self.model_deployment_name or self.model_deployment_name == "gpt-4.1-mini":
            self.model_deployment_name = os.environ.get(
                "AZURE_AI_MODEL_DEPLOYMENT_NAME", self.model_deployment_name
            )


settings = Settings()
