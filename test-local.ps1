$ErrorActionPreference = "Stop"
python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) {
    throw "DeepResearch tests failed with exit code $LASTEXITCODE"
}
