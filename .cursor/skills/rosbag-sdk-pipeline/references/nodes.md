# DataWorks 节点与脚本

## 生产

| 文件 | 用途 |
|------|------|
| `pipeline/dataworks/sdk_pipeline_driver_node.py` | 单 Driver 源码 |
| `pipeline/dataworks/bundled/sdk_pipeline_driver_node.py` | 粘贴进 PyODPS3 |
| `pipeline/scripts/bundle_sdk_pipeline_driver.py` | 生成 bundled |
| `pipeline/scripts/check_dpe_nodes.py` | 禁止 class |

## Legacy（维护 only）

`job0_discover_node.py` → `job0_dispatch_node.py` → Job1–4。表前缀 `aig_rosbag__`。新 bag 不要走这条。

冻结的多节点 SDK（`sdk_extract_node.py` 等）仅应急，不要为新功能重新编排。

## 镜像

- Driver：maxframe / pyodps（DataWorks 自定义镜像）
- DPE：`pipeline/docker/dpe-sdk-pack/` 或 `dpe-deps`；含 rosbags/ffmpeg/ossfs2；**不要**把 maxframe 打进 DPE
