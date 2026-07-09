$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not $env:DEEP_RESEARCH_WEB_PORT) {
    $env:DEEP_RESEARCH_WEB_PORT = "18181"
}

Write-Host "Starting DeepResearch Report Workbench..."
Write-Host "Open http://127.0.0.1:$env:DEEP_RESEARCH_WEB_PORT"

python report_workbench.py
