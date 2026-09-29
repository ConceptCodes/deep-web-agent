"""Deep Web Agent setup."""

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from deep_web_agent.model import get_model
from deep_web_agent.backend import initialize_backend
from deep_web_agent.memory import initialize_memory
from deep_web_agent.prompts import SYSTEM_MESSAGE
from deep_web_agent.settings import settings
from deep_web_agent.tools import tool_catalog

model = get_model(
    api_key=(
        settings.openai_api_key.get_secret_value()
        if settings.openai_api_key is not None
        else None
    ),
    model_id=settings.model_id,
)

memory_setup = initialize_memory()
backend_setup = initialize_backend(memory_setup.backend, store=memory_setup.store)

agent = create_deep_agent(
    model=model,
    tools=tool_catalog,
    middleware=[TodoListMiddleware()],
    backend=backend_setup.backend,
    skills=["/skills/"],
    memory=memory_setup.files,
    store=backend_setup.store,
    permissions=backend_setup.permissions,
    checkpointer=InMemorySaver(),
    system_prompt=SYSTEM_MESSAGE,
)
