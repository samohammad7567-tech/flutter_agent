<#
.SYNOPSIS
    One-shot installer for flutter-agent: Python environment, dependencies,
    source registration, first index, and registration with Claude Code.

.DESCRIPTION
    By default this REUSES an existing compatible virtualenv (such as the one
    docs-mcp created) rather than building its own, because the CUDA PyTorch
    wheel is a ~2.8 GB download that unpacks to roughly 4.9 GB. Pass -OwnVenv to
    build a private environment instead.

.EXAMPLE
    .\install.ps1                      # reuse a found venv, install, register
    .\install.ps1 -OwnVenv             # build a private .venv (large download)
    .\install.ps1 -Cpu -OwnVenv        # private venv, CPU-only PyTorch
    .\install.ps1 -SkipRegister        # install only
#>
[CmdletBinding()]
param(
    [switch]$Cpu,
    [switch]$OwnVenv,
    [switch]$SkipRegister,
    [switch]$SkipIndex,
    [string]$CudaChannel = "cu128",
    [string]$Python = "python",
    [string]$ReuseVenv = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"

Write-Host "==> flutter-agent installer" -ForegroundColor Cyan
Write-Host "    target: $root"

function Test-Venv([string]$candidate) {
    if (-not (Test-Path $candidate)) { return $false }
    & $candidate -c "import torch, faiss, sentence_transformers, mcp" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# --- pick an interpreter ----------------------------------------------------
if (-not $OwnVenv) {
    $candidates = @()
    if ($ReuseVenv) { $candidates += $ReuseVenv }
    $candidates += @(
        (Join-Path (Split-Path $root -Parent) "local-mcp\.venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE "Desktop\local-mcp\.venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Venv $candidate) {
            $py = $candidate
            Write-Host "==> reusing existing environment" -ForegroundColor Green
            Write-Host "    $py"
            Write-Host "    (it already has torch, faiss, sentence-transformers and mcp)"
            break
        }
    }
}

if ($py -eq (Join-Path $venv "Scripts\python.exe")) {
    if (-not (Test-Path $py)) {
        Write-Host "==> creating virtualenv" -ForegroundColor Cyan
        Write-Host "    note: the CUDA PyTorch wheel is a ~2.8 GB download." -ForegroundColor Yellow
        & $Python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "failed to create virtualenv with '$Python'" }
    }
    & $py -m pip install --upgrade pip setuptools wheel --quiet

    $already = (& $py -c "import torch,sys;print(torch.version.cuda or 'cpu')" 2>$null)
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==> PyTorch already installed (CUDA: $already)" -ForegroundColor Green
    }
    else {
        $useCuda = -not $Cpu
        if ($useCuda -and $null -eq (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
            Write-Warning "nvidia-smi not found - installing the CPU-only PyTorch wheel."
            $useCuda = $false
        }
        $channel = if ($useCuda) { $CudaChannel } else { "cpu" }
        Write-Host "==> installing PyTorch ($channel)" -ForegroundColor Cyan
        & $py -m pip install torch --index-url "https://download.pytorch.org/whl/$channel"
        if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed" }
    }
}

# --- flutter-agent itself ---------------------------------------------------
Write-Host "==> installing flutter-agent" -ForegroundColor Cyan
& $py -m pip install -e "$root[dev]"
if ($LASTEXITCODE -ne 0) { throw "flutter-agent install failed" }

Write-Host "==> verifying GPU" -ForegroundColor Cyan
& $py -m flutter_agent.cli doctor

# --- register source roots --------------------------------------------------
$registered = (& $py -m flutter_agent.cli sources list)
if ($registered -match "No source roots registered") {
    Write-Host ""
    Write-Host "No Flutter projects registered yet. Add them with:" -ForegroundColor Yellow
    Write-Host "  $py -m flutter_agent.cli sources add <path-to-flutter-project>"
    Write-Host "Register your shared package first, then each app."
}
elseif (-not $SkipIndex) {
    Write-Host "==> indexing registered sources" -ForegroundColor Cyan
    & $py -m flutter_agent.cli index
}

# --- register with Claude Code ---------------------------------------------
if (-not $SkipRegister) {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($null -eq $claude) {
        Write-Warning "The 'claude' CLI was not found. Register manually:"
        Write-Host "  claude mcp add --scope user flutter-agent -- `"$py`" -m flutter_agent.server"
    }
    else {
        Write-Host "==> registering with Claude Code (user scope)" -ForegroundColor Cyan
        & claude mcp remove --scope user flutter-agent 2>$null | Out-Null
        & claude mcp add --scope user flutter-agent -- $py -m flutter_agent.server
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    registered. Restart Claude Code, then run /mcp." -ForegroundColor Green
        }
        else {
            Write-Warning "Registration failed; add it manually with the command above."
        }
    }
}

Write-Host ""
Write-Host "Done. Next:" -ForegroundColor Green
Write-Host "  $py -m flutter_agent.cli status"
Write-Host "  $py -m flutter_agent.cli pattern `"pagination`""
Write-Host "  $py -m flutter_agent.cli check <path-to-a-feature>"
