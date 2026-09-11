from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Protocol

from .agents.common import AgentResult


def disable_external_telemetry() -> None:
    """Keep these synthetic local agents from sending third-party telemetry."""
    for key, value in {
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "AGNO_TELEMETRY": "false",
        "AGNO_TRACKING": "false",
        "OTEL_SDK_DISABLED": "true",
        "DO_NOT_TRACK": "1",
    }.items():
        os.environ[key] = value


class AgentRunner(Protocol):
    async def __call__(self, prompt: str) -> AgentResult: ...


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    framework: str
    distribution: str
    module: str

    @property
    def app_name(self) -> str:
        return f"Purview Lab - {self.framework}"

    async def run(self, prompt: str) -> AgentResult:
        disable_external_telemetry()
        module = importlib.import_module(f"purview_lab.agents.{self.module}")
        runner: AgentRunner = module.run
        return await runner(prompt)


AGENTS = (
    AgentSpec("microsoft", "Microsoft Agent Framework", "agent-framework-core", "microsoft_agent"),
    AgentSpec("langgraph", "LangGraph", "langgraph", "langgraph_agent"),
    AgentSpec("autogen", "AutoGen", "autogen-agentchat", "autogen_agent"),
    AgentSpec("pydantic", "PydanticAI", "pydantic-ai-slim", "pydantic_agent"),
    AgentSpec("openai", "OpenAI Agents SDK", "openai-agents", "openai_agent"),
    AgentSpec("agno", "Agno", "agno", "agno_agent"),
)
AGENTS_BY_ID = {agent.agent_id: agent for agent in AGENTS}
