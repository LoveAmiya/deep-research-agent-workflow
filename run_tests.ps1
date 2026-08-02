$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m unittest tests.test_report_workbench
python -m unittest discover -s tests
python -m evaluation.test_inventory --report evaluation/results/latest_test_inventory.json
