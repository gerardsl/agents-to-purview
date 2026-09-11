from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import UsageLimits

from .common import INSTRUCTIONS, AdditionTool, AgentResult, parse_prompt


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()

    def local_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for message in reversed(messages):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    return ModelResponse(parts=[TextPart(str(part.content))])
        return ModelResponse(
            parts=[ToolCallPart("add_numbers", {"a": a, "b": b}, tool_call_id="addition")]
        )

    agent = Agent(
        FunctionModel(local_model),
        name="pydantic-addition-agent",
        instructions=INSTRUCTIONS,
        tools=[tool.add_numbers],
        retries=0,
    )
    result = await agent.run(prompt, usage_limits=UsageLimits(request_limit=3, tool_calls_limit=1))
    return AgentResult("pydantic", "PydanticAI", result.output.strip(), tuple(tool.calls))
