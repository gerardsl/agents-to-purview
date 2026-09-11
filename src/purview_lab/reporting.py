from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from azure.core.exceptions import ClientAuthenticationError

from .agents.common import SAFE_PROMPT
from .errors import IntegrationError, PolicyBlocked
from .purview import ConnectedAgent
from .registry import AGENTS
from .sdk import SDK_VERSION, HttpReceipt

Status = Literal["LIVE_API_VERIFIED", "OFFLINE_SIMULATED", "POLICY_BLOCKED", "FAILED"]


@dataclass(frozen=True)
class CheckReport:
    agent_id: str
    framework: str
    mode: Literal["offline", "live"]
    status: Status
    message: str
    receipts: tuple[HttpReceipt, ...]
    answer: str | None = None
    conversation_id: str | None = None
    prompt_policy_mode: str | None = None
    response_policy_mode: str | None = None
    prompt_outcome: str | None = None
    response_outcome: str | None = None
    blocked_stage: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    user_id: str | None = None


async def check_agent(connected: ConnectedAgent, prompt: str = SAFE_PROMPT) -> CheckReport:
    status: Status
    conversation_id = None
    blocked_stage = None
    try:
        result = await connected.run(prompt)
    except PolicyBlocked as exc:
        status = "POLICY_BLOCKED"
        message = str(exc)
        conversation_id = exc.correlation_id
        blocked_stage = exc.stage
    except IntegrationError as exc:
        status = "FAILED"
        message = str(exc)
    except ClientAuthenticationError:
        status = "FAILED"
        message = (
            "Microsoft authentication failed. Check the selected tenant/app, sign-in method, "
            "Conditional Access, and administrator consent. "
            "No raw authentication details were saved."
        )
    except TimeoutError:
        status = "FAILED"
        message = "The local framework agent exceeded its 30-second execution limit."
    else:
        return CheckReport(
            agent_id=connected.agent.agent_id,
            framework=connected.agent.framework,
            mode=result.mode,
            status="LIVE_API_VERIFIED" if result.live_api_verified else "OFFLINE_SIMULATED",
            message=(
                "Live SDK round-trip verified; portal ingestion is a separate check."
                if result.live_api_verified
                else "HTTP simulation passed. No Microsoft tenant was contacted."
            ),
            receipts=result.receipts,
            answer=result.agent.answer,
            conversation_id=result.conversation_id,
            prompt_policy_mode=result.prompt.mode,
            response_policy_mode=result.response.mode,
            prompt_outcome=result.prompt.outcome,
            response_outcome=result.response.outcome,
            tenant_id=connected.config.tenant_id,
            client_id=connected.config.client_id,
            user_id=connected.config.user_id,
        )
    return CheckReport(
        agent_id=connected.agent.agent_id,
        framework=connected.agent.framework,
        mode=connected.mode,
        status=status,
        message=message,
        receipts=tuple(connected.receipts),
        conversation_id=conversation_id,
        blocked_stage=blocked_stage,
        tenant_id=connected.config.tenant_id,
        client_id=connected.config.client_id,
        user_id=connected.config.user_id,
    )


def _complete_set(reports: Mapping[str, CheckReport]) -> bool:
    return set(reports) == {agent.agent_id for agent in AGENTS} and all(
        key == report.agent_id for key, report in reports.items()
    )


def require_all_verified(reports: Mapping[str, CheckReport], *, live: bool) -> str:
    if not _complete_set(reports):
        raise IntegrationError(
            "The report must contain exactly the six expected agents, without duplicates."
        )
    expected = "LIVE_API_VERIFIED" if live else "OFFLINE_SIMULATED"
    mode = "live" if live else "offline"
    failed = [
        report.agent_id
        for report in reports.values()
        if report.status != expected or report.mode != mode
    ]
    if failed:
        raise IntegrationError(
            f"Not all six agents were verified: {', '.join(failed)}. "
            "Read their individual results; do not interpret this run as a successful connection."
        )
    if live:
        return (
            "6/6 LIVE API round-trips verified. "
            "Portal ingestion and DLP blocking are separate checks."
        )
    return "6/6 offline SDK simulations passed. LIVE TENANT NOT VERIFIED."


def write_report(reports: Mapping[str, CheckReport], path: Path) -> Path:
    complete = _complete_set(reports)
    live_verified = complete and all(
        report.mode == "live" and report.status == "LIVE_API_VERIFIED"
        for report in reports.values()
    )
    offline_passed = complete and all(
        report.mode == "offline" and report.status == "OFFLINE_SIMULATED"
        for report in reports.values()
    )
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "expected_agents": 6,
        "reported_agents": len(reports),
        "live_tenant_verified": live_verified,
        "offline_simulation_passed": offline_passed,
        "portal_ingestion_verified": False,
        "live_dlp_blocking_verified": False,
        "verification_boundary": (
            "SDK API acknowledgements only. A 202/204 is not an inline verdict. "
            "No-policy results log metadata only. Portal ingestion needs separate manual evidence."
        ),
        "purview_sdk_version": SDK_VERSION,
        "framework_versions": {agent.distribution: version(agent.distribution) for agent in AGENTS},
        "agents": [asdict(report) for report in reports.values()],
    }
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
