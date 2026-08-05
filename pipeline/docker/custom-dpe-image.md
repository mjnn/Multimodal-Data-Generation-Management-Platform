# 自定义 DPE 镜像规范（DataWorks / MaxFrame）



上云管线使用 MaxFrame DPE。**Driver 与 DPE worker 是两套运行环境。**



## 两套镜像，不要混用



| 环境 | 谁跑 | 装什么 | 怎么配 |

|------|------|--------|--------|

| **DataWorks 节点 Pod（Driver）** | `new_session(o)`、写 MC | maxframe、pyodps、pandas | 节点「自定义镜像」+ 启动脚本 pip |

| **MaxCompute DPE Worker** | `@with_fs_mount`、parse_bag | rosbags、pyyaml、**ossfs2** | `docker/dpe-deps` 构建 → ACR → **MC 镜像管理** → 参数 `dpe_image` |



Driver 启动脚本里的 `pip install rosbags` **不会**进入 DPE worker。



## Job1 推荐：deps-only DPE 镜像



源码：`docker/dpe-deps/Dockerfile`



内含：



- Python 3.11（Miniforge，`MF_PYTHON_EXECUTABLE`）

- `rosbags`、`pyyaml`

- `ossfs2`（`@with_fs_mount` 必需）

- **不含** maxframe/pyodps、**不含**业务 `.py`



### 1. 本地构建并推送 ACR



```powershell

.\scripts\build_dpe_deps_image.ps1 -ImageTag registry.cn-shanghai.aliyuncs.com/<命名空间>/rosbag-dpe-deps:latest

docker push registry.cn-shanghai.aliyuncs.com/<命名空间>/rosbag-dpe-deps:latest

```



要求：ACR **企业版**（标准版/高级版），x86_64。



### 2. MaxCompute 登记镜像



控制台 → **管理配置 → 镜像管理 → 用户自定义镜像 → 创建镜像**



- 选择 ACR 企业版实例、命名空间、仓库、版本

- **镜像名称**（小写）：例如 `rosbag_dpe_deps`（Job1 工作流参数 `dpe_image` 填此名，不是 ACR 完整 URL）



### 3. DataWorks 工作流参数



```

dpe_image=rosbag_dpe_deps

```



`job1_parse_node.py` 会在 `new_session` 前设置：



```python

mf_options.sql.settings = {

    "odps.sql.python.version": "cp311",

    "odps.session.image": "<dpe_image>",

}

```



日志应出现：`Job1 DPE image: rosbag_dpe_deps`



### 4. DataWorks Driver 镜像（不变）



节点自定义镜像启动脚本只需 Driver 依赖：



```bash

pip install maxframe pyodps pandas alibabacloud_oss_v2 pyarrow

# Job1 Driver 不需要 rosbags；DPE 走 dpe_image

```



业务代码：**整文件粘贴** `dataworks/job*_*.py`。



### 5. SDK v1：`sdk_pipeline_driver` DPE 镜像（必装 `[mc]`）



**推荐云上路径**为单节点 `sdk_pipeline_driver_node.py`：DPE chunk UDF 内 `import oms_multimodal` 并按 `MODEL_BACKEND=mc` 嵌套 MaxFrame AI。镜像 **必须** 安装带 MC extra 的 SDK，版本 **≥ 0.3.2**。



在 `docker/dpe-deps/Dockerfile` 的 `pip install -r requirements.txt` 之后追加（二选一）：



**A. PyPI / 镜像源（推荐生产登记前本地验证）**



```dockerfile

RUN conda run -n py311 pip install --no-cache-dir 'oms-multimodal-sdk[mc]>=0.3.2' && \

    conda run -n py311 python -c "import oms_multimodal; print('sdk', oms_multimodal.__version__)"

```



**B. 本地 wheel（离线 / 未发布时）**



```dockerfile

# 本地先构建 wheel：cd piplinesdk && py -3 -m build

COPY piplinesdk/dist/oms_multimodal_sdk-0.3.2-py3-none-any.whl /tmp/sdk.whl

RUN conda run -n py311 pip install --no-cache-dir '/tmp/sdk.whl[mc]' && \

    conda run -n py311 python -c "import oms_multimodal; print('sdk', oms_multimodal.__version__)"

```



**禁止** COPY 业务 `.py` 后在 DPE 内 subprocess。maxframe/pyodps 由 MaxCompute 平台提供，**勿**打进生产 DPE 镜像 unless 平台文档要求。



工作流参数示例：



```

dpe_image=rosbag_sdk_dpe

dpe_cpu=4

dpe_memory_gb=16

```



节点模板：`pipeline/dataworks/sdk_pipeline_driver_node.py`（单 Driver + `apply_chunk`；多节点 `sdk_*_dpe_node.py` 已冻结，见 `dataworks/WORKFLOW.md`）



## 回退：不配 dpe_image



未设 `dpe_image` 时 Job1 使用 `@with_python_requirements("rosbags")` 在线装包（慢，且多 PythonPack 子任务）。生产环境请用 `dpe_image`。



## 历史路径（勿用）



- `docker/job1-dpe/Dockerfile`：COPY 业务代码 + subprocess，已废弃

- `cloud/job1_submit.py`：本地 submit，已废弃



## 参考



- `.cursor/rules/maxframe-dpe-cloud.mdc`

- `dataworks/workflow-params.example`


