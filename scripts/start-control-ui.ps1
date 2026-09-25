$ErrorActionPreference = "Stop"

$ProjectDirectory = Split-Path -Parent $PSScriptRoot
$ControlPort = if ($env:OMEGACLAW_CONTROL_PORT) { $env:OMEGACLAW_CONTROL_PORT } else { "3210" }
$ControlUrl = "http://localhost:$ControlPort"

Push-Location $ProjectDirectory
try {
    docker compose up --detach --build control
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not start Omega Control." }

    Write-Host "Waiting for Omega Control at $ControlUrl ..."
    $Healthy = $false
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        $Health = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' omegaclaw-control 2>$null
        if ($Health -eq "healthy") {
            $Healthy = $true
            break
        }
        Start-Sleep -Seconds 1
    }

    if (-not $Healthy) {
        throw "Omega Control did not become healthy. Run: docker compose logs control"
    }

    Start-Process $ControlUrl
} finally {
    Pop-Location
}
