param(
    [Parameter(Mandatory = $true)]
    [string]$ImageTag
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Push-Location $Root
try {
    Write-Warning "job1-dpe/Dockerfile is deprecated. Building docker/dpe-deps instead."
    docker build -f docker/dpe-deps/Dockerfile -t $ImageTag .
    Write-Host "Built image: $ImageTag"
    Write-Host "Push to ACR, register in MaxCompute 镜像管理, set workflow param dpe_image=<MC镜像名>."
}
finally {
    Pop-Location
}
