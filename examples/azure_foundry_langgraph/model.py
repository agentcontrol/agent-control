import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain.chat_models import init_chat_model

from settings import settings


def create_chat_model():
    deployment = os.environ.get(
        "AZURE_AI_MODEL_DEPLOYMENT_NAME", settings.model_deployment_name
    )
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    # Don't pass azure_endpoint - let init_chat_model read AZURE_OPENAI_ENDPOINT
    # from the environment (set by Foundry Hosted Agents automatically).
    return init_chat_model(
        f"azure_openai:{deployment}",
        azure_ad_token_provider=token_provider,
    )
