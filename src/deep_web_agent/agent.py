"""Construct the agent within an explicit application lifetime."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from deep_web_agent.backend import initialize_backend
from deep_web_agent.browser import BrowserSession
from deep_web_agent.memory import MemorySetup, initialize_memory
from deep_web_agent.model import get_model
from deep_web_agent.prompts import SYSTEM_MESSAGE
from deep_web_agent.settings import settings
from deep_web_agent.tools import create_tools


@dataclass(frozen=True)
class AgentSession:
    agent: Any
    memory: MemorySetup


@contextmanager
def agent_session() -> Iterator[AgentSession]:
    """Build an agent and always release its browser, including startup failures."""
    browser = BrowserSession()
    try:
        model = get_model(
            api_key=(
                settings.openai_api_key.get_secret_value()
                if settings.openai_api_key is not None
                else None
            ),
            model_id=settings.model_id,
        )
        memory = initialize_memory(settings.memory_dir)
        backend = initialize_backend(memory)
        agent = create_deep_agent(
            model=model,
            tools=create_tools(browser),
            middleware=[TodoListMiddleware()],
            backend=backend.backend,
            skills=["/skills/"],
            memory=memory.files,
            store=backend.store,
            permissions=backend.permissions,
            checkpointer=InMemorySaver(),
            system_prompt=SYSTEM_MESSAGE,
        )
        yield AgentSession(agent, memory)
    finally:
        browser.shutdown()
