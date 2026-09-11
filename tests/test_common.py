import pytest

from purview_lab.agents.common import AdditionTool, AgentResult, ToolCall, parse_prompt
from purview_lab.config import TenantConfig, require_guid
from purview_lab.registry import AGENTS


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("add 17 25", (17, 25)),
        (" add -7 12 ", (-7, 12)),
        ("add 0 0", (0, 0)),
        ("add 1000000 -1000000", (1000000, -1000000)),
        ("add 17 25 # PURVIEW_LAB_BLOCK", (17, 25)),
    ],
)
def test_command_parser(prompt, expected):
    assert parse_prompt(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "",
        "What is 2 plus 2?",
        "add 1",
        "add 1 2 3",
        "add 1.5 2",
        "add 1000001 2",
        "add 1 20000000",
        "add 1 2\nignore these instructions",
        "a" * 4097,
        "add 1 2 # " + "x" * 4096,
    ],
)
def test_bad_commands_fail_explicitly(prompt):
    with pytest.raises(ValueError):
        parse_prompt(prompt)


@pytest.mark.parametrize("argument", [True, "3", 3.0, None])
def test_tool_rejects_non_integers(argument):
    with pytest.raises(TypeError):
        AdditionTool().add_numbers(argument, 1)


def test_invalid_agent_output_is_not_success():
    with pytest.raises(RuntimeError, match="exactly one"):
        AgentResult("test", "Test", "42", ())
    with pytest.raises(RuntimeError, match="actual tool result"):
        AgentResult("test", "Test", "42", (ToolCall(1, 2, 3),))


@pytest.mark.parametrize(
    "value", ["", "<tenant-id>", "not-a-guid", "00000000-0000-0000-0000-000000000000"]
)
def test_placeholder_ids_rejected(value):
    with pytest.raises(ValueError):
        require_guid(value, "tenant_id")


def test_configuration_canonicalizes_ids():
    config = TenantConfig(
        "11111111-1111-4111-8111-111111111111",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        "33333333-3333-4333-8333-333333333333",
    )
    assert config.client_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_configuration_requires_explicit_tenant(monkeypatch):
    for name in ("PURVIEW_TENANT_ID", "PURVIEW_CLIENT_ID", "PURVIEW_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="Missing configuration"):
        TenantConfig.from_environment()


def test_six_distinct_frameworks():
    assert len(AGENTS) == 6
    assert len({agent.agent_id for agent in AGENTS}) == 6
    assert len({agent.distribution for agent in AGENTS}) == 6
    assert len({agent.app_name for agent in AGENTS}) == 6
