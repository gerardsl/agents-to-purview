# Six agents connected to Microsoft Purview

Before running the **live tenant checks**, prepare the permissions below and fill
in the tenant-details box. Local/offline demonstrations do not require these permissions.

## Required permissions

The notebook's default **interactive browser sign-in** uses Microsoft Graph
**delegated permissions** on your Microsoft Entra app registration:

| Microsoft Graph permission | Type | Why it is needed |
| --- | --- | --- |
| `ProtectionScopes.Compute.User` | Delegated | Determine which Purview policies apply to the signed-in user's activities. |
| `Content.Process.User` | Delegated | Submit the agents' prompts and responses for Purview processing. |
| `ContentActivity.Write` | Delegated | Log activity metadata when no applicable content-processing policy is returned. |

In the [Microsoft Entra admin center](https://entra.microsoft.com), go to
**Entra ID > App registrations > your application > API permissions > Add a permission >
Microsoft Graph > Delegated permissions**. Add all three permissions, then have an
authorized administrator select **Grant admin consent for your tenant**.

**One app registration can serve all six agents.** For browser sign-in, configure
its **Mobile and desktop applications** platform with redirect URI **`http://localhost`**.
The SDK chooses an available localhost callback port automatically.

Your tenant also needs the applicable **Purview licensing and pay-as-you-go billing**,
plus Audit and AI collection policies scoped to your test user and application.
A separate DLP test rule is needed to verify blocking. See
[What your administrator must prepare](#what-your-administrator-must-prepare) for the full setup.
Unattended app-only authentication uses **application permissions**, not the delegated
permissions above; see [Repeat the tests](#repeat-the-tests) for that alternative.

## Fill in your tenant details

Use this box as a worksheet. Replace the placeholders with your values, then enter
them when **step 4 of the notebook** prompts you. **Editing this README does not
automatically configure or connect the agents.**

```text
YOUR MICROSOFT TENANT DETAILS

Tenant ID       : <paste the Directory (tenant) ID here>
App ID          : <paste the Application (client) ID here>
User Object ID  : <paste the test user's Object ID here>
```

### Where to find each ID

First open the [Microsoft Entra admin center](https://entra.microsoft.com) and
switch to the **directory you intend to test**.

| Field in the box | Exact location in Microsoft Entra | Make sure you copy |
| --- | --- | --- |
| **Tenant ID** | **Entra ID > Overview > Tenant ID** | The directory's tenant ID, not an Azure subscription ID. |
| **App ID** | **Entra ID > App registrations > select your test app > Overview > Application (client) ID** | The **Application (client) ID**, not the application's Object ID or service-principal Object ID. |
| **User Object ID** | **Entra ID > Users > All users > select the account you will sign in with > Overview > Object ID** | That **user's Object ID**, not their email address and not an application identity. |

The application and test user must be in the intended tenant. For the default
delegated workflow, sign in as the user whose Object ID you entered.
These IDs are configuration identifiers, not credentials. **Do not put passwords,
MFA codes, access tokens, or client secrets in this box.** You complete sign-in and
MFA directly with Microsoft; no client secret is needed for the default workflow.

## Start here

Open **`connect_agents_to_purview.ipynb`** and run its cells from top to bottom.
It guides you through local checks, tenant configuration, sign-in, six individual
SDK connection checks, a machine-readable report, and the separate Purview portal check.

**Offline tests are not proof of a live connection. Use a live report for your configured tenant.**
The notebook reports live success only after actual Microsoft API responses for all six agents.

The project uses an isolated **x64 Python 3.12** environment, including on Windows ARM64.
It does not replace your system Python.

```powershell
.\setup.ps1
```

If your organization's execution policy prevents running local scripts, use its
approved script-signing or execution process; do not disable organizational policy.
Setup needs a working `python` with pip for its first bootstrap, downloads a local
Python runtime if needed, restores locked packages, registers the notebook kernel,
and runs offline tests. It never signs in or changes tenant settings.

In VS Code, open the notebook and select **Python (six agents + Purview)**, or
`.venv\Scripts\python.exe`. Use **Shift+Enter** for each cell. The notebook prompts
for tenant, application, and user object IDs. By default, it opens Microsoft's
browser sign-in; no client secret is needed.

## The six actual frameworks

| Agent source under `src\purview_lab\agents` | Framework | Native execution exercised |
| --- | --- | --- |
| `microsoft_agent.py` | Microsoft Agent Framework | `Agent` and `FunctionInvocationLayer` |
| `langgraph_agent.py` | LangGraph | `StateGraph`, conditional routing, `ToolNode` |
| `autogen_agent.py` | AutoGen | `AssistantAgent` with function calling and reflection |
| `pydantic_agent.py` | PydanticAI | `Agent`, `FunctionModel`, and tool execution |
| `openai_agent.py` | OpenAI Agents SDK | `Agent`, `Runner`, and `function_tool` |
| `agno_agent.py` | Agno | `Agent`, custom `Model`, and its native tool loop |

All six understand `add 17 25` and return `42` **after their framework executes the
addition tool**. Other integers, negative numbers, zero, repeated runs, invalid
commands, and operand limits are tested. These are intentionally deterministic
test agents: the local model chooses a tool and returns its result. They do not
call OpenAI or another hosted LLM, and they do not test language-model quality.

Third-party tracing/telemetry is disabled in the lab process. Offline tests deny
external sockets. Purview calls in live mode go only to the configured Microsoft
identity tenant and the fixed public-cloud Microsoft Graph endpoint.

```powershell
.\.venv\Scripts\python.exe -m purview_lab
```

This command runs all six frameworks through the real Purview SDK with simulated
HTTP responses and writes `artifacts\offline-connection-report.json`. It is always
offline; it never silently switches to live credentials.

## What your administrator must prepare

The notebook includes these steps too. A tenant ID alone cannot authorize a connection.

1. Use an organizational Microsoft 365 tenant with the required Purview entitlement
   and pay-as-you-go billing. Microsoft's SDK guide lists E5 and pay-as-you-go
   prerequisites; confirm current licensing and feature availability with your admin.
2. Register an application in **Microsoft Entra ID**, normally single-tenant.
   For browser sign-in, add the **Mobile and desktop applications** platform with
   redirect URI **`http://localhost`**. For device-code sign-in, also enable
   **Allow public client flows**.
   The Python SDK chooses an available localhost callback port automatically.
   Do not pass the portless portal URI as an explicit SDK `redirect_uri` value.
3. Add the three Microsoft Graph delegated permissions listed in
   [Required permissions](#required-permissions), and have your administrator grant consent.
4. Enable Purview Audit and the appropriate DSPM for AI collection policy for the
   test user and registered application. A collection policy determines whether
   prompts/responses are retained. Configure a test-scoped DLP rule separately if
   you want to verify blocking. Current Microsoft guidance requires
   `New-DlpComplianceRule` for Entra-registered application DLP policies.
5. Complete the [tenant-details box](#fill-in-your-tenant-details) using the portal
   locations listed above. Keep all IDs in the same intended tenant.

The simplest setup shares **one Entra registration across six logical agents**.
Each agent has a distinct name and agent metadata. Purview may group them under
the same application ID. The notebook also supports a different client ID for
each framework if you want **six separate application identities**. Each of those
registrations needs its own configuration, consent, and policy scope.

The notebook does **not** provision app registrations, grant consent, configure
billing, or change tenant-wide policies. Those are administrator prerequisites,
not steps that an SDK can bypass.

## Integration and verification boundaries

This uses the actual Microsoft **`agent-framework-purview`** Python SDK and its
Microsoft Graph `dataSecurityAndGovernance` APIs. It is not the Azure Purview
catalog/Atlas SDK, and it does not need a `*.purview.azure.com` account endpoint.

Each protected invocation:

1. Computes protection scopes for the explicit user and actual Entra application ID.
2. Evaluates the prompt before running the agent.
3. Runs the framework's local tool agent, then evaluates its response before returning it.

The most restrictive matching scope wins. Scope-level and content-level blocks
are enforced. The original ETag, including quotes, is forwarded. A `modified` scope
state refreshes the cache without discarding the returned content decision. Any
new scope-level block is enforced; an upgrade from offline to inline evaluation
requires an inline recheck before the agent runs or output is returned.
A shared conversation ID and sequence numbers
0/1 correlate each prompt/response; each HTTP call has a separate request ID.

**No silent success:** HTTP/authentication/billing errors, invalid JSON, missing
ETags, processing errors, unsupported actions/modes, and a missing inline verdict
fail closed. All SDK operations are awaited; no fire-and-forget task is mistaken
for a connection.

- **No applicable policy:** only content-activity metadata is logged, and the result
  is labeled `metadataLoggedOnly`. It is not claimed as DLP protection or prompt retention.
- **Offline policy evaluation:** HTTP 202/204 is labeled `acceptedWithoutVerdict`,
  not an inline allow decision. Inline policies cannot proceed on those statuses.
- **Live API verification:** proves an authenticated round-trip to Microsoft's APIs.
- **Portal ingestion:** must be checked separately in Purview, with the recorded
  conversation/request IDs. Reports and policy propagation can take time.
- **DLP blocking:** needs a deliberately configured test policy; a successful safe
  prompt is not proof that a sensitive prompt would be blocked.

These agents have one local, non-networked tool. Protection surrounds their public
invocation boundary. If you add external tools, retrieval, intermediate model
calls, streaming, or agent-to-agent handoffs, apply equivalent checks at those
additional boundaries. This lab is not a production-wide compliance certification.

### Preview SDK compatibility

The SDK is preview, and its standalone client/models are currently in internal
modules. `src\purview_lab\sdk.py` isolates that access and checks the exact SDK
version, **`1.0.0b260730`**. Do not upgrade it without rerunning the contract tests.

The adapter addresses observed differences between this release and the documented
Graph contract: internal serializer `type` and routing fields are removed,
datetime values are serialized explicitly, quoted ETags are preserved, and the
documented bodyless HTTP 204 response is handled without inventing a verdict.
The SDK still performs authentication, request routing, HTTP submission, and response
parsing. Tests use its real client with `httpx.MockTransport`, not a fake SDK.

## Repeat the tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q --disable-socket --allow-hosts=127.0.0.1,::1
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
```

Tests cover all six native frameworks, exact SDK payloads/authentication headers,
prompt and response blocking for every framework, permission/billing/throttling
failures, stale policy state, asynchronous acknowledgements, metadata-only mode,
resource cleanup, report completeness, and full notebook execution in a real kernel.
Generated evidence is under `artifacts`: `test-results.xml`, `coverage.json`,
`executed-offline.ipynb`, and `notebook-validation.json`, as well as connection reports.

Live tests are **skipped by default**, not counted as passed. After administrator
setup, the notebook is the recommended live test path. For noninteractive CI,
use a confidential app with administrator-consented Microsoft Graph application
permissions appropriate to the target user scope (the SDK guidance lists
`ProtectionScopes.Compute.All`, `Content.Process.All`, and `ContentActivity.Write`).
The Graph references also list narrower `.User` permissions; use only permissions
your administrator has authorized for the scenario.

Set `PURVIEW_TENANT_ID`, `PURVIEW_CLIENT_ID`, `PURVIEW_USER_ID`, and
`PURVIEW_CLIENT_SECRET` securely in the process environment, then explicitly opt in:

```powershell
$env:PURVIEW_LIVE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests\live -q
Remove-Item Env:\PURVIEW_LIVE_TESTS
Remove-Item Env:\PURVIEW_CLIENT_SECRET
```

Do not hard-code secrets or paste them into notebook cells. The interactive
client-secret option uses `getpass`, keeps credentials in memory, and closes them
in the notebook's cleanup cell. Access tokens and raw HTTP bodies are never saved
in connection reports. Reports include the configured tenant, app, and user object IDs
to identify the verification target. Clear notebook outputs before sharing, and shut down the
kernel when finished. `.env*`, generated reports, and notebook checkpoints are ignored.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Wrong Python / ARM64 wheel or compiler errors | Select the x64 `.venv` kernel installed by `setup.ps1`. |
| `AADSTS50011` | Register `http://localhost` as a mobile/desktop redirect URI. |
| Sign-in blocked | Check tenant, public-client settings, Conditional Access, and admin consent. Device code is an explicit option, not a bypass. |
| 401 / 403 | Check sign-in, permission type, admin consent, app ID, and target user Object ID. |
| 402 | Check Purview licensing, billing linkage, and feature enablement with an administrator. |
| 429 | Wait for the indicated retry interval and rerun. The lab does not automatically duplicate writes. |
| HTTP success but no policy | Configure collection/DLP policies for the app and user; wait for propagation. |
| HTTP success but no portal record | Check Audit/collection settings and ingestion delay; HTTP success alone is not portal proof. |
| Safe sample is blocked | Review your test policy scope; do not disable organizational protections to force a green check. |
| Missing inline decision / unknown action | Treat as unverified; investigate the policy/API/SDK version rather than allowing content. |

## Microsoft references

- [Purview SDK integration and prerequisites](https://learn.microsoft.com/agent-framework/integrations/by-component/middleware/purview?pivots=programming-language-python)
- [Use Microsoft Purview APIs in Microsoft Graph](https://learn.microsoft.com/purview/developer/use-the-api)
- [Compute protection scopes and permissions](https://learn.microsoft.com/graph/api/userprotectionscopecontainer-compute?view=graph-rest-1.0)
- [Process content and permissions](https://learn.microsoft.com/graph/api/userdatasecurityandgovernance-processcontent?view=graph-rest-1.0)
- [Content activity resource schema](https://learn.microsoft.com/graph/api/resources/contentactivity?view=graph-rest-1.0)
- [Configure Purview for custom AI apps](https://learn.microsoft.com/purview/developer/configurepurview)
- [Test Purview portal ingestion](https://learn.microsoft.com/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk)
