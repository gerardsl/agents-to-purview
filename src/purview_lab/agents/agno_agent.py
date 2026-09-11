from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse

from .common import INSTRUCTIONS, AdditionTool, AgentResult, parse_prompt


@dataclass
class LocalToolModel(Model):
    a: int = 0
    b: int = 0

    def invoke(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        for message in reversed(messages):
            if message.role == "tool":
                return ModelResponse(role="assistant", content=str(message.content))
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "addition",
                    "type": "function",
                    "function": {
                        "name": "add_numbers",
                        "arguments": json.dumps({"a": self.a, "b": self.b}),
                    },
                }
            ],
        )

    async def ainvoke(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError("This test agent deliberately uses non-streaming responses.")

    def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError("This test agent deliberately uses non-streaming responses.")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        if not isinstance(response, ModelResponse):
            raise TypeError("The local model must return an Agno ModelResponse.")
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._parse_provider_response(response)


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()
    agent = Agent(
        name="agno-addition-agent",
        model=LocalToolModel(id="local-addition-model", a=a, b=b),
        tools=[tool.add_numbers],
        instructions=INSTRUCTIONS,
        tool_call_limit=1,
        telemetry=False,
        markdown=False,
    )
    result = await agent.arun(prompt, stream=False)
    if not isinstance(result.content, str):
        raise RuntimeError("Agno returned non-text output.")
    return AgentResult("agno", "Agno", result.content.strip(), tuple(tool.calls))
