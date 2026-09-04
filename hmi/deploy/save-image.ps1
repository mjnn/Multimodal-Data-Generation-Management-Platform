#Requires -Version 5.1
<#
.SYNOPSIS
  在仓库根构建 HMI 镜像并 docker save 到 hmi/deploy/offline/*.tar

.DESCRIPTION
  对应交接文档 docs/deploy-intranet-cicd.md。
  必须在装有 Docker 的开发机执行；构建上下文为 Git 仓库根（不是 hmi/deploy）。

.EXAMPLE
  powershell -File hmi\deploy\save-image.ps1 -Tag 20260827-1
#>
param(
    [Parameter(Mandatory = $false)]
    [string] $Tag = (Get-Date -Format "yyyyMMdd-1"),

    [switch] $SkipFrontend
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
Write-Host "REPO_ROOT=$RepoRoot  TAG=$Tag"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "找不到 docker。请先安装 Docker Desktop / 引擎，并确保当前用户能运行 docker。"
}

$frontend = Join-Path $RepoRoot "hmi\frontend"
$dist = Join-Path $frontend "dist"
if (-not $SkipFrontend) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "找不到 npm。构建前端需要 Node.js。"
    }
    Push-Location $frontend
    try {
        if (Test-Path (Join-Path $frontend "package-lock.json")) {
            npm ci
        } else {
            npm install
        }
        npm run build
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $dist)) {
    throw "缺少 hmi/frontend/dist。去掉 -SkipFrontend 或先 npm run build。"
}

$imageDated = "rosbag-to-labels-hmi:$Tag"
$imageLatest = "rosbag-to-labels-hmi:latest"

Write-Host "docker build -f hmi/deploy/Dockerfile (context=repo root)"
docker build -f "hmi/deploy/Dockerfile" `
    --build-arg "APP_REVISION=$Tag" `
    -t $imageDated `
    -t $imageLatest `
    .

$outDir = Join-Path $RepoRoot "hmi\deploy\offline"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$tar = Join-Path $outDir "rosbag-to-labels-hmi-$Tag.tar"

Write-Host "docker save -o $tar"
docker save -o $tar $imageDated $imageLatest

$hash = (Get-FileHash -Algorithm SHA256 $tar).Hash
Write-Host "OK tar=$tar"
Write-Host "SHA256=$hash"
Write-Host "下一步: sftp -P 60022 <账号>@odnpgdcpiv.bastionhost.aliyuncs.com  然后 put 该 tar"
