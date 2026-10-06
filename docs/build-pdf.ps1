<#
.SYNOPSIS
    Render the flutter-agent manuals (English + Arabic) to PDF.

.DESCRIPTION
    Uses Edge/Chrome in headless mode. A Chromium engine is used deliberately:
    it is the only thing on a stock Windows box that shapes Arabic correctly
    (connected letters, right-to-left order, LTR code spans left intact).
    Naive PDF libraries render Arabic as disconnected, reversed glyphs.

.EXAMPLE
    .\build-pdf.ps1
#>
[CmdletBinding()]
param(
    [string]$Browser = ""
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

if (-not $Browser) {
    $candidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )
    $Browser = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Browser) { throw "No Edge or Chrome found. Pass -Browser <path to exe>." }

Write-Host "==> renderer: $Browser" -ForegroundColor Cyan

$jobs = @(
    @{ Html = "guide-en.html";    Pdf = "flutter-agent-guide-en.pdf";    Label = "Manual (English)" },
    @{ Html = "guide-ar.html";    Pdf = "flutter-agent-guide-ar.pdf";    Label = "Manual (Arabic)"  },
    @{ Html = "training-ar.html"; Pdf = "flutter-agent-training-ar.pdf"; Label = "Training (Arabic)" }
)

foreach ($job in $jobs) {
    $src = Join-Path $here $job.Html
    $out = Join-Path $here $job.Pdf
    if (-not (Test-Path $src)) { throw "missing source: $src" }

    Write-Host "==> $($job.Label): $($job.Html) -> $($job.Pdf)" -ForegroundColor Cyan
    if (Test-Path $out) { Remove-Item $out -Force }

    # An isolated --user-data-dir is required: if the user already has Edge open,
    # the headless process attaches to that profile and exits without rendering.
    # Start-Process is used rather than the call operator so stderr is not
    # redirected - in PowerShell 5.1 that would wrap Edge's harmless startup
    # chatter in ErrorRecords and trip $ErrorActionPreference = "Stop".
    $browserArgs = @(
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--user-data-dir=$env:TEMP\flutter-agent-pdf",
        "--print-to-pdf=$out",
        ("file:///" + $src.Replace("\", "/"))
    )
    $proc = Start-Process -FilePath $Browser -ArgumentList $browserArgs -NoNewWindow -Wait -PassThru

    if ($proc.ExitCode -ne 0) { throw "$($job.Label): renderer exited $($proc.ExitCode)" }
    if (-not (Test-Path $out)) { throw "render failed for $($job.Html)" }
    $kb = [math]::Round((Get-Item $out).Length / 1KB, 1)
    Write-Host "    wrote $($job.Pdf)  ($kb KB)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done. PDFs are in $here" -ForegroundColor Green
