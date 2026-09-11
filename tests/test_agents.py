import pytest

from purview_lab.agents.common import ToolCall
from purview_lab.registry import AGENTS


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
@pytest.mark.parametrize(("a", "b"), [(17, 25), (-7, 12), (0, 0), (-19, -23), (1000000, -1000000)])
async def test_native_framework_executes_tool_and_returns_its_result(agent, a, b):
    result = await agent.run(f"add {a} {b}")
    assert result.agent_id == agent.agent_id
    assert result.framework == agent.framework
    assert result.answer == str(a + b)
    assert result.tool_calls == (ToolCall(a, b, a + b),)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_runs_are_independent(agent):
    first = await agent.run("add 1 2")
    second = await agent.run("add 30 12")
    assert first.answer == "3"
    assert second.answer == "42"
    assert len(first.tool_calls) == len(second.tool_calls) == 1


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_all_agents_reject_invalid_commands(agent):
    with pytest.raises(ValueError):
        await agent.run("not a supported command")
