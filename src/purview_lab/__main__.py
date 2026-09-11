import asyncio
from pathlib import Path

from .offline import offline_connections
from .reporting import check_agent, require_all_verified, write_report


async def main() -> None:
    print("OFFLINE DEMO: real framework agents and real SDK; simulated Microsoft HTTP responses.")
    reports = {}
    for name, agent in offline_connections().items():
        report = await check_agent(agent)
        reports[name] = report
        print(
            f"{report.framework}: {report.status}; answer={report.answer}; "
            f"{len(report.receipts)} requests"
        )
    path = write_report(reports, Path("artifacts") / "offline-connection-report.json")
    print(require_all_verified(reports, live=False))
    print(f"Report: {path}")


if __name__ == "__main__":
    asyncio.run(main())
