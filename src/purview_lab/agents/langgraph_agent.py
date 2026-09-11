from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .common import AdditionTool, AgentResult, parse_prompt


async def run(prompt: str) -> AgentResult:
    a, b = parse_prompt(prompt)
    tool = AdditionTool()

    def local_model(state: MessagesState) -> dict[str, list[AIMessage]]:
        last = state["messages"][-1]
        if isinstance(last, ToolMessage):
            return {"messages": [AIMessage(content=last.content)]}
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "add_numbers", "args": {"a": a, "b": b}, "id": "addition"}
                    ],
                )
            ]
        }

    graph = StateGraph(MessagesState)
    graph.add_node("agent", local_model)
    graph.add_node("tools", ToolNode([tool.add_numbers], handle_tool_errors=False))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    result = await graph.compile().ainvoke(
        {"messages": [HumanMessage(content=prompt)]}, {"recursion_limit": 6}
    )
    answer = result["messages"][-1].content
    if not isinstance(answer, str):
        raise RuntimeError("LangGraph returned non-text output.")
    return AgentResult("langgraph", "LangGraph", answer.strip(), tuple(tool.calls))
