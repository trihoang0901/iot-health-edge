[CmdletBinding()]
param(
    [switch]$IncludeDockerLive,
    [switch]$IncludeFirmware
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$composeFile = Join-Path $root 'deploy\docker-compose.yml'
$envFile = Join-Path $root '.env'
$firmwareDir = Join-Path $root 'firmware\health-node'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dryRunRoot = Join-Path $root ".codex-tmp\verify-runs-$timestamp"
$reportPath = Join-Path $root 'evidence\analysis\verification-latest.json'
$results = [System.Collections.Generic.List[object]]::new()
$script:LastNativeExitCode = 0
$invocation = '.\scripts\VERIFY-MVP.ps1'
if ($IncludeDockerLive) {
    $invocation += ' -IncludeDockerLive'
}
if ($IncludeFirmware) {
    $invocation += ' -IncludeFirmware'
}
$reportDir = Split-Path -Parent $reportPath
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$runningReport = [ordered]@{
    artifact_version = '1.3'
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    command = $invocation
    launcher_or_upload_used = $false
    overall_status = 'running'
    checks = @()
}
[System.IO.File]::WriteAllText(
    $reportPath,
    (($runningReport | ConvertTo-Json -Depth 5) + "`n"),
    $utf8NoBom
)

if (-not (Test-Path -LiteralPath $python)) {
    throw "Khong tim thay Python cua project: $python"
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Khong tim thay .env cuc bo de resolve Compose"
}

function Invoke-VerificationGate {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Action,
        [bool]$Required = $true
    )

    Write-Host "`n==> $Name"
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 'passed'
    $errorCode = $null
    $script:LastNativeExitCode = 0
    try {
        & $Action
        if ($script:LastNativeExitCode -ne 0) {
            throw "process_exit_$script:LastNativeExitCode"
        }
    }
    catch {
        $status = 'failed'
        $errorCode = $_.Exception.GetType().Name
        Write-Host "FAILED: $Name ($errorCode)" -ForegroundColor Red
    }
    finally {
        $watch.Stop()
    }

    $results.Add([pscustomobject]@{
        name = $Name
        required = $Required
        status = $status
        duration_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 1)
        error_code = $errorCode
    })
}

Push-Location $root
try {
    Invoke-VerificationGate -Name 'Python full regression' -Action {
        & $python -m pytest -q
        $script:LastNativeExitCode = $LASTEXITCODE
    }

    Invoke-VerificationGate -Name 'Dashboard JavaScript syntax' -Action {
        & node --check '.\edge\static\app.js'
        $script:LastNativeExitCode = $LASTEXITCODE
    }

    Invoke-VerificationGate -Name 'Docker Compose resolved config' -Action {
        & docker compose --env-file $envFile -f $composeFile --profile full config --quiet
        $script:LastNativeExitCode = $LASTEXITCODE
    }

    Invoke-VerificationGate -Name 'Deterministic experiment dry-run' -Action {
        & $python -m simulator.experiment `
            --profile remote-app-emulated `
            --scenario normal `
            --count 30 `
            --seed 20260814 `
            --run-id "verify-$timestamp" `
            --output-dir $dryRunRoot `
            --dry-run
        $script:LastNativeExitCode = $LASTEXITCODE
    }

    if ($IncludeDockerLive) {
        Invoke-VerificationGate -Name 'Docker live health and capabilities' -Action {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 5
            $capabilities = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/capabilities' -TimeoutSec 5
            if ($health.status -ne 'ok') {
                throw 'edge_health_not_ok'
            }
            if ($capabilities.protocol.name -ne 'MQTT' -or $capabilities.claims.measured_5g) {
                throw 'capability_contract_invalid'
            }
        }
    }
    else {
        $results.Add([pscustomobject]@{
            name = 'Docker live health and capabilities'
            required = $false
            status = 'not_requested'
            duration_ms = 0
            error_code = $null
        })
    }

    if ($IncludeFirmware) {
        $platformio = @(
            (Join-Path $root '.platformio-venv\Scripts\platformio.exe'),
            (Join-Path $env:USERPROFILE '.platformio\penv\Scripts\platformio.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        Invoke-VerificationGate -Name 'Firmware build-only nodemcuv2' -Required $false -Action {
            if (-not $platformio) {
                throw 'platformio_not_found'
            }
            & $platformio run --project-dir $firmwareDir --environment nodemcuv2
            $script:LastNativeExitCode = $LASTEXITCODE
        }
    }
    else {
        $results.Add([pscustomobject]@{
            name = 'Firmware build-only nodemcuv2'
            required = $false
            status = 'not_requested'
            duration_ms = 0
            error_code = $null
        })
    }
}
finally {
    Pop-Location
}

$requiredFailures = @($results | Where-Object { $_.required -and $_.status -ne 'passed' })
$runnerProvenanceJson = & $python -c "import json; from simulator.experiment import source_provenance; print(json.dumps(source_provenance()))"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($runnerProvenanceJson)) {
    throw 'Khong tao duoc runner source fingerprint cho verification report'
}
$verificationProvenanceJson = & $python '.\scripts\verification_source_fingerprint.py'
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($verificationProvenanceJson)) {
    throw 'Khong tao duoc verification input fingerprint'
}
$runnerProvenance = $runnerProvenanceJson | ConvertFrom-Json
$verificationProvenance = $verificationProvenanceJson | ConvertFrom-Json
$report = [ordered]@{
    artifact_version = '1.3'
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    command = $invocation
    runner_source_provenance = $runnerProvenance
    verification_input_provenance = $verificationProvenance
    launcher_or_upload_used = $false
    overall_status = if ($requiredFailures.Count -eq 0) { 'passed' } else { 'failed' }
    checks = $results
}

$reportJson = $report | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($reportPath, $reportJson + "`n", $utf8NoBom)
Write-Host "`nVerification report: $reportPath"
Write-Host "Overall: $($report.overall_status)"

if ($requiredFailures.Count -gt 0) {
    exit 1
}
