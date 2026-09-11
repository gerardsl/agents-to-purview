from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent_framework import (
    Agent,
    BaseChatClient,
    ChatOptions,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from .common import INSTRUCTIONS, AdditionTool, AgentResult, parse_prompt


class LocalToolClient(FunctionInvocationLayer[ChatOptions], BaseChatClient[ChatOptions]):
    def __init__(self, a: int, b: int) -> None:
        super().__init__(
            function_invocation_configuration={"max_iterations": 3, "max_function_calls": 1}
        )
        self.arguments = {"a": a, "b": b}

    async def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> ChatResponse:
        if stream:
            raise NotImplementedError("This test agent deliberately uses non-streaming responses.")
        for message in reversed(messages):
            for content in message.contents:
                if content.type == "function_result":
                    if content.exception:
                        raise RuntimeError("The Microsoft Agent Framework tool failed.")
                    return ChatResponse(messages=[Message("assistant", [str(content.result)])])
        return ChatResponse(
            messages=[
                Message(
                    "assistant",
                    [
                        Content(
                            "function_call",
                            call_id="addition",
                            name="add_numbers",
                            arguments=self.arguments,
                        )
                    ],
                )
            ]
        )


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()
    agent = Agent(
        client=LocalToolClient(a, b),
        name="microsoft-addition-agent",
        instructions=INSTRUCTIONS,
        tools=[tool.add_numbers],
    )
    result = await agent.run(prompt)
    return AgentResult(
        "microsoft", "Microsoft Agent Framework", result.text.strip(), tuple(tool.calls)
    )
