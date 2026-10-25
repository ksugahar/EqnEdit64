# Final, non-interactive EqnEdit64 release gate.
#
# This is intentionally stricter than build_tests.bat: it adds ASan, the
# extended real-window-procedure endurance run and release identity checks.
# Every UI process is started hidden by the underlying tests;
# no SendInput, cursor movement, or foreground activation is used.

[CmdletBinding()]
param(
    [ValidateRange(1, 10000)]
    [int]$EnduranceSeeds = 100,
    [ValidateRange(1, 1000000)]
    [int]$EnduranceOps = 5000,
    [ValidateRange(60, 3600)]
    [int]$EnduranceTimeoutSeconds = 1800,
    [Parameter(Mandatory)]
    [ValidateSet('Unsigned', 'Signed')]
    [string]$Phase,
    [Parameter(Mandatory)]
    [string]$CheckpointPath,
    [string]$UnsignedReportPath,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'
if ($EnduranceSeeds -ne 100 -or $EnduranceOps -ne 5000 -or $EnduranceTimeoutSeconds -ne 1800) {
    throw 'Release gate requires 100 seeds, 5000 operations per seed and 1800 seconds'
}
if (-not $ReportPath) {
    $ReportPath = Join-Path ([IO.Path]::GetTempPath()) 'EqnEdit64-final-acceptance.json'
}
if ($env:EQNEDIT64_ISOLATED_TEST_SESSION -ne '1') {
    throw @'
The full release gate starts and exits several private-font processes.
Run it only in hosted CI or the approved isolated test session, then set EQNEDIT64_ISOLATED_TEST_SESSION=1 in that session.
'@
}
$root = Split-Path -Parent $PSScriptRoot
$buildExe = Join-Path $root 'build\EqnEdit64.exe'
$distExe = Join-Path $root 'dist\EqnEdit64.exe'
$started = Get-Date
if ([IO.Path]::GetFullPath($ReportPath) -eq [IO.Path]::GetFullPath($CheckpointPath)) {
    throw 'Report and checkpoint must be separate files'
}
if ($Phase -eq 'Signed') {
    if (-not $UnsignedReportPath) { throw 'UnsignedReportPath is required' }
    if ([IO.Path]::GetFullPath($ReportPath) -eq [IO.Path]::GetFullPath($UnsignedReportPath) -or
        [IO.Path]::GetFullPath($ReportPath) -eq [IO.Path]::GetFullPath($CheckpointPath)) {
        throw 'Signed report must preserve the unsigned records'
    }
    foreach ($required in @($CheckpointPath, $UnsignedReportPath, $buildExe, $distExe)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing checkpoint input: $required" }
    }
    $releaseFiles = @(Get-ChildItem -LiteralPath (Split-Path -Parent $distExe) -File)
    if ($releaseFiles.Count -ne 1 -or $releaseFiles[0].Name -cne 'EqnEdit64.exe') {
        throw 'dist must contain EqnEdit64.exe only'
    }
    # Hold both actual inputs against writes/replacement throughout trust and byte checks.
    $buildLock = [IO.File]::Open($buildExe, 'Open', 'Read', 'Read')
    try {
        $distLock = [IO.File]::Open($distExe, 'Open', 'Read', 'Read')
        try {
            if ((Get-FileHash $buildExe).Hash -ne (Get-FileHash $distExe).Hash) { throw 'Signed build/dist mismatch' }
            $signature = Get-AuthenticodeSignature -LiteralPath $distExe
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -cne 'CN=ksugahar' -or
                -not ($signature.SignerCertificate.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.3')) {
                throw 'Invalid code signing certificate'
            }
            $certificateHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($signature.SignerCertificate.RawData))
            if ($env:EQNEDIT64_SIGNER_SHA256) {
                if ($env:EQNEDIT64_SIGNER_SHA256 -notmatch '^[0-9a-fA-F]{64}$' -or
                    $certificateHash -cne $env:EQNEDIT64_SIGNER_SHA256.ToUpperInvariant()) { throw 'Signer pin mismatch' }
            }
            Push-Location $root
            try {
                & python tools/release_version.py --check
                if ($LASTEXITCODE -ne 0) { throw 'Generated release version fields are stale' }
                & python tools/check_release_versions.py --artifact $distExe --artifact web/equation-editor.js --artifact web/equation-editor.fragment.html
                if ($LASTEXITCODE -ne 0) { throw 'Signed release version label gate failed' }
                & python tools/signing_checkpoint.py verify --exe $distExe --acceptance $UnsignedReportPath --checkpoint $CheckpointPath --output $ReportPath
                if ($LASTEXITCODE -ne 0) { throw 'Signed qualification payload verification failed' }
            } finally { Pop-Location }
            $signedReport = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
            $signedReport | Add-Member -NotePropertyName signer -NotePropertyValue $signature.SignerCertificate.Subject
            $signedReport | Add-Member -NotePropertyName signer_sha256 -NotePropertyValue $certificateHash
            $signedReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding utf8
        } finally { $distLock.Dispose() }
    } finally { $buildLock.Dispose() }
    Write-Host 'PASS: signed payload matches completed unsigned qualification; no rebuild'
    return
}
if (Test-Path -LiteralPath $CheckpointPath) { throw 'Existing checkpoint must not be overwritten' }


function Invoke-Batch([string]$RelativePath, [int]$FuzzTimeoutSeconds = 0) {
    Push-Location $root
    try {
        if ($FuzzTimeoutSeconds) {
            & cmd.exe /d /c $RelativePath $FuzzTimeoutSeconds
        } else {
            & cmd.exe /d /c $RelativePath
        }
        if ($LASTEXITCODE -ne 0) {
            throw "$RelativePath failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-PowerShellScript([string]$RelativePath, [object[]]$Arguments) {
    $script = Join-Path $root $RelativePath
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $script @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$RelativePath failed with exit code $LASTEXITCODE"
    }
}

if ($Phase -eq 'Unsigned') {
    Invoke-Batch 'build\build_tests.bat' $EnduranceTimeoutSeconds
    Invoke-Batch 'build\build_asan.bat'
    Invoke-PowerShellScript 'build\test_asan.ps1' @(
        '-TimeoutSeconds', $EnduranceTimeoutSeconds)
}

foreach ($required in @($buildExe, $distExe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required release input is missing: $required"
    }
}

Invoke-PowerShellScript 'build\test_font_session.ps1' @(
    '-AppPath', $distExe, '-Iterations', 32)

# The long normal-build run is separate from ASan: it exercises the unsigned,
# portable executable that will actually be deployed.
$enduranceTimer = [Diagnostics.Stopwatch]::StartNew()
Invoke-PowerShellScript 'build\test_ui_fuzz.ps1' @(
    '-AppPath', $distExe, '-Seeds', $EnduranceSeeds, '-Ops', $EnduranceOps,
    '-TimeoutSeconds', $EnduranceTimeoutSeconds)
$enduranceTimer.Stop()

$paintReport = (Join-Path $env:TEMP 'EqnEdit64-paint-benchmark.txt')
$paintError = (Join-Path $env:TEMP 'EqnEdit64-paint-benchmark.err.txt')
$paint = Start-Process -FilePath $distExe -ArgumentList '--paint-bench' `
    -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput $paintReport -RedirectStandardError $paintError
if ($paint.ExitCode -ne 0) {
    $details = Get-Content -LiteralPath $paintReport -Raw -ErrorAction SilentlyContinue
    throw "Offscreen paint performance gate failed ($($paint.ExitCode)):`n$details"
}
$paintMeasurements = Get-Content -LiteralPath $paintReport -Raw

$releaseFiles = @(Get-ChildItem -LiteralPath (Split-Path -Parent $distExe) -File)
if ($releaseFiles.Count -ne 1 -or $releaseFiles[0].Name -cne 'EqnEdit64.exe') {
    throw "dist must contain EqnEdit64.exe only: $($releaseFiles.Name -join ', ')"
}
$buildHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $buildExe).Hash
$distHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $distExe).Hash
if ($buildHash -ne $distHash) {
    throw 'dist\EqnEdit64.exe is not the exact executable exercised by the gate.'
}

$stamp = Join-Path $root 'src\build_stamp.h'
$buildCommit = 'unknown'
if (Test-Path -LiteralPath $stamp) {
    $match = Select-String -LiteralPath $stamp -Pattern 'BUILD_COMMIT' |
        Select-Object -First 1
    if ($match) { $buildCommit = $match.Line -replace '.*"(.*)".*', '$1' }
}
$gitCommit = (& git -C $root rev-parse HEAD).Trim()
$asanRuntime = if ($Phase -eq 'Unsigned') {
    $runtimePath = Join-Path $root 'build\clang_rt.asan_dynamic-x86_64.dll'
    $runtimeInfo = Get-Item -LiteralPath $runtimePath -ErrorAction Stop
    [ordered]@{
        path = $runtimeInfo.FullName
        version = $runtimeInfo.VersionInfo.FileVersion
        sha256 = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash
    }
} else { $null }
$report = [ordered]@{
    schema = 'eqnedit64.final-acceptance.v2'
    accepted_at = (Get-Date).ToString('o')
    elapsed_seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 3)
    source_commit = $gitCommit
    executable_build_commit = $buildCommit
    app_path = $distExe
    app_sha256 = $distHash
    session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
    phase = 'unsigned-qualified-awaiting-signature'
    distribution_files = @($releaseFiles.Name)
    gui_endurance = [ordered]@{
        seeds = $EnduranceSeeds
        operations_per_seed = $EnduranceOps
        total_operations = $EnduranceSeeds * $EnduranceOps
        timeout_seconds = $EnduranceTimeoutSeconds
        elapsed_seconds = [math]::Round($enduranceTimer.Elapsed.TotalSeconds, 3)
    }
    font_lifecycles = 32
    paint_benchmark = $paintMeasurements.Trim()
    background_suite = 'passed'
    asan_suite = 'passed'
    asan_runtime = $asanRuntime
    build_phase_fuzz_timeout_seconds = $EnduranceTimeoutSeconds
}
$reportFolder = Split-Path -Parent $ReportPath
if (-not (Test-Path -LiteralPath $reportFolder)) {
    New-Item -ItemType Directory -Path $reportFolder | Out-Null
}
$report | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath $ReportPath -Encoding utf8

Push-Location $root
try {
    & python tools/signing_checkpoint.py record --exe $distExe --acceptance $ReportPath --checkpoint $CheckpointPath
    if ($LASTEXITCODE -ne 0) { throw 'Unsigned signing checkpoint failed' }
} finally { Pop-Location }
Write-Host 'PASS: unsigned qualification complete; manager signing required' 
Write-Host "  commit: $buildCommit"
Write-Host "  sha256: $distHash"

Write-Host "  endurance: $EnduranceSeeds x $EnduranceOps = $($EnduranceSeeds * $EnduranceOps) operations"
Write-Host "  paint benchmark: all cached cases below 5 ms"
Write-Host "  report: $ReportPath"
