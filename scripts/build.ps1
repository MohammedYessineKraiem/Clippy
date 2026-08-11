$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ModelPath = Join-Path $ProjectRoot "models\all-MiniLM-L6-v2"

if (-not (Test-Path -LiteralPath $ModelPath -PathType Container)) {
    throw "Local model missing: $ModelPath"
}

Push-Location $ProjectRoot
try {
    python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    python -m PyInstaller --noconfirm --clean "packaging\Clippy.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
} finally {
    Pop-Location
}
