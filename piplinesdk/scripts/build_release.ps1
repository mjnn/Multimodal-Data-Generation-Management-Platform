# OMS Multimodal SDK — 构建 0.3.2 发布包
# 用法：cd piplinesdk ; .\scripts\build_release.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $Root
$Bundled = Join-Path $Root "oms_multimodal\bundled"
$ExamplesDst = Join-Path $Bundled "examples\dataworks"
$PipelineDw = Join-Path $RepoRoot "pipeline\dataworks"

Write-Host "==> Sync docs to bundled/"
Copy-Item (Join-Path $Root "docs\SDK.md") (Join-Path $Bundled "SDK.md") -Force
Copy-Item (Join-Path $Root "docs\DATAWORKS_SDK.md") (Join-Path $Bundled "DATAWORKS_SDK.md") -Force
Copy-Item (Join-Path $Root "oms_label_taxonomy.yaml") (Join-Path $Bundled "oms_label_taxonomy.yaml") -Force

Write-Host "==> Sync DataWorks example nodes to bundled/examples/dataworks/"
New-Item -ItemType Directory -Force -Path $ExamplesDst | Out-Null
$ExampleFiles = @(
    "dpe_udf_minimal_example.py",
    "sdk_dpe_common.py",
    "sdk_dispatch_batch_node.py",
    "sdk_extract_dpe_node.py",
    "sdk_asr_dpe_node.py",
    "sdk_preview_dpe_node.py",
    "sdk_label_dpe_node.py",
    "sdk_embed_dpe_node.py",
    "sdk_infer_node.py",
    "sdk_node_common.py"
)
foreach ($name in $ExampleFiles) {
    $src = Join-Path $PipelineDw $name
    if (-not (Test-Path $src)) {
        Write-Warning "Skip missing: $src"
        continue
    }
    Copy-Item $src (Join-Path $ExamplesDst $name) -Force
}
# dispatch helpers（DPE 节点 import）
foreach ($name in @("pipeline_dispatch.py", "upload_run.py")) {
    $src = Join-Path $PipelineDw $name
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $ExamplesDst $name) -Force
    }
}

Write-Host "==> Build wheel + sdist"
Push-Location $Root
try {
    python -m pip install build -q
    python -m build
    $Wheel = Get-ChildItem dist\oms_multimodal_sdk-*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Wheel) { throw "No wheel in dist/" }
    Copy-Item $Wheel.FullName (Join-Path $Root $Wheel.Name) -Force
    Write-Host "==> Done: $($Wheel.FullName)"
    Write-Host "==> Copied to: $(Join-Path $Root $Wheel.Name)"
} finally {
    Pop-Location
}

Write-Host "==> Verify import"
python -c @"
from oms_multimodal import __version__, bundled_sdk_doc_path, bundled_dataworks_doc_path, bundled_examples_dir
from oms_multimodal.client import OmsMultimodalClient
print('version', __version__)
print('sdk doc', bundled_sdk_doc_path().exists())
print('dw doc', bundled_dataworks_doc_path().exists())
print('examples', len(list(bundled_examples_dir().glob('dataworks/*.py'))))
"@
