"""Generate the walkthrough notebook from maintainable, reviewable cell sources."""

import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from textwrap import dedent

import nbformat

ROOT = Path(__file__).resolve().parents[1]
cells = []


def markdown(source: str) -> None:
    source = dedent(source).strip()
    cells.append(nbformat.v4.new_markdown_cell(source, id=sha256(source.encode()).hexdigest()[:12]))


def code(source: str) -> None:
    source = dedent(source).strip()
    source = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "I",
            "--fix",
            "--stdin-filename",
            "cell.py",
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    ).stdout
    source = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", "cell.py", "-"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    ).stdout.strip()
    cells.append(nbformat.v4.new_code_cell(source, id=sha256(source.encode()).hexdigest()[:12]))


markdown("""
    # Connect six framework agents to Microsoft Purview

    **Run the cells in order with Shift+Enter.** Select the kernel
    **Python (six agents + Purview)**, or this folder's `.venv\\Scripts\\python.exe`.
    If it is not available, run `.\u005csetup.ps1` in this folder first.

    You will first run six real local agents, then supply your Microsoft tenant/app/user
    IDs, sign in, and run one Purview SDK check per agent. No hosted language model or
    model API key is needed. The only generated text is synthetic arithmetic.

    **Important boundaries:** a tenant ID alone is not enough; your administrator must
    prepare registration, permissions, licensing/billing, and Purview policies.
    This notebook does not grant permissions or change tenant settings. Running the
    live check cells sends synthetic interactions/metadata to Microsoft and can incur
    Purview consumption charges or create retained/audited records.

    **Three different checks:** API connectivity, DLP enforcement, and Purview portal
    ingestion are not interchangeable. Offline demonstrations are always labeled
    `OFFLINE_SIMULATED`, never "connected."
""")

markdown("""
    ## 1. Check the kernel and dependencies

    This cell uses the exact versions in this project. If runtime packages are missing,
    it restores them into the **selected kernel**, using the lock file. When packages
    are already present, it does not reinstall them or contact a package index.

    Default mode is **live**. For a credentials-free rehearsal, change `MODE` to
    `"offline"` in this cell before running it. Automated notebook tests use that mode.
""")
code("""
    import os
    import subprocess
    import sys
    import sysconfig
    import tomllib
    from importlib.metadata import PackageNotFoundError, version
    from pathlib import Path

    ROOT = Path.cwd()
    if not (ROOT / "pyproject.toml").is_file():
        raise RuntimeError("Open this folder in VS Code and restart this notebook's kernel.")
    if sys.version_info[:2] != (3, 12) or sysconfig.get_platform() != "win-amd64":
        raise RuntimeError("Select the x64 Python 3.12 kernel prepared by setup.ps1.")

    MODE = os.environ.get("PURVIEW_LAB_MODE", "live")  # Change to "offline" for a rehearsal.
    if MODE not in ("live", "offline"):
        raise ValueError("MODE must be live or offline.")
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mismatches = []
    requirements = manifest["project"]["dependencies"] + [
        f"six-agents-purview=={manifest['project']['version']}"
    ]
    for requirement in requirements:
        package, expected = requirement.split("==")
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = None
        if actual != expected:
            mismatches.append(package)
    if mismatches:
        if MODE == "offline":
            raise RuntimeError(f"Restore dependencies with setup.ps1 first: {mismatches}")
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--quiet", "--only-binary=:all:",
                "--constraint", str(ROOT / "requirements-lock.txt"),
                "--editable", ".[notebook,test]",
            ],
            cwd=ROOT,
            check=True,
        )
    print(f"Kernel: {sys.executable}")
    print(f"Mode: {MODE.upper()}. Dependencies are ready. No tenant connection has been tested yet.")
""")

markdown("""
    ## 2. Run all six real agents locally

    Each framework runs its own native tool execution loop. The test model is
    deterministic: it requests `add_numbers`, the framework executes that tool, and
    the model returns the tool result. These are not six aliases for one agent.

    Expected: **six rows, each with answer `42` and exactly one tool call**.
    This checks agent execution, not tenant connectivity.
""")
code("""
    from dataclasses import asdict, replace
    from IPython.display import Markdown, display
    from purview_lab.agents.common import SAFE_PROMPT
    from purview_lab.registry import AGENTS, disable_external_telemetry

    disable_external_telemetry()
    native_results = []
    for agent in AGENTS:
        native_results.append(await agent.run(SAFE_PROMPT))
    assert len(native_results) == 6
    assert all(result.answer == "42" and len(result.tool_calls) == 1 for result in native_results)
    lines = ["| Framework | Answer | Native tool calls |", "| --- | --- | --- |"]
    lines += [
        f"| {result.framework} | {result.answer} | {len(result.tool_calls)} |"
        for result in native_results
    ]
    display(Markdown("\\n".join(lines)))
    print("6/6 local agents passed. Tenant connectivity is still unverified.")
""")

markdown("""
    ## 3. One-time tenant preparation (administrator)

    Complete this before the live cells. If it is not ready, use offline mode; do not
    interpret an offline pass as proof of tenant configuration.

    1. Use an organizational Microsoft 365 tenant with the needed Purview features and
       billing. The [SDK prerequisites](https://learn.microsoft.com/agent-framework/integrations/by-component/middleware/purview?pivots=programming-language-python)
       list E5 and pay-as-you-go billing; confirm eligibility with your administrator.
    2. In **Entra ID > App registrations > New registration**, register a single-tenant
       test app, for example **Purview Six-Agent Lab**. Copy its **Application (client) ID**
       and **Directory (tenant) ID**.
    3. For browser sign-in, select **Authentication > Add a platform > Mobile and desktop
       applications**, and add **`http://localhost`**. The SDK automatically chooses an
       available localhost callback port. For device-code sign-in, also enable
       **Allow public client flows**. Device code is an alternative only if tenant
       policy allows it; it does not bypass Conditional Access.
    4. In **API permissions > Microsoft Graph > Delegated permissions**, add
       **`ProtectionScopes.Compute.User`**, **`Content.Process.User`**, and
       **`ContentActivity.Write`**. Have your administrator grant consent.
    5. In **Entra ID > Users**, select the test user and copy their **Object ID**.
       It must be the user signing in, not an email address or service-principal ID.
    6. In [Purview](https://purview.microsoft.com), enable Audit and the appropriate
       DSPM for AI collection policy for the test user/application. Follow the
       [configuration guide](https://learn.microsoft.com/purview/developer/configurepurview).
       An inline DLP rule is separate from an audit/collection policy. Current guidance
       requires `New-DlpComplianceRule` for application DLP policies; have an administrator
       scope any test rule narrowly, not to the whole production tenant.

    **One app or six?** The easiest path uses one registered app for six logical agents.
    All six have distinct names and agent metadata, but Purview can group them under
    that single client ID. If you need six separate enterprise-app identities, register
    six applications and put their client IDs in `CLIENT_IDS_BY_AGENT` below. Every
    registration then needs permissions, consent, authentication, and policy scope.

    **Optional app-only authentication:** set `AUTH_MODE = "client_secret"` below only
    for a confidential app your administrator has configured. The SDK guidance lists
    application permissions `ProtectionScopes.Compute.All`, `Content.Process.All`, and
    `ContentActivity.Write`; use the least permissions your administrator authorizes
    for your user scope. The secret is requested with `getpass`, never stored in a cell.
""")

markdown("""
    ## 4. Enter your tenant details

    In live mode, this cell prompts for three GUIDs. The default authentication method
    is interactive browser sign-in, with no secret. No ambient Azure CLI identity
    or default tenant is used.

    In offline mode it uses obviously synthetic IDs and no real credentials.
""")
code("""
    from purview_lab.config import TenantConfig
    from purview_lab.offline import DEMO_CONFIG

    AUTH_MODE = "interactive"  # Supported alternatives: "device_code", "client_secret".
    if MODE == "live":
        base_config = TenantConfig(
            tenant_id=input("Directory (tenant) ID: ").strip(),
            client_id=input("Application (client) ID: ").strip(),
            user_id=input("Test user's Object ID: ").strip(),
            auth_mode=AUTH_MODE,
        )
    else:
        base_config = DEMO_CONFIG

    CLIENT_IDS_BY_AGENT = {agent.agent_id: base_config.client_id for agent in AGENTS}
    # For separate enterprise apps, replace individual values with their registered client IDs.
    configs = {
        agent.agent_id: replace(base_config, client_id=CLIENT_IDS_BY_AGENT[agent.agent_id])
        for agent in AGENTS
    }
    app_client_ids = {config.client_id for config in configs.values()}
    app_count = len(app_client_ids)
    print(f"Configured {len(configs)} agents using {app_count} app registration(s).")
    print("Configuration is in kernel memory. It is not proof of a Purview connection.")
""")

markdown("""
    ## 5. Sign in and prepare the SDK connections

    In live mode, finish Microsoft's sign-in prompt in the browser. A shared registration
    signs in once, while distinct client IDs each need authentication. The credential is
    explicitly bound to the tenant and app you entered.

    This step prepares reusable connections. **It does not yet claim any agent is connected.**
    The following six cells make the actual Purview API calls.
""")
code("""
    from getpass import getpass
    from purview_lab.live import LiveLab
    from purview_lab.offline import offline_connections
    from purview_lab.reporting import check_agent, require_all_verified, write_report

    previous_live_lab = globals().get("live_lab")
    if previous_live_lab is not None:
        await previous_live_lab.close()
    live_lab = None
    if MODE == "live":
        secrets = {}
        if AUTH_MODE == "client_secret":
            secrets = {
                client_id: getpass(f"Client secret for {client_id} (never saved): ")
                for client_id in app_client_ids
            }
        try:
            live_lab = await LiveLab.connect(configs, secrets=secrets)
        finally:
            secrets.clear()
        connections = live_lab.connections
        print("Authentication succeeded. The six Purview API checks have not run yet.")
    else:
        connections = offline_connections()
        print("OFFLINE SIMULATION: actual SDK, mocked HTTP responses, no Microsoft sign-in.")
    reports = {}
""")

markdown("""
    ## How to read each agent's result

    The wrapper computes protection scopes, checks the prompt, runs the native agent,
    and checks its answer. It waits for SDK calls to complete and fails closed on errors.
    A `modified` scope state refreshes cached policies, not the already returned decision.
    Fresh scope blocks still apply, and a stricter inline policy requires an inline recheck.

    | Result | Meaning |
    | --- | --- |
    | `LIVE_API_VERIFIED` | The agent completed real authenticated SDK calls and returned its checked answer. |
    | `OFFLINE_SIMULATED` | Real framework + SDK code passed with mocked HTTP; no tenant was contacted. |
    | `POLICY_BLOCKED` | Purview blocked input or output. The blocked content was not released. |
    | `FAILED` | Authentication, permissions, billing, networking, or response validation failed. |

    `evaluateInline / allowed` is an inline decision. `acceptedWithoutVerdict` means
    asynchronous acceptance, **not** a real-time allow decision. `metadataLoggedOnly`
    means no applicable policy was found: only audit metadata was submitted, not prompt
    retention or DLP protection. Fix tenant policy scope if protection was expected.

    Each check is recorded even if another agent fails, so you can see all six results.
    A final assertion refuses to report success unless the complete set passes.
""")

agent_sections = [
    ("microsoft", "Microsoft Agent Framework", "Agent + FunctionInvocationLayer"),
    ("langgraph", "LangGraph", "StateGraph + ToolNode"),
    ("autogen", "AutoGen", "AssistantAgent + native function execution"),
    ("pydantic", "PydanticAI", "Agent + FunctionModel"),
    ("openai", "OpenAI Agents SDK", "Agent + Runner + function_tool"),
    ("agno", "Agno", "Agent + custom local Model"),
]
for index, (agent_id, framework, mechanism) in enumerate(agent_sections, 1):
    markdown(f"""
        ## 6.{index}. Connect and check: {framework}

        Native implementation: **{mechanism}**. Runs `add 17 25`.
        Expected answer: `42`. A live success requires actual Microsoft SDK responses.
    """)
    code(f"""
        reports["{agent_id}"] = await check_agent(connections["{agent_id}"])
        display(asdict(reports["{agent_id}"]))
    """)

markdown("""
    ## 7. Save evidence and require all six checks to pass

    This writes a JSON report under `artifacts`. It contains per-agent outcomes,
    framework/SDK versions, target tenant/app/user IDs, conversation IDs, HTTP status
    codes, and request IDs.
    It does **not** save tokens, secrets, raw HTTP bodies, or prompts.

    Offline reports always have `live_tenant_verified: false`. Live verification is
    marked true only for six successful **live** round-trips. Portal ingestion and
    live DLP blocking remain false until separately verified; this report deliberately
    makes no claim about them. A failed report is saved before the assertion raises.
""")
code("""
    default_report = ROOT / "artifacts" / f"{MODE}-connection-report.json"
    report_path = Path(os.environ.get("PURVIEW_LAB_REPORT_PATH", str(default_report)))
    saved_report = write_report(reports, report_path)
    print(f"Evidence saved to: {saved_report}")
    print(require_all_verified(reports, live=(MODE == "live")))
    for report in reports.values():
        if "noApplicablePolicy" in (report.prompt_policy_mode, report.response_policy_mode):
            print(
                f"WARNING: {report.framework}: "
                "no applicable policy for at least one direction; metadata only."
            )
""")

markdown("""
    ## 8. Optional: verify real DLP blocking

    Leave this **off** unless an administrator has configured a test-scoped inline DLP
    rule that detects the synthetic marker **`PURVIEW_LAB_BLOCK`** for your test user
    and app(s). This is a custom test keyword, not a built-in sensitive-information type.

    Set `RUN_DLP_PROBE = True` only after that rule is active. Expected: all six agents
    report **prompt** blocking, before the framework is invoked. A missing block fails
    this check. It never disables or bypasses policies to force a passing result.

    Offline mode can demonstrate the blocking path, but cannot prove a tenant DLP rule.
""")
code("""
    RUN_DLP_PROBE = False
    if RUN_DLP_PROBE:
        import json
        from purview_lab.offline import BLOCK_MARKER

        dlp_reports = {}
        for name, agent in connections.items():
            dlp_reports[name] = await check_agent(agent, f"{SAFE_PROMPT} # {BLOCK_MARKER}")
        for report in dlp_reports.values():
            display(asdict(report))
        blocked_all = len(dlp_reports) == 6 and all(
            report.status == "POLICY_BLOCKED" and report.blocked_stage == "prompt"
            for report in dlp_reports.values()
        )
        dlp_evidence = {
            "mode": MODE,
            "live_dlp_blocking_verified": MODE == "live" and blocked_all,
            "agents": [asdict(report) for report in dlp_reports.values()],
        }
        dlp_path = saved_report.with_name(f"{MODE}-dlp-probe.json")
        dlp_path.write_text(json.dumps(dlp_evidence, indent=2), encoding="utf-8")
        assert blocked_all, "DLP probe did not block all six prompts. Inspect the test policy and results."
        print("6/6 prompt blocks verified." if MODE == "live" else "6/6 MOCK blocks demonstrated; no tenant proof.")
    else:
        print("DLP blocking probe NOT RUN. A safe arithmetic response does not prove DLP blocking.")
""")

markdown("""
    ## 9. Confirm ingestion in the Purview portal (separate, manual check)

    APIs acknowledge receipt before every Purview UI/report has necessarily updated.
    The Purview integration APIs do not expose a general read-back API for these
    analytics. Do not mark portal ingestion complete just because HTTP requests passed.

    Open [Purview](https://purview.microsoft.com) in the **same tenant** and follow the
    [official test guide](https://learn.microsoft.com/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk):

    - **DSPM for AI / Activity explorer:** filter Enterprise AI apps and the test
      application, user, and time window. Identify the six agent interactions using
      their names/metadata and the conversation IDs in the saved report.
    - **Audit:** filter workload `ConnectedAIApp`, or activity
      `connectedAIAppInteraction`. Confirm events corresponding to the test run.
    - **eDiscovery**, if enabled and authorized: the documented query pattern is
      `ItemClass=IPM.SkypeTeams.Message.ConnectedAIApp.Entra.*YourEntraAppID*`.
      Verify retained prompt/response content only when a collection policy enables it.

    Ingestion and policy propagation take time; some reports can require at least a
    day. If you only received `metadataLoggedOnly`, do not expect full prompt retention.
    One shared app registration may appear as one app, not six enterprise apps.
    Save any manual portal evidence separately according to your organization's policy.

    ## 10. Troubleshooting

    | Problem | Check |
    | --- | --- |
    | Wrong kernel / compiler error | Use the project's x64 Python 3.12 `.venv` kernel; run `setup.ps1`. |
    | Sign-in / redirect error | Correct tenant/client ID, `http://localhost`, public-client settings, and Conditional Access. |
    | 401 / 403 | Correct delegated/application permission type, admin consent, and user's Object ID. |
    | 402 | Purview entitlement, pay-as-you-go billing, and feature enablement. |
    | 429 | Wait for the retry interval, then rerun that agent's cell. |
    | No inline decision | Treat as unverified; review policy mode and service behavior. |
    | No policy / no portal data | Check collection/DLP scope and ingestion delay; API success is not retention proof. |
    | SDK version error | Restore `requirements-lock.txt`; do not blindly upgrade the preview adapter. |

    After fixing configuration, rerun **steps 4 and 5**, the six checks, and the
    report cell. After changing only a tenant policy, rerun the checks and report;
    each new run recomputes scopes.
""")

markdown("""
    ## 11. Close credentials

    Run this when finished, then shut down the notebook kernel. HTTP sessions are
    already closed after each invocation; this closes the shared identity credentials.
    To run more live checks after cleanup, rerun the sign-in cell first.
    Clear outputs before sharing this notebook.
""")
code("""
    if live_lab is not None:
        await live_lab.close()
        live_lab = None
    print("Credentials closed. Shut down the kernel when finished; no secrets were written by this lab.")
""")

markdown("""
    ## Implementation and references

    `src\\purview_lab\\agents` contains six independent framework agents.
    `purview.py` implements the guarded invocation boundary; `sdk.py` contains the
    pinned preview SDK compatibility adapter. See `README.md` for the exact SDK
    serialization fixes, tests, and the limits of extending this example.

    - [Microsoft Purview SDK](https://learn.microsoft.com/agent-framework/integrations/by-component/middleware/purview?pivots=programming-language-python)
    - [Purview API integration sequence](https://learn.microsoft.com/purview/developer/use-the-api)
    - [Protection scopes API](https://learn.microsoft.com/graph/api/userprotectionscopecontainer-compute?view=graph-rest-1.0)
    - [Process content API](https://learn.microsoft.com/graph/api/userdatasecurityandgovernance-processcontent?view=graph-rest-1.0)
    - [Configure tenant policies](https://learn.microsoft.com/purview/developer/configurepurview)
""")


def main() -> None:
    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python (six agents + Purview)",
                "language": "python",
                "name": "six-agents-purview",
            },
            "language_info": {"name": "python", "version": "3.12.10"},
        },
    )
    nbformat.validate(notebook)
    destination = ROOT / "connect_agents_to_purview.ipynb"
    nbformat.write(notebook, destination)
    print(f"Created {destination.name}: {len(cells)} cells.")


if __name__ == "__main__":
    main()
