from langchain_openrouter import ChatOpenRouter
from langchain_core.language_models import BaseChatModel

def get_model(api_key, model_id) -> BaseChatModel:
    if api_key is None:
        raise ValueError("API key must be provided")
    return ChatOpenRouter(
        api_key=api_key,
        model=model_id,
    )
