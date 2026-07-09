$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m unittest tests.test_report_workbench
python -m unittest discover -s tests
