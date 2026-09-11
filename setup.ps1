[CmdletBinding()]
param(
    [string]$BootstrapPython = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$EnvironmentPython = Join-Path $Root ".venv\Scripts\python.exe"

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE. Resolve the error above and rerun setup."
    }
}

Push-Location $Root
try {
    if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
        if (Test-Path -LiteralPath (Join-Path $Root ".venv")) {
            throw "An incomplete .venv already exists. Rename it before rerunning; setup will not overwrite it."
        }
        $UvTarget = Join-Path $Root ".tools\bootstrap"
        if (-not (Test-Path -LiteralPath (Join-Path $UvTarget "uv\__init__.py"))) {
            Invoke-Checked -Executable $BootstrapPython -Arguments @(
                "-m", "pip", "install", "--only-binary=:all:", "--quiet",
                "--target", $UvTarget, "uv"
            )
        }
        $PreviousPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = $UvTarget
            Invoke-Checked -Executable $BootstrapPython -Arguments @(
                "-m", "uv", "python", "install", "--install-dir", ".python",
                "--no-bin", "cpython-3.12.10-windows-x86_64-none"
            )
            Invoke-Checked -Executable $BootstrapPython -Arguments @(
                "-m", "uv", "venv", "--python",
                ".python\cpython-3.12.10-windows-x86_64-none\python.exe", ".venv"
            )
        }
        finally {
            $env:PYTHONPATH = $PreviousPythonPath
        }
    }

    Invoke-Checked -Executable $EnvironmentPython -Arguments @(
        "-c",
        "import sys, sysconfig; assert sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64', 'Use an x64 Python 3.12 environment; do not use the ARM64 interpreter.'"
    )
    Invoke-Checked -Executable $EnvironmentPython -Arguments @("-m", "ensurepip", "--upgrade")
    Invoke-Checked -Executable $EnvironmentPython -Arguments @(
        "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
        "--only-binary=:all:", "--constraint", "requirements-lock.txt", "--editable", ".[notebook,test]"
    )
    Invoke-Checked -Executable $EnvironmentPython -Arguments @("-m", "pip", "check")
    Invoke-Checked -Executable $EnvironmentPython -Arguments @(
        "-m", "ipykernel", "install", "--user", "--name", "six-agents-purview",
        "--display-name", "Python (six agents + Purview)"
    )
    if (-not $SkipTests) {
        Invoke-Checked -Executable $EnvironmentPython -Arguments @(
            "-m", "pytest", "-q", "-m", "not live", "--disable-socket", "--allow-hosts=127.0.0.1,::1"
        )
    }
    Write-Host "Ready: open connect_agents_to_purview.ipynb and select Python (six agents + Purview)."
    Write-Host "No live Microsoft tenant connection has been attempted by setup."
}
finally {
    Pop-Location
}
