from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agents import (
    Agent,
    ModelResponse,
    ModelSettings,
    RunConfig,
    Runner,
    Tool,
    Usage,
    function_tool,
)
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelTracing
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from .common import INSTRUCTIONS, AdditionTool, AgentResult, parse_prompt


class LocalToolModel(Model):
    def __init__(self, a: int, b: int) -> None:
        self.arguments = json.dumps({"a": a, "b": b})

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        **kwargs: Any,
    ) -> ModelResponse:
        if isinstance(input, list):
            for item in reversed(input):
                if item.get("type") == "function_call_output":
                    output = item.get("output")
                    if not isinstance(output, str):
                        raise RuntimeError("The OpenAI Agents tool returned non-text output.")
                    return ModelResponse(
                        output=[
                            ResponseOutputMessage(
                                id="answer",
                                type="message",
                                role="assistant",
                                status="completed",
                                content=[
                                    ResponseOutputText(
                                        type="output_text", text=output, annotations=[]
                                    )
                                ],
                            )
                        ],
                        usage=Usage(),
                        response_id="local-answer",
                    )
        return ModelResponse(
            output=[
                ResponseFunctionToolCall(
                    id="tool-call",
                    type="function_call",
                    call_id="addition",
                    name="add_numbers",
                    arguments=self.arguments,
                )
            ],
            usage=Usage(),
            response_id="local-tool-call",
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("This test agent deliberately uses non-streaming responses.")


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()
    agent = Agent(
        name="openai-addition-agent",
        instructions=INSTRUCTIONS,
        model=LocalToolModel(a, b),
        tools=[function_tool(tool.add_numbers, failure_error_function=None)],
    )
    result = await Runner.run(
        agent, prompt, max_turns=3, run_config=RunConfig(tracing_disabled=True)
    )
    if not isinstance(result.final_output, str):
        raise RuntimeError("OpenAI Agents SDK returned non-text output.")
    return AgentResult(
        "openai", "OpenAI Agents SDK", result.final_output.strip(), tuple(tool.calls)
    )
