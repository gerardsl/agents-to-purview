from __future__ import annotations

import re
from dataclasses import dataclass, field

SAFE_PROMPT = "add 17 25"
INSTRUCTIONS = (
    "Call add_numbers once with the two integers in the user's add command. "
    "Return only the integer returned by the tool. Do not do arithmetic yourself."
)
_COMMAND = re.compile(r"add\s+(-?\d{1,7})\s+(-?\d{1,7})(?:\s+# [^\r\n]+)?", re.ASCII)


def parse_prompt(prompt: str) -> tuple[int, int]:
    if not isinstance(prompt, str) or len(prompt) > 4096:
        raise ValueError("Provide a text command of at most 4096 characters.")
    match = _COMMAND.fullmatch(prompt.strip())
    if match is None:
        raise ValueError("Use 'add <integer> <integer>', for example 'add 17 25'.")
    numbers = (int(match[1]), int(match[2]))
    if any(abs(number) > 1_000_000 for number in numbers):
        raise ValueError("Each integer must be between -1000000 and 1000000.")
    return numbers


@dataclass(frozen=True)
class ToolCall:
    a: int
    b: int
    result: int


@dataclass
class AdditionTool:
    calls: list[ToolCall] = field(default_factory=list)

    def add_numbers(self, a: int, b: int) -> int:
        """Add two integers.

        Args:
            a: First integer.
            b: Second integer.
        """
        if type(a) is not int or type(b) is not int:
            raise TypeError("add_numbers requires two integers, not strings or booleans.")
        if abs(a) > 1_000_000 or abs(b) > 1_000_000:
            raise ValueError("Tool arguments must be between -1000000 and 1000000.")
        result = a + b
        self.calls.append(ToolCall(a, b, result))
        return result


@dataclass(frozen=True)
class AgentResult:
    agent_id: str
    framework: str
    answer: str
    tool_calls: tuple[ToolCall, ...]

    def __post_init__(self) -> None:
        if len(self.tool_calls) != 1:
            raise RuntimeError(f"{self.framework} did not execute exactly one addition tool call.")
        if self.answer != str(self.tool_calls[0].result):
            raise RuntimeError(f"{self.framework} did not return the actual tool result.")
