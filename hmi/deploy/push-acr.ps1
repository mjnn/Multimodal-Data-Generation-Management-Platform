$ErrorActionPreference = 'Stop'
$envFile = (Resolve-Path (Join-Path $PSScriptRoot '..\..\.env')).Path
$lines = Get-Content $envFile
$reg = ($lines | Where-Object { $_ -match '^ACR_REGISTRY=' }) -replace '^ACR_REGISTRY=', ''
$user = ($lines | Where-Object { $_ -match '^ACR_USERNAME=' }) -replace '^ACR_USERNAME=', ''
$pass = ($lines | Where-Object { $_ -match '^ACR_PASSWORD=' }) -replace '^ACR_PASSWORD=', ''
if (-not $reg -or -not $user -or -not $pass) { throw 'Missing ACR credentials in .env' }
$pass | docker login $reg --username $user --password-stdin
docker push crpi-02k3y8iudey5q0vb.cn-shanghai.personal.cr.aliyuncs.com/mirror_ns/rosbag_to_labels_pipline_hmi:20260803-2
docker push crpi-02k3y8iudey5q0vb.cn-shanghai.personal.cr.aliyuncs.com/mirror_ns/rosbag_to_labels_pipline_hmi:latest
