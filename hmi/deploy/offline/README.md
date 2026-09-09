# 内网离线加载 HMI 镜像

> **完整交接流程**（开发机构建、save、堡垒机 SFTP、POC 上 load/run）：[`docs/deploy-intranet-cicd.md`](../../../docs/deploy-intranet-cicd.md)  
> 下文是某次已打好的 tar 快照，**tag 会过期**，新发布请用 `save-image.ps1` 生成新文件。

## 包内容

| 项 | 值 |
|----|-----|
| 文件 | `rosbag-to-labels-hmi-20260909-1.tar` |
| SHA256 | `03C57AB510B5D7AB6A85C6A315CA0C246B2778EE868DD32F13042D877ACA258A` |
| 镜像 tag | `rosbag-to-labels-hmi:20260909-1`、`rosbag-to-labels-hmi:latest` |
| 构建 | 含 `strip_public_ui_prefix`（直连 `:8012/tools/rosbag-labels/` 可加载 JS） |

旧包 `…-20260908-1.tar` / 更早日期可删，勿混用。

## 镜像内配置

| 路径 | 说明 |
|------|------|
| `/app/shared/config.yaml` | 云侧默认；密钥不写这里 |
| `/app/.build_revision` | `app_revision=20260909-1` |
| 运行配置 | 用 `-e` / `env_file`（镜像内通常无 `/app/.env`） |

启动仍会校验 `ODPS_*` + `OSS_BUCKET`（本地模式也可填占位）。

## 权限

```bash
sudo docker …   # 或 usermod -aG docker ecs-user 后重登
```

## 加载

```bash
sudo docker load -i ~/rosbag-to-labels-hmi-20260909-1.tar
sudo docker images | grep rosbag-to-labels-hmi
```

## 内网 AI 网关（OpenAI 兼容）

```bash
-e LLM_PROVIDER=aigw \
-e AIGW_BASE_URL=https://ali.aigw.csvw.com/model/ark/llm/master-agent/v1 \
-e AIGW_API_KEY='你的Bearer' \
-e AIGW_MODEL=ep-20260804101318-bdd5v
```

可选：`OMNI_PROVIDER` / `ASR_PROVIDER` / `EMBEDDING_PROVIDER`；`AIGW_OMNI_MODEL` 等。

## 启动（本地模式 + aigw 示例）

```bash
sudo docker rm -f dataplatform
mkdir -p ~/hmi_runtime ~/hmi_app_meta

sudo docker run -d --name dataplatform --restart unless-stopped \
  -p 8012:8000 \
  -e HMI_DATA_SOURCE=local \
  -e HMI_TEST_MODE=1 \
  -e HMI_JWT_SECRET='change-me-to-a-long-random-string' \
  -e HMI_RUNTIME_ROOT=/app/data/hmi_runtime \
  -e HMI_PUBLIC_API_BASE=/tools/rosbag-labels/api \
  -e HMI_LOCAL_SDK_POLL_ENABLED=1 \
  -e HMI_OSS_SYNC_POLL_ENABLED=0 \
  -e HMI_MIRROR_ARTIFACTS_TO_OSS=0 \
  -e ODPS_PROJECT=local_placeholder \
  -e ODPS_ENDPOINT=https://service.cn-shanghai.maxcompute.aliyun.com/api \
  -e ODPS_ACCESS_ID=local_placeholder \
  -e ODPS_ACCESS_KEY=local_placeholder \
  -e OSS_BUCKET=local-placeholder-bucket \
  -e OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com \
  -e CLOUD_REGION=cn_shanghai \
  -e LLM_PROVIDER=aigw \
  -e AIGW_BASE_URL=https://ali.aigw.csvw.com/model/ark/llm/master-agent/v1 \
  -e AIGW_API_KEY='你的Bearer' \
  -e AIGW_MODEL=ep-20260804101318-bdd5v \
  -v ~/hmi_runtime:/app/data/hmi_runtime \
  -v ~/hmi_app_meta:/app/hmi/data \
  rosbag-to-labels-hmi:20260909-1

sudo docker logs dataplatform --tail 40
curl -fsS http://127.0.0.1:8012/api/health
```

浏览器：`http://<IP>:8012/tools/rosbag-labels/`（直连 8012 需要后端剥 `/tools/rosbag-labels` 前缀；旧镜像只有标题、JS 当 HTML 时请换含 `strip_public_ui_prefix` 的新包）。

```bash
sudo docker exec dataplatform python /app/hmi/scripts/bootstrap_admin.py
```

## 注意

- 保持 `HMI_DATA_SOURCE=local`，关 OSS 同步。
- 前端路径带 `/tools/rosbag-labels/`。
- 本 tar **勿提交 git**。
