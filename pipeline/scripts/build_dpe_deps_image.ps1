param(
    [Parameter(Mandatory = $true)]
    [string]$ImageTag
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Push-Location $Root
try {
    docker build -f docker/dpe-deps/Dockerfile -t $ImageTag .
    Write-Host "Built: $ImageTag"
    Write-Host "Next:"
    Write-Host "  1. docker push $ImageTag"
    Write-Host "  2. MaxCompute 控制台 -> 镜像管理 -> 登记 ACR 镜像"
    Write-Host "  3. DataWorks 工作流参数 dpe_image=<MC 镜像名称>"
}
finally {
    Pop-Location
}
