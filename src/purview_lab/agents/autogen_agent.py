from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_core import FunctionCall
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    FunctionExecutionResultMessage,
    LLMMessage,
    ModelCapabilities,
    ModelFamily,
    ModelInfo,
    RequestUsage,
)

from .common import INSTRUCTIONS, AdditionTool, AgentResult, parse_prompt


class LocalToolClient(ChatCompletionClient):
    def __init__(self, a: int, b: int) -> None:
        self.arguments = json.dumps({"a": a, "b": b})

    async def create(self, messages: Sequence[LLMMessage], **kwargs: Any) -> CreateResult:
        for message in reversed(messages):
            if isinstance(message, FunctionExecutionResultMessage):
                result = message.content[0]
                if result.is_error:
                    raise RuntimeError("The AutoGen tool failed.")
                return CreateResult(
                    finish_reason="stop",
                    content=result.content,
                    usage=self.actual_usage(),
                    cached=False,
                )
        return CreateResult(
            finish_reason="function_calls",
            content=[FunctionCall(id="addition", name="add_numbers", arguments=self.arguments)],
            usage=self.actual_usage(),
            cached=False,
        )

    async def create_stream(
        self, messages: Sequence[LLMMessage], **kwargs: Any
    ) -> AsyncGenerator[str | CreateResult, None]:
        yield await self.create(messages, **kwargs)

    async def close(self) -> None:
        """The local scripted client owns no sockets or external resources."""

    def actual_usage(self) -> RequestUsage:
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def total_usage(self) -> RequestUsage:
        return self.actual_usage()

    def count_tokens(self, messages: Sequence[LLMMessage], **kwargs: Any) -> int:
        return sum(len(str(message.content).split()) for message in messages)

    def remaining_tokens(self, messages: Sequence[LLMMessage], **kwargs: Any) -> int:
        return 4096 - self.count_tokens(messages)

    @property
    def capabilities(self) -> ModelCapabilities:
        return {"vision": False, "function_calling": True, "json_output": False}

    @property
    def model_info(self) -> ModelInfo:
        return {
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": ModelFamily.UNKNOWN,
            "structured_output": False,
        }


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()
    client = LocalToolClient(a, b)
    agent = AssistantAgent(
        name="autogen_addition_agent",
        model_client=client,
        tools=[tool.add_numbers],
        system_message=INSTRUCTIONS,
        reflect_on_tool_use=True,
        max_tool_iterations=1,
    )
    try:
        result = await agent.run(task=prompt)
        message = result.messages[-1]
        if not isinstance(message, TextMessage):
            raise RuntimeError("AutoGen returned non-text output.")
        return AgentResult("autogen", "AutoGen", message.content.strip(), tuple(tool.calls))
    finally:
        await client.close()
