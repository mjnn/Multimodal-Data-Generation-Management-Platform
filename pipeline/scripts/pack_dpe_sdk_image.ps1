#!/usr/bin/env pwsh
# 从 piplinesdk 构建 wheel，并刷新 pipeline/dist/dpe-sdk-image-pack-* + zip
param(
    [string]$Version = "0.3.2"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Sdk = Join-Path $Repo "piplinesdk"
$PackName = "dpe-sdk-image-pack-$Version"
$OutDir = Join-Path $Repo "pipeline\dist\$PackName"
$DockerPack = Join-Path $Repo "pipeline\docker\dpe-sdk-pack"
$WheelName = "oms_multimodal_sdk-$Version-py3-none-any.whl"

Push-Location $Sdk
try {
    py -3.11 -m pip install build -q
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
    py -3.11 -m build --wheel
    $whl = Get-ChildItem dist -Filter "*.whl" | Select-Object -First 1
    if (-not $whl) { throw "wheel not built" }
}
finally {
    Pop-Location
}

foreach ($dir in @($OutDir, $DockerPack)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $dir "wheels") | Out-Null
}

$template = Join-Path $DockerPack "Dockerfile"
# Prefer existing pack template under docker/dpe-sdk-pack if present; else require OutDir already seeded
$srcWhl = Join-Path $Sdk "dist\$($whl.Name)"
Copy-Item $srcWhl (Join-Path $OutDir "wheels\$WheelName") -Force
Copy-Item $srcWhl (Join-Path $DockerPack "wheels\$WheelName") -Force

foreach ($name in @("Dockerfile", "requirements.txt", "README.md", "build.ps1", "MANIFEST.txt")) {
    $a = Join-Path $DockerPack $name
    $b = Join-Path $OutDir $name
    if (Test-Path $a) {
        Copy-Item $a $b -Force
    } elseif (Test-Path $b) {
        Copy-Item $b $a -Force
    }
}

$Zip = Join-Path $Repo "pipeline\dist\$PackName.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path $OutDir -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "OK pack=$OutDir"
Write-Host "OK zip=$Zip"
Write-Host "OK wheel=$srcWhl"
