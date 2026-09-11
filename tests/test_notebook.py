import json
import os
import sys
from pathlib import Path

import nbformat
import pytest
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "connect_agents_to_purview.ipynb"

NETWORK_GUARD = """
import ipaddress
import socket

_original_getaddrinfo = socket.getaddrinfo
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _require_loopback(host):
    if host in ("localhost", b"localhost"):
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise RuntimeError("Notebook test blocked external network access.") from None
    if not address.is_loopback:
        raise RuntimeError("Notebook test blocked external network access.")

def _local_getaddrinfo(host, *args, **kwargs):
    _require_loopback(host)
    return _original_getaddrinfo(host, *args, **kwargs)

def _local_connect(self, address):
    _require_loopback(address[0])
    return _original_connect(self, address)

def _local_connect_ex(self, address):
    _require_loopback(address[0])
    return _original_connect_ex(self, address)

socket.getaddrinfo = _local_getaddrinfo
socket.socket.connect = _local_connect
socket.socket.connect_ex = _local_connect_ex
"""

FAILED_LIVE_AUTH = """
from azure.core.exceptions import ClientAuthenticationError
import purview_lab.live

_test_ids = iter([
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
])
input = lambda prompt: next(_test_ids)

class RejectedTestCredential:
    def __init__(self, config, **kwargs):
        pass
    async def token(self):
        raise ClientAuthenticationError("EXPECTED_TEST_AUTH_REJECTION")
    async def close(self):
        pass

purview_lab.live.TenantCredential = RejectedTestCredential
"""


def notebook_client(tmp_path, notebook):
    kernels = tmp_path / "kernels"
    spec_dir = kernels / "purview-lab-test"
    spec_dir.mkdir(parents=True)
    (spec_dir / "kernel.json").write_text(
        json.dumps(
            {
                "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                "display_name": "Isolated Purview notebook test",
                "language": "python",
            }
        ),
        encoding="utf-8",
    )
    manager = KernelManager(
        ip="127.0.0.1",
        kernel_name="purview-lab-test",
        kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]),
    )
    client = NotebookClient(
        notebook,
        km=manager,
        kernel_name="purview-lab-test",
        timeout=120,
        resources={"metadata": {"path": str(ROOT)}},
    )
    return client, manager


def test_notebook_is_valid_clean_and_contains_six_explicit_connection_steps():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    assert len(notebook.cells) >= 25
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert all(cell.execution_count is None and not cell.outputs for cell in code_cells)
    for agent_id in ("microsoft", "langgraph", "autogen", "pydantic", "openai", "agno"):
        assert (
            sum(f'reports["{agent_id}"] = await check_agent' in cell.source for cell in code_cells)
            == 1
        )


@pytest.mark.notebook
def test_entire_notebook_executes_offline_with_no_external_network(tmp_path):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    notebook.cells.insert(0, nbformat.v4.new_code_cell(NETWORK_GUARD))
    client, manager = notebook_client(tmp_path, notebook)
    report_path = tmp_path / "offline-notebook-report.json"
    environment = {
        **os.environ,
        "PURVIEW_LAB_MODE": "offline",
        "PURVIEW_LAB_REPORT_PATH": str(report_path),
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
        "OTEL_SDK_DISABLED": "true",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        executed = client.execute(env=environment)
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
            manager.cleanup_resources()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["reported_agents"] == 6
    assert payload["offline_simulation_passed"]
    assert not payload["live_tenant_verified"]
    assert not payload["portal_ingestion_verified"]
    assert all(agent["answer"] == "42" for agent in payload["agents"])
    assert all(agent["status"] == "OFFLINE_SIMULATED" for agent in payload["agents"])
    assert all(len(agent["receipts"]) == 3 for agent in payload["agents"])
    assert all(
        output.output_type != "error"
        for cell in executed.cells
        if cell.cell_type == "code"
        for output in cell.outputs
    )
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    nbformat.write(executed, artifacts / "executed-offline.ipynb")
    (artifacts / "notebook-validation.json").write_text(
        json.dumps(
            {
                "notebook": NOTEBOOK.name,
                "mode": "offline",
                "executed_code_cells": sum(cell.cell_type == "code" for cell in executed.cells),
                "six_agents_verified_offline": True,
                "live_tenant_verified": False,
                "external_network_blocked": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.notebook
def test_live_notebook_auth_failure_cannot_create_a_success_report(tmp_path):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    notebook.cells.insert(0, nbformat.v4.new_code_cell(NETWORK_GUARD + FAILED_LIVE_AUTH))
    client, manager = notebook_client(tmp_path, notebook)
    report_path = tmp_path / "must-not-exist.json"
    environment = {
        **os.environ,
        "PURVIEW_LAB_MODE": "live",
        "PURVIEW_LAB_REPORT_PATH": str(report_path),
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
        "OTEL_SDK_DISABLED": "true",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        with pytest.raises(CellExecutionError, match="EXPECTED_TEST_AUTH_REJECTION"):
            client.execute(env=environment)
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
            manager.cleanup_resources()
    assert not report_path.exists()
