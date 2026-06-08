param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = "python"
$IconPath = Join-Path $Root "assets\macro-logo.ico"
$IconSource = Join-Path $Root "assets\macro-logo-300.png"

function Invoke-Native {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command exited with code $LASTEXITCODE"
    }
}

if (-not (Test-Path $IconPath)) {
    Write-Host "Generating app icon..."
    Invoke-Native $Python @("-c", "from pathlib import Path; from PIL import Image; src=Path(r'$IconSource'); out=Path(r'$IconPath'); im=Image.open(src).convert('RGBA'); sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]; im.save(out, sizes=sizes)")
}

Write-Host "Installing runtime and build requirements..."
Invoke-Native $Python @("-m", "pip", "install", "-r", "requirements.txt", "-r", "requirements-build.txt")

if (-not $SkipTests) {
    Write-Host "Running tests..."
    Invoke-Native $Python @("-m", "unittest", "discover", "-s", "tests", "-v")
}

$ExePath = Join-Path $Root "dist\Macro Studio\Macro Studio.exe"
$RunningBuild = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $ExePath }
if ($RunningBuild) {
    Write-Host "Stopping running packaged app before rebuild..."
    $RunningBuild | Stop-Process -Force
}

Write-Host "Building Macro Studio..."
Invoke-Native $Python @("-m", "PyInstaller", "--clean", "--noconfirm", "MacroStudio.spec")

if (-not (Test-Path $ExePath)) {
    throw "Build finished but executable was not found at $ExePath"
}

Write-Host "Built $ExePath"
