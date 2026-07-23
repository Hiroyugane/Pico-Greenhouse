<#
.SYNOPSIS
    Build the Pi Greenhouse custom MicroPython firmware (.uf2) offline.

.DESCRIPTION
    Punch item P1 of docs/notes/firmware-freeze-versioning-plan.md, at the
    "minimum scope" the council chose (section 5.4): a hand-run script. No CI,
    no tag-triggered artifact build, no auto-flash. Flashing stays a deliberate
    human act with a Pico in BOOTSEL mode.

    What it does, in order:
      1. Preflight - every required tool, named with an install hint if absent.
      2. Resolve the MicroPython ref. First run (or -Repin) queries upstream
         for the newest FINAL release tag and writes it to tools/micropython.lock;
         every later run reuses the lock, so builds are reproducible.
      3. Clone/fetch that ref into a sibling checkout and fetch its submodules.
      4. Build mpy-cross FROM THAT SAME TREE. This is the load-bearing step:
         the .mpy files an OTA payload ships must be compiled by the mpy-cross
         that matches the firmware, or the payload applies and then fails every
         import on a board with no REPL (plan 5.2).
      5. Generate the frozen fw_info.py (firmware version + .mpy ABI + source).
      6. Run the RP2 make with tools/freeze_manifest.py as FROZEN_MANIFEST.
      7. Drop build/firmware.uf2, archive it as build/firmware-<version>.uf2 as
         the rollback for the NEXT build, and write build/firmware-build.json.

    BEFORE FLASHING (plan section 3.1, non-negotiable):
      - The device must have booted at least once on its current firmware with
        the version line in /boot.log. Once the new .uf2 is written that line
        is the only record of what it was running.
      - Keep the previous build/firmware-<version>.uf2. BOOTSEL + drag-drop is
        the only recovery path for a bad frozen build.

.PARAMETER MicroPythonDir
    Where the MicroPython checkout lives. Default: a sibling of the repo root.
    Never vendored into this repo - it would dwarf it.

.PARAMETER Board
    RP2 board name. Default RPI_PICO.

.PARAMETER Ref
    Build this exact tag/commit instead of the locked one. Does not rewrite the
    lockfile; use -Repin for that.

.PARAMETER Repin
    Re-resolve the newest final upstream release and rewrite the lockfile.

.PARAMETER Tier1Only
    Restrict the freeze to the Tier-1 set. Tier-2 is frozen by default since
    2026-07-23 (operator decision after P0.5 measured the heap 97.5% full).

.PARAMETER FreezeOnly
    Comma-separated module filenames to freeze instead of the whole tier. The
    P0.5 loop ("freeze the coldest first, re-measure") uses this.

.PARAMETER Jobs
    Parallel make jobs. Default: processor count.

.EXAMPLE
    .\tools\build_firmware.ps1
    .\tools\build_firmware.ps1 -Repin
    .\tools\build_firmware.ps1 -FreezeOnly 'sdcard.py,ds3231.py,ssd1306.py'
#>
[CmdletBinding()]
param(
    [string]$MicroPythonDir,
    [string]$Board = 'RPI_PICO',
    [string]$Ref,
    [switch]$Repin,
    [switch]$Tier1Only,
    [string]$FreezeOnly,
    [int]$Jobs = 0
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LockFile = Join-Path $PSScriptRoot 'micropython.lock'
$ManifestFile = Join-Path $PSScriptRoot 'freeze_manifest.py'
$BuildDir = Join-Path $RepoRoot 'build'
$FrozenDir = Join-Path $BuildDir 'frozen'
$UpstreamUrl = 'https://github.com/micropython/micropython'
$SourceName = 'upstream'

if (-not $MicroPythonDir) {
    $MicroPythonDir = Join-Path (Split-Path -Parent $RepoRoot) 'micropython'
}
if ($Jobs -le 0) {
    $Jobs = [int]$env:NUMBER_OF_PROCESSORS
    if ($Jobs -le 0) { $Jobs = 4 }
}

function Write-Step($message) {
    Write-Host ''
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Get-PythonExe {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    throw 'No Python found (.venv\Scripts\python.exe or python on PATH).'
}

function Assert-Toolchain {
    # Fail on ALL missing tools at once. Discovering them one build at a time
    # is the difference between one install session and four.
    $required = @(
        @{ Name = 'git';             Hint = 'winget install --id Git.Git' },
        @{ Name = 'cmake';           Hint = 'winget install --id Kitware.CMake  (need >= 3.12)' },
        @{ Name = 'make';            Hint = 'MSYS2: pacman -S make   - or scoop install make' },
        @{ Name = 'arm-none-eabi-gcc'; Hint = 'winget install --id Arm.GnuArmEmbeddedToolchain  (the real install cost)' }
    )
    $missing = @()
    foreach ($tool in $required) {
        if (-not (Get-Command $tool.Name -ErrorAction SilentlyContinue)) {
            $missing += ('  {0,-20} {1}' -f $tool.Name, $tool.Hint)
        }
    }
    if ($missing.Count -gt 0) {
        Write-Host 'Missing build tools:' -ForegroundColor Red
        $missing | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        Write-Host ''
        Write-Host 'See docs/hardware/firmware-build-runbook.md for the one-time toolchain setup.'
        throw 'Toolchain incomplete - nothing was built.'
    }
}

function Resolve-NewestFinalTag {
    # "Newest final release" per the council (plan 3.1): vMAJOR.MINOR[.PATCH]
    # only. Every pre-release (-rc, -preview, -beta) is rejected, and so is
    # "latest master" - an unpinned firmware is an unreproducible firmware.
    Write-Host "querying $UpstreamUrl for release tags ..."
    $lines = & git ls-remote --tags --refs $UpstreamUrl
    if ($LASTEXITCODE -ne 0) { throw "git ls-remote failed against $UpstreamUrl" }
    $best = $null
    $bestVersion = $null
    foreach ($line in $lines) {
        $parts = $line -split "`t"
        if ($parts.Count -lt 2) { continue }
        $tag = $parts[1] -replace '^refs/tags/', ''
        if ($tag -notmatch '^v\d+(\.\d+){1,2}$') { continue }
        $version = [version]($tag.Substring(1))
        if (($null -eq $bestVersion) -or ($version -gt $bestVersion)) {
            $bestVersion = $version
            $best = $tag
        }
    }
    if (-not $best) { throw 'No final release tags found upstream - refusing to build from an unpinned ref.' }
    return $best
}

function Read-Lock {
    if (-not (Test-Path $LockFile)) { return $null }
    return Get-Content $LockFile -Raw | ConvertFrom-Json
}

function Write-Lock($resolvedRef, $commit) {
    $payload = [ordered]@{
        source      = $SourceName
        url         = $UpstreamUrl
        ref         = $resolvedRef
        commit      = $commit
        board       = $Board
        resolved_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        _comment    = 'Pinned MicroPython ref for tools/build_firmware.ps1. Council 2026-07-22 (plan section 3.1): upstream, newest FINAL release, never "latest master". Resolved once and committed so builds are reproducible; re-resolve deliberately with build_firmware.ps1 -Repin, which rewrites this file. Changing the ref may change the .mpy ABI, which makes every field unit compiled payload stale - see plan section 7 step 6 before repinning.'
    }
    $payload | ConvertTo-Json | Out-File -FilePath $LockFile -Encoding utf8
    Write-Host "lockfile updated: $LockFile"
}

# --- 1. Preflight -----------------------------------------------------------
Write-Step 'Preflight'
Assert-Toolchain
$Python = Get-PythonExe
if (-not (Test-Path $ManifestFile)) { throw "freeze manifest missing: $ManifestFile" }
Write-Host "repo        : $RepoRoot"
Write-Host "micropython : $MicroPythonDir"
Write-Host "board       : $Board"
Write-Host "python      : $Python"

# --- 2. Resolve the ref -----------------------------------------------------
Write-Step 'Resolve MicroPython ref'
$lock = Read-Lock
if ($Ref) {
    $targetRef = $Ref
    Write-Host "using -Ref override: $targetRef (lockfile not rewritten)"
} elseif ($Repin -or ($null -eq $lock)) {
    $targetRef = Resolve-NewestFinalTag
    Write-Host "resolved newest final release: $targetRef"
} else {
    $targetRef = $lock.ref
    Write-Host "using locked ref: $targetRef  (pass -Repin to re-resolve)"
}

# --- 3. Checkout ------------------------------------------------------------
Write-Step "Checkout $targetRef"
if (-not (Test-Path (Join-Path $MicroPythonDir '.git'))) {
    Write-Host "cloning into $MicroPythonDir (this takes a while) ..."
    & git clone $UpstreamUrl $MicroPythonDir
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }
}
Push-Location $MicroPythonDir
try {
    & git fetch --tags --force origin
    if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }
    & git checkout --detach $targetRef
    if ($LASTEXITCODE -ne 0) { throw "git checkout $targetRef failed - is it a real tag?" }
    $mpyCommit = (& git rev-parse --short HEAD).Trim()
    Write-Host "at $targetRef ($mpyCommit)"
    Write-Host 'fetching submodules (pico-sdk, tinyusb) ...'
    & make -C ports/rp2 BOARD=$Board submodules
    if ($LASTEXITCODE -ne 0) { throw 'make submodules failed' }
} finally {
    Pop-Location
}

if (-not $Ref) { Write-Lock $targetRef $mpyCommit }

# --- 4. mpy-cross from the same tree ---------------------------------------
Write-Step 'Build mpy-cross (same tree = same .mpy ABI)'
& make -C (Join-Path $MicroPythonDir 'mpy-cross') "-j$Jobs"
if ($LASTEXITCODE -ne 0) { throw 'mpy-cross build failed' }
$MpyCross = Join-Path $MicroPythonDir 'mpy-cross\build\mpy-cross.exe'
if (-not (Test-Path $MpyCross)) {
    $MpyCross = Join-Path $MicroPythonDir 'mpy-cross\build\mpy-cross'
}
if (-not (Test-Path $MpyCross)) { throw 'mpy-cross binary not found after a successful build - check the port layout.' }
Write-Host "mpy-cross: $MpyCross"
Write-Host ''
Write-Host 'REMINDER: build OTA payloads with THIS mpy-cross. A payload compiled by' -ForegroundColor Yellow
Write-Host 'any other one carries a bytecode ABI this firmware will refuse (plan 6.3).' -ForegroundColor Yellow

# --- 5. Generate the frozen fw_info.py -------------------------------------
Write-Step 'Generate fw_info.py'
New-Item -ItemType Directory -Path $FrozenDir -Force | Out-Null
$FwInfoPath = Join-Path $FrozenDir 'fw_info.py'
& $Python (Join-Path $PSScriptRoot 'gen_fw_info.py') `
    --mpy-tree $MicroPythonDir `
    --ref $targetRef `
    --commit $mpyCommit `
    --source-name $SourceName `
    --out $FwInfoPath
if ($LASTEXITCODE -ne 0) { throw 'fw_info generation failed' }

$fwInfoText = Get-Content $FwInfoPath -Raw
$fwVersion = ([regex]'FIRMWARE_VERSION = "([^"]+)"').Match($fwInfoText).Groups[1].Value
$mpyAbi = ([regex]'MPY_ABI = (\d+)').Match($fwInfoText).Groups[1].Value
if (-not $fwVersion) { throw "could not read FIRMWARE_VERSION back from $FwInfoPath" }
Write-Host "firmware version: $fwVersion   (.mpy ABI $mpyAbi)"

# --- 6. Build the firmware --------------------------------------------------
Write-Step "Build ports/rp2 (BOARD=$Board)"
$env:PG_REPO_DIR = $RepoRoot
$env:PG_FW_INFO_DIR = $FrozenDir
if ($Tier1Only) { $env:PG_FREEZE_TIER1_ONLY = '1' } else { Remove-Item Env:\PG_FREEZE_TIER1_ONLY -ErrorAction SilentlyContinue }
if ($FreezeOnly) { $env:PG_FREEZE_ONLY = $FreezeOnly } else { Remove-Item Env:\PG_FREEZE_ONLY -ErrorAction SilentlyContinue }

& make -C (Join-Path $MicroPythonDir 'ports/rp2') BOARD=$Board FROZEN_MANIFEST=$ManifestFile "-j$Jobs"
if ($LASTEXITCODE -ne 0) { throw 'firmware build failed' }

# --- 7. Collect artifacts ---------------------------------------------------
Write-Step 'Collect artifacts'
$builtUf2 = Join-Path $MicroPythonDir "ports/rp2/build-$Board/firmware.uf2"
if (-not (Test-Path $builtUf2)) { throw "firmware.uf2 not found at $builtUf2" }

$targetUf2 = Join-Path $BuildDir 'firmware.uf2'
$archiveUf2 = Join-Path $BuildDir "firmware-$fwVersion.uf2"
Copy-Item $builtUf2 $targetUf2 -Force
Copy-Item $builtUf2 $archiveUf2 -Force

# A build can succeed and still be stock: if FROZEN_MANIFEST never reached the
# port, make produces a perfectly good firmware with nothing frozen, and the
# only symptom is a heap number that did not move. Check the image itself.
Write-Step 'Verify the freeze took'
$verifyArgs = @((Join-Path $PSScriptRoot 'verify_frozen_uf2.py'), $targetUf2, '--expect-version', $fwVersion)
if ($Tier1Only) { $verifyArgs += '--tier1-only' }
& $Python $verifyArgs
if ($LASTEXITCODE -ne 0) { throw 'freeze verification failed - do not flash this image' }

$note = [ordered]@{
    firmware_version = $fwVersion
    mpy_abi          = [int]$mpyAbi
    mpy_source       = "$SourceName@$targetRef@$mpyCommit"
    board            = $Board
    tier1_only       = [bool]$Tier1Only
    freeze_only      = $FreezeOnly
    mpy_cross        = $MpyCross
    built_at         = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    artifact         = $targetUf2
    rollback         = $archiveUf2
}
$notePath = Join-Path $BuildDir 'firmware-build.json'
$note | ConvertTo-Json | Out-File -FilePath $notePath -Encoding utf8

Write-Host ''
Write-Host "firmware : $targetUf2" -ForegroundColor Green
Write-Host "rollback : $archiveUf2" -ForegroundColor Green
Write-Host "note     : $notePath" -ForegroundColor Green
Write-Host ''
Write-Host 'Next steps (docs/hardware/firmware-build-runbook.md):'
Write-Host '  1. Confirm the device logged its CURRENT version to /boot.log before you flash.'
Write-Host '  2. Keep the previous firmware-<version>.uf2 - it is the only rollback.'
Write-Host '  3. BOOTSEL + drag-drop, then watch boot.log for import errors on every frozen module.'
Write-Host '  4. Soak with diagnostics.mem_trend_log = True and compare via tools/heap_baseline.py.'
