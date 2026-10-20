<#
.SYNOPSIS
    Bring up flutter-agent on a machine that does not have it yet: environment,
    source registration, and the first index.

.DESCRIPTION
    `install.ps1` builds the environment. This script adds the part that is
    specific to a second machine: the knowledge base arrives with the clone, but
    `~/.flutter-agent/` does not, so the source roots have to be registered at
    THEIR paths here and the index rebuilt from scratch.

    Projects come from -Projects, or from scanning -Scan for pubspec.yaml.
    Registration is idempotent, so re-running this is safe.

.EXAMPLE
    .\setup.ps1 -Projects D:\work\corereusablepackage,D:\work\my_app
    .\setup.ps1 -Scan D:\work -Depth 3        # discover projects under D:\work
    .\setup.ps1 -Scan D:\work -DryRun         # list what it would register
    .\setup.ps1 -Cpu -SkipInstall             # register and index only
#>
[CmdletBinding()]
param(
    [string[]]$Projects = @(),
    [string[]]$Scan = @(),
    [int]$Depth = 2,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$SkipInstall,
    [switch]$SkipIndex,
    [switch]$SkipRegister,
    [switch]$Cpu,
    [switch]$OwnVenv,
    [string]$CudaChannel = "cu128",
    [string]$Python = "python",
    [string]$ReuseVenv = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "==> flutter-agent setup" -ForegroundColor Cyan
Write-Host "    checkout: $root"

# --- 1. this must be a checkout, not an unpacked copy -----------------------
# knowledge_home() prefers the repo's own knowledge/ directory; without it every
# lesson recorded here would land in ~/.flutter-agent/knowledge, outside git.
if (-not (Test-Path (Join-Path $root "knowledge\lessons"))) {
    throw "No knowledge\lessons under $root - this is not a flutter-agent checkout."
}
if (-not (Test-Path (Join-Path $root ".git"))) {
    Write-Warning "No .git here. Lessons recorded on this machine will not be version-controlled."
}

# --- 2. environment ---------------------------------------------------------
if ($SkipInstall) {
    Write-Host "==> skipping install" -ForegroundColor DarkGray
}
else {
    # Indexing happens after registration, below, so never inside the installer.
    $installArgs = @{ SkipIndex = $true }
    if ($Cpu) { $installArgs.Cpu = $true }
    if ($OwnVenv) { $installArgs.OwnVenv = $true }
    if ($SkipRegister) { $installArgs.SkipRegister = $true }
    if ($CudaChannel) { $installArgs.CudaChannel = $CudaChannel }
    if ($Python) { $installArgs.Python = $Python }
    if ($ReuseVenv) { $installArgs.ReuseVenv = $ReuseVenv }
    # install.ps1 runs with ErrorActionPreference Stop and throws on real
    # failures; $LASTEXITCODE after it belongs to whatever native command it ran
    # last, so it is not a verdict on the install.
    & (Join-Path $root "install.ps1") @installArgs
}

# --- 3. find the CLI the install just produced ------------------------------
function Resolve-Cli {
    $candidates = @()
    if ($ReuseVenv) { $candidates += (Join-Path (Split-Path $ReuseVenv -Parent) "flutter-agent.exe") }
    $candidates += @(
        (Join-Path $root ".venv\Scripts\flutter-agent.exe"),
        (Join-Path (Split-Path $root -Parent) "local-mcp\.venv\Scripts\flutter-agent.exe"),
        (Join-Path $env:USERPROFILE "Desktop\local-mcp\.venv\Scripts\flutter-agent.exe")
    )
    $onPath = Get-Command flutter-agent -ErrorAction SilentlyContinue
    if ($null -ne $onPath) { $candidates += $onPath.Source }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        try { & $candidate --version | Out-Null } catch { continue }
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$cli = Resolve-Cli
if ($null -eq $cli) {
    throw "Could not find a working flutter-agent CLI. Run .\install.ps1 first, or pass -ReuseVenv <venv>\Scripts\python.exe."
}
Write-Host "==> CLI: $cli" -ForegroundColor Green
& $cli doctor

# --- 4. collect project roots ----------------------------------------------
# A pubspec under any of these is plugin scaffolding, build output, an example
# app or the agent's own test fixture - never a source root worth indexing.
# Matching whole path segments (not a substring) keeps a project named
# "webstore" or "ios_tools" from being thrown away.
$skipSegments = @(
    "build", ".dart_tool", ".git", ".symlinks", "ephemeral", "android", "ios",
    "windows", "macos", "linux", "web", "node_modules", "example", "fixtures"
)
$separators = @([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)

$found = New-Object System.Collections.Generic.List[string]
foreach ($path in $Projects) {
    if (Test-Path $path) { $found.Add((Resolve-Path $path).Path) }
    else { Write-Warning "No such path, skipped: $path" }
}
foreach ($dir in $Scan) {
    if (-not (Test-Path $dir)) { Write-Warning "No such scan root, skipped: $dir"; continue }
    Write-Host "==> scanning $dir (depth $Depth)" -ForegroundColor Cyan
    $hits = Get-ChildItem -Path $dir -Filter pubspec.yaml -File -Recurse -Depth $Depth -ErrorAction SilentlyContinue
    foreach ($hit in $hits) {
        $owner = $hit.Directory.FullName
        $excluded = $false
        foreach ($segment in $owner.Split($separators)) {
            if ($skipSegments -contains $segment) { $excluded = $true; break }
        }
        if ($excluded) { continue }
        if (-not (Test-Path (Join-Path $owner "lib"))) { continue }
        $found.Add($owner)
    }
}

# Case-insensitive dedupe, shared packages first: the component catalog is read
# from the package, so it is the useful half of the corpus to have in place.
$roots = @($found | Sort-Object -Unique -Property { $_.ToLowerInvariant() })
$roots = @($roots | Sort-Object -Property @{
    Expression = {
        $isPackage = (Test-Path (Join-Path $_ "lib\src")) -and -not (Test-Path (Join-Path $_ "lib\features"))
        if ($isPackage) { 0 } else { 1 }
    }
}, @{ Expression = { $_ } })

if ($roots.Count -eq 0) {
    Write-Host ""
    Write-Warning "No projects to register. Pass -Projects <path>[,<path>] or -Scan <dir>."
    Write-Host "Already registered:"
    & $cli sources list
    return
}

Write-Host ""
Write-Host "Projects to register ($($roots.Count)):" -ForegroundColor Cyan
foreach ($r in $roots) { Write-Host "    $r" }

# A wide scan finds archives, backups and "- copy" folders as readily as live
# work, and every stale copy it registers dilutes retrieval: `pattern` starts
# answering with a precedent you abandoned a year ago.
if ($roots.Count -gt 10) {
    Write-Warning "$($roots.Count) projects is a lot. Old copies and archived versions weaken retrieval - consider -Projects with just the ones you work in."
}

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run - nothing registered." -ForegroundColor Yellow
    return
}
if ($Scan.Count -gt 0 -and -not $Yes) {
    $answer = Read-Host "Register these? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Write-Host "Aborted."; return }
}

# --- 5. register ------------------------------------------------------------
$ok = 0
foreach ($r in $roots) {
    & $cli sources add $r
    if ($LASTEXITCODE -eq 0) { $ok++ } else { Write-Warning "Could not register $r" }
}
Write-Host "==> registered $ok of $($roots.Count)" -ForegroundColor Green

# --- 6. index ---------------------------------------------------------------
if ($SkipIndex) {
    Write-Host "==> skipping index. Run '$cli index' before using the agent." -ForegroundColor Yellow
}
else {
    Write-Host "==> indexing (first run also downloads the ~90 MB embedding model)" -ForegroundColor Cyan
    & $cli index
    if ($LASTEXITCODE -ne 0) { throw "indexing failed" }
    & $cli status
}

# --- 7. what git does not carry --------------------------------------------
if (-not (Test-Path (Join-Path $env:USERPROFILE ".claude\CLAUDE.md"))) {
    Write-Host ""
    Write-Warning "~\.claude\CLAUDE.md is missing. This agent supplies precedent; that file supplies the house rules - copy it from your other machine."
}

Write-Host ""
Write-Host "Done. Lessons live in knowledge\lessons\lessons.jsonl - pull before a session, push after one." -ForegroundColor Green
