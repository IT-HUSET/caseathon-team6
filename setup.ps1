# One-shot setup for Policy Insight on Windows. Run via setup.cmd (double-click) or:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Installs uv (which fetches Python 3.13 itself) and the Claude CLI if missing, then syncs dependencies.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') +
        ";$env:USERPROFILE\.local\bin"
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Refresh-Path
if (-not (Have uv)) {
    Write-Host '==> Installing uv' -ForegroundColor Cyan
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
}
if (-not (Have claude)) {
    Write-Host '==> Installing Claude CLI' -ForegroundColor Cyan
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
    Refresh-Path
}

Write-Host '==> Installing Python 3.13 and project dependencies' -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Retrying with --native-tls (corporate proxy?)' -ForegroundColor Yellow
    uv sync --native-tls
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
    $env:UV_NATIVE_TLS = '1'
    [Environment]::SetEnvironmentVariable('UV_NATIVE_TLS', '1', 'User')
}

Write-Host '==> Checking Claude login (a short test call)' -ForegroundColor Cyan
$reply = 'Reply with OK' | claude -p 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Claude is not logged in yet. Run 'claude' in a terminal, choose your Claude Pro account, then re-run this script." -ForegroundColor Yellow
    exit 1
}

Write-Host @'

Setup complete. Next steps (in this folder):
  uv run python -m ingest --limit 2      # quick smoke test (uses your Claude quota)
  uv run python -m ingest                # full ingest, ~10-15 min for 19 docs
  uv run streamlit run app.py            # launch the UI
'@ -ForegroundColor Green
