#!/usr/bin/env python3
"""示例 05：DataWorks 里如何写 DPE UDF，以及 apply_chunk 的并发参数。

【重要】
  本文件是「教学 / 粘贴」示例，需要在阿里云 DataWorks 的 **PyODPS3** 节点里运行。
  本机直接 `python 05_....py` 通常会失败，因为：
    - 没有 DataWorks 注入的全局对象 ``o``（ODPS 入口）和 ``args``（节点参数）
    - 需要 MaxFrame、已登记的 DPE 镜像、可挂载的 OSS 桶

【你会学到】
  1. Driver（调度进程）和 DPE Worker（真正干活的进程）分别是什么
  2. 什么是 UDF（User-Defined Function，用户自定义函数）
  3. **发现 bag（discover）**：Driver 列 OSS → DPE ``apply_chunk`` 算 SHA256 → ``clip_id``
  4. ``DataFrame.apply``（一行调一次）和 ``DataFrame.mf.apply_chunk``（一次吃多行）的区别
  5. 两个关键并发旋钮：
       - batch_rows / hash_batch_rows ：每个 chunk UDF 调用处理几行
       - dpe_parallel                 ：把输入拆成多少个分区，以便多个 Worker 并行
  6. 如何在 pipeline chunk UDF 里调用本 SDK 的 ``run_stages``

【建议阅读顺序】
  先读本文件顶部注释与 ``main()``，再对照生产代码：
    pipeline/dataworks/sdk_pipeline_driver_node.py
    pipeline/dataworks/sdk_dpe_common.py
"""
from __future__ import annotations

# =============================================================================
# 下面从「概念」到「可粘贴代码」。粘贴到 DataWorks 时，可从「可运行骨架」一节开始复制。
# =============================================================================

#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │ 概念图（生产 Driver = 两次 apply_chunk）                                    │
# │                                                                            │
# │   DataWorks PyODPS3 节点（Driver）                                         │
# │   ┌────────────────────────────────────────────────────────────────────┐   │
# │   │ ① 发现 bag                                                          │   │
# │   │    Driver: 列举 OSS ``rosbags/**/*.bag``                             │   │
# │   │    DPE:    apply_chunk(hash) 读挂载文件算 SHA256                      │   │
# │   │            → clip_id = "sha256:{hex}"                                │   │
# │   │ ② 跑流水线                                                          │   │
# │   │    DPE:    apply_chunk(pipeline) 调 SDK run_stages                   │   │
# │   └────────────────────────────────────────────────────────────────────┘   │
# │                         │                                                  │
# │                         ▼                                                  │
# │              ┌─────────────────────┐                                       │
# │              │ DPE Worker（远端）     │  挂载 OSS、hash / 跑 SDK             │
# │              └─────────────────────┘                                       │
# └──────────────────────────────────────────────────────────────────────────┘
#
# UDF = User-Defined Function（用户自定义函数）
#   写在节点脚本里的普通 Python 函数，经 MaxFrame 发送到 DPE Worker 执行。
#
# 禁止在 UDF 里使用：
#   - @dataclass / 自定义 class / NamedTuple / Enum
#   （Worker 端无法反序列化节点脚本里定义的类）
# 请只用：dict / list / 内置类型。
#

DEMO_MODE = "chunk"  # "row" = 一行一次 apply；"chunk" = apply_chunk（推荐批量）
# discover 来源：
#   auto = 扫 OSS scan_prefix（默认 rosbags/）
#   keys = 用参数 bag_oss_keys（逗号/换行分隔）
#   demo = 写死 2 行假数据（不访问 OSS 列举，适合只练 apply 语法）
DISCOVER_MODE = "auto"


def _teaching_notes_only() -> None:
    """仅文档用，不会被调用。说明发现 + 并发参数如何配合。"""
    #
    # 发现（discover）两步：
    #   1) Driver 用 AK/SK 列对象键：rosbags/xxx/output.bag
    #   2) DPE hash UDF 在挂载路径 /mnt/oss/rosbags/... 上读文件算 SHA256
    #      clip_id 必须来自内容 hash，不要用路径名当 ID
    #
    # 假设扫到 8 个 bag：
    #
    #   hash 阶段：hash_batch_rows=32 → 通常一次 chunk 吃完（或按批切）
    #   pipeline 阶段：dpe_parallel=4, batch_rows=2
    #   ────────────────────────────────
    #   先 rebalance 成约 4 个分区
    #   每个分区里 apply_chunk 按 batch_rows=2 打包：
    #     WorkerA: 处理 [行0, 行1]
    #     WorkerB: 处理 [行2, 行3]
    #     ...
    #
    #   batch_rows=1：调试 / 大模型探针更稳妥（失败面小）
    #   hash_batch_rows 可更大：hash 是纯 IO/CPU，吞吐优先
    #
    pass


# =============================================================================
# 可运行骨架（粘贴到 DataWorks PyODPS3）
# =============================================================================

def get_arg(name: str, default: str | None = None) -> str | None:
    """读取 DataWorks 节点参数。本机没有 ``args`` 时返回 default。"""
    try:
        value = args.get(name)  # type: ignore[name-defined]
    except NameError:
        value = None
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def get_int_arg(name: str, default: int) -> int:
    raw = get_arg(name)
    return default if raw is None else int(raw)


# ---------- 0) 发现 bag：Driver 列举 OSS 对象键 ----------

def parse_bag_oss_keys(raw: str | None) -> list[str]:
    """把参数 ``bag_oss_keys`` 拆成键列表（逗号或换行分隔）。"""
    import re

    if not raw or not str(raw).strip():
        return []
    return [
        key.strip()
        for key in re.split(r"[\r\n,]+", str(raw))
        if key.strip().lower().endswith(".bag")
    ]


def list_bag_keys_from_oss(
    *,
    access_key_id: str,
    access_key_secret: str,
    oss_bucket: str,
    cloud_region: str,
    scan_prefix: str = "rosbags/",
    max_scan: int = 1000,
    oss_endpoint: str | None = None,
) -> list[str]:
    """Driver 侧列举 ``{scan_prefix}**/*.bag``（不读文件内容）。

    教学示例用 ``oss2``；生产节点也可用 ``oss_v2_dw.iter_object_keys``（同语义）。
    """
    import oss2

    # 外网 endpoint 给 Driver 列举；DPE 挂载用内网 URL（见 main）
    endpoint = (
        (oss_endpoint or "").strip()
        or f"https://oss-{cloud_region.replace('_', '-')}.aliyuncs.com"
    )
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, oss_bucket)
    prefix = (scan_prefix or "rosbags/").lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    keys: list[str] = []
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        key = str(getattr(obj, "key", "") or "")
        if not key.lower().endswith(".bag"):
            continue
        keys.append(key)
        if len(keys) >= max_scan:
            break
    keys.sort()
    return keys


def content_hash_to_clip_id(hex_digest: str) -> str:
    digest = hex_digest.strip().lower().removeprefix("sha256:")
    return f"sha256:{digest}"


# ---------- 0b) 发现 bag：DPE hash chunk（读挂载文件算 SHA256） ----------

def build_hash_chunk_udf(*, oss_mount_url: str, mount_path: str, storage_options: dict):
    """构造「发现」用的 chunk UDF：每行一个 bag_oss_key → clip_id / content_hash。

    与生产 ``sdk_pipeline_driver_node._build_hash_chunk_udf`` 同思路。
    """
    from pathlib import Path

    import pandas as pd
    from maxframe.udf import with_fs_mount, with_running_options

    def _hash_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
        import hashlib

        rows_out: list[dict] = []
        for _, row in chunk.iterrows():
            bag_oss_key = str(row["bag_oss_key"]).lstrip("/")
            bag_path = Path(mount_path) / bag_oss_key
            hasher = hashlib.sha256()
            # 流式读，避免大 bag 一次性进内存
            with bag_path.open("rb") as bag_file:
                while True:
                    block = bag_file.read(1024 * 1024)
                    if not block:
                        break
                    hasher.update(block)
            content_hash = hasher.hexdigest()
            rows_out.append(
                {
                    "clip_id": content_hash_to_clip_id(content_hash),
                    "bag_oss_key": bag_oss_key,
                    "content_hash": content_hash,
                }
            )
        return pd.DataFrame(rows_out)

    # hash 偏 IO，CPU/内存可低于 pipeline 阶段
    fn = with_running_options(engine="dpe", cpu=2, memory=8)(_hash_chunk)
    fn = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(fn)
    return fn


def discover_bags_via_hash(
    *,
    bag_keys: list[str],
    md,
    pd,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict,
    hash_batch_rows: int,
    dpe_parallel: int,
) -> list[dict]:
    """Driver：把 bag 键表提交给 DPE hash，取回 clip_id 列表。"""
    if not bag_keys:
        raise ValueError("discover: bag_keys 为空（检查 scan_prefix / bag_oss_keys）")

    hash_input = md.DataFrame(pd.DataFrame([{"bag_oss_key": key} for key in bag_keys]))
    parallel = min(max(dpe_parallel, 1), len(bag_keys))
    if parallel > 1:
        hash_input = hash_input.mf.rebalance(num_partitions=parallel)

    hash_udf = build_hash_chunk_udf(
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=storage_options,
    )
    hash_result = (
        hash_input.mf.apply_chunk(
            hash_udf,
            batch_rows=max(hash_batch_rows, 1),
            output_type="dataframe",
            dtypes={
                "clip_id": "string",
                "bag_oss_key": "string",
                "content_hash": "string",
            },
            skip_infer=True,
        )
        .execute()
        .fetch()
    )
    discovered: list[dict] = []
    for _, row in hash_result.iterrows():
        discovered.append(
            {
                "clip_id": str(row["clip_id"]),
                "bag_oss_key": str(row["bag_oss_key"]),
                "content_hash": str(row["content_hash"]),
            }
        )
    return discovered


def build_job_rows_from_discovered(
    discovered: list[dict],
    *,
    max_bags: int | None,
    run_id_prefix: str = "demo-run",
) -> list[dict]:
    """把发现结果变成 pipeline apply_chunk 的输入行（每 bag 一个 run_id）。"""
    import uuid

    bags = list(discovered)
    bags.sort(key=lambda item: str(item.get("bag_oss_key") or ""))
    if max_bags is not None:
        bags = bags[: max(0, max_bags)]

    job_rows: list[dict] = []
    for index, bag in enumerate(bags):
        clip_id = str(bag["clip_id"])
        run_id = str(bag.get("run_id") or f"{run_id_prefix}-{uuid.uuid4().hex[:8]}")
        bag_oss_key = str(bag["bag_oss_key"])
        run_relpath = f"clips/{clip_id}/runs/{run_id}"
        job_rows.append(
            {
                "clip_id": clip_id,
                "run_id": run_id,
                "bag_oss_key": bag_oss_key,
                "run_relpath": run_relpath,
                "output_relpath": run_relpath,
                "content_hash": str(bag.get("content_hash") or ""),
            }
        )
        _ = index  # 保留枚举以便读者扩展过滤逻辑
    return job_rows


# ---------- A) 一行一次：DataFrame.apply（入门） ----------

def build_row_udf(*, oss_mount_url: str, mount_path: str, storage_options: dict):
    """构造「一行调用一次」的 UDF。

    函数签名约定：接收 pandas.Series（一行），返回 dict（展开成输出列）。
    """
    import pandas as pd
    from pathlib import Path
    from maxframe.udf import with_fs_mount, with_running_options

    def _process_one_row(row: pd.Series) -> dict:
        # 在 DPE Worker 上执行：挂载点 mount_path 下能直接看到 OSS 对象
        clip_id = str(row["clip_id"])
        rel = str(row["output_relpath"])
        out = Path(mount_path) / rel / "hello_row.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"clip_id={clip_id}\n", encoding="utf-8")
        # 只能返回内置类型组成的 dict
        return {
            "clip_id": clip_id,
            "ok": True,
            "output_relpath": rel,
            "bytes_written": int(out.stat().st_size),
        }

    # 装饰器：
    #   with_running_options —— 指定跑在 DPE，并给出 CPU/内存
    #   with_fs_mount        —— 把 OSS 桶挂到 Worker 本地路径
    fn = with_running_options(engine="dpe", cpu=1, memory=4)(_process_one_row)
    fn = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(fn)
    return fn


# ---------- B) 一次多行：DataFrame.mf.apply_chunk（批量 / 并发主路径） ----------

def build_chunk_udf(*, oss_mount_url: str, mount_path: str, storage_options: dict, sdk_stages: str):
    """构造 pipeline chunk UDF：一次收到多行（行数 ≈ batch_rows），返回同样多行。

    MaxFrame 会把输入按 batch_rows 切成块，每块调用本函数一次。
    """
    import os
    from pathlib import Path

    import pandas as pd
    from maxframe.udf import with_fs_mount, with_running_options

    def _process_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
        # chunk：本批的多行输入（列与 Driver 构造的 DataFrame 一致）
        rows_out: list[dict] = []

        for _, row in chunk.iterrows():
            clip_id = str(row["clip_id"])
            run_id = str(row["run_id"])
            bag_rel = str(row["bag_oss_key"])          # 例如 rosbags/xxx/output.bag
            run_rel = str(row["run_relpath"])           # 例如 clips/.../runs/...
            bag_path = Path(mount_path) / bag_rel
            run_dir = Path(mount_path) / run_rel

            ok = True
            error = ""
            stages_done = ""

            try:
                if not bag_path.is_file():
                    raise FileNotFoundError(f"挂载路径下找不到 bag: {bag_path}")

                # ---- 可选：在 UDF 内调用本 SDK（需 DPE 镜像已安装 oms-multimodal-sdk）----
                # 下面这段演示「如何接线」；若镜像没有 SDK，可先注释掉，只写标记文件。
                use_sdk = str(os.environ.get("DEMO_USE_SDK", "0")).lower() in {
                    "1",
                    "true",
                    "yes",
                }
                if use_sdk:
                    # 把 Driver 注入的环境变量留给 SDK（MODEL_BACKEND 等）
                    from oms_multimodal import (
                        ClipConfig,
                        OmsMultimodalClient,
                        bundled_taxonomy_path,
                        parse_stages,
                        run_stages,
                    )

                    run_dir.mkdir(parents=True, exist_ok=True)
                    client = OmsMultimodalClient(
                        taxonomy_path=bundled_taxonomy_path(),
                        work_dir=run_dir / "_sdk_work",
                        load_dotenv=False,
                        model_backend=os.environ.get("MODEL_BACKEND", "api"),
                    )
                    ctx = client.make_run_context(
                        run_dir,
                        media_mode="local",
                        clip_id=clip_id,
                        run_id=run_id,
                    )
                    try:
                        result = run_stages(
                            ctx,
                            bag_path,
                            client,
                            stages=parse_stages(sdk_stages),
                            clip_config=ClipConfig(min_sec=15, max_sec=20, sample_fps=1.0),
                            model_backend=os.environ.get("MODEL_BACKEND", "api"),
                        )
                        stages_done = ",".join(result.stages_done)
                    finally:
                        client.close()
                else:
                    # 最小演示：不调 SDK，只写一个标记文件，证明 Worker 能写 OSS 挂载
                    run_dir.mkdir(parents=True, exist_ok=True)
                    marker = run_dir / "dpe_chunk_ok.txt"
                    marker.write_text(
                        f"clip_id={clip_id}\nrun_id={run_id}\nbag={bag_rel}\n",
                        encoding="utf-8",
                    )
                    stages_done = "demo_marker"

            except Exception as exc:  # noqa: BLE001 — 行级隔离：单行失败不拖垮整批
                ok = False
                error = f"{type(exc).__name__}: {exc}"

            rows_out.append(
                {
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "ok": ok,
                    "error": error,
                    "stages_done": stages_done,
                    "run_relpath": run_rel,
                }
            )

        # apply_chunk 要求返回 DataFrame，行数通常与输入 chunk 一致
        return pd.DataFrame(rows_out)

    # CPU/内存按单任务体量估算；真正并发度还受分区数、集群配额影响
    fn = with_running_options(engine="dpe", cpu=4, memory=16)(_process_chunk)
    fn = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(fn)
    return fn


def main() -> None:
    """Driver 入口：发现 bag →（可选）pipeline apply_chunk → 取回结果。"""
    import json

    import maxframe.dataframe as md
    import pandas as pd
    from maxframe.config import options as mf_options
    from maxframe.session import new_session

    # ---------- 读取节点参数（在 DataWorks「参数」面板配置） ----------
    oss_bucket = get_arg("oss_bucket") or ""
    if not oss_bucket:
        raise ValueError("请配置节点参数 oss_bucket=你的OSS桶名")

    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    mount_path = get_arg("mount_path", "/mnt/oss") or "/mnt/oss"
    dpe_image = get_arg("dpe_image")  # MaxCompute 已登记的镜像名；空则用平台默认
    role_arn = get_arg("oss_ram_role_arn")  # 推荐：用 RAM 角色挂载 OSS

    # 并发相关
    batch_rows = get_int_arg("batch_rows", 1)
    hash_batch_rows = get_int_arg("hash_batch_rows", 32)
    dpe_parallel = get_int_arg("dpe_parallel", 2)

    sdk_stages = get_arg("stages", "extract,asr") or "extract,asr"
    mode = (get_arg("demo_mode", DEMO_MODE) or DEMO_MODE).strip().lower()
    discover_mode = (get_arg("discover_mode", DISCOVER_MODE) or DISCOVER_MODE).strip().lower()
    scan_prefix = get_arg("scan_prefix", "rosbags/") or "rosbags/"
    max_scan = get_int_arg("max_scan", 1000)
    max_bags_raw = get_arg("max_bags")
    max_bags = int(max_bags_raw) if max_bags_raw else None
    # skip_pipeline=1 时只跑发现（hash），便于单独验证 discover
    skip_pipeline = (get_arg("skip_pipeline", "0") or "0").lower() in {"1", "true", "yes"}

    if batch_rows < 1:
        raise ValueError("batch_rows 必须 >= 1")
    if hash_batch_rows < 1:
        raise ValueError("hash_batch_rows 必须 >= 1")
    if dpe_parallel < 1:
        raise ValueError("dpe_parallel 必须 >= 1")

    # ---------- 强制使用 DPE 引擎 ----------
    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        # 告诉 MaxCompute：Worker 用哪套自定义镜像（需已在 MC 控制台登记）
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings
    mf_options.local_execution.enabled = False

    # ---------- OSS 挂载（DPE）+ 列举用凭证（Driver） ----------
    account = o.account  # type: ignore[name-defined]
    oss_mount_url = f"oss://{oss_bucket}.oss-{cloud_region}-internal.aliyuncs.com/"
    if role_arn:
        storage_options = {"oss_role_arn": role_arn}
    else:
        # 调试可用 AK；生产更推荐 RAM 角色
        storage_options = {
            "oss_access_key_id": account.access_id,
            "oss_access_key_secret": account.secret_access_key,
        }

    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")

        # ========== ① 发现 bag ==========
        if discover_mode == "demo":
            # 不扫 OSS、不算 hash：只练 apply 语法时用
            discovered = [
                {
                    "clip_id": get_arg("clip_id_0", "demo-clip-0"),
                    "bag_oss_key": get_arg("bag_oss_key_0", "rosbags/demo/output.bag"),
                    "content_hash": "",
                    "run_id": get_arg("run_id_0", "demo-run-0"),
                },
                {
                    "clip_id": get_arg("clip_id_1", "demo-clip-1"),
                    "bag_oss_key": get_arg("bag_oss_key_1", "rosbags/demo/output.bag"),
                    "content_hash": "",
                    "run_id": get_arg("run_id_1", "demo-run-1"),
                },
            ]
            print("DISCOVER_MODE=demo（跳过 OSS 列举与 hash）")
        else:
            if discover_mode == "keys":
                bag_keys = parse_bag_oss_keys(get_arg("bag_oss_keys"))
            else:
                # auto：Driver 列举对象键
                bag_keys = list_bag_keys_from_oss(
                    access_key_id=str(account.access_id),
                    access_key_secret=str(account.secret_access_key),
                    oss_bucket=oss_bucket,
                    cloud_region=cloud_region,
                    scan_prefix=scan_prefix,
                    max_scan=max_scan,
                    oss_endpoint=get_arg("oss_endpoint"),
                )
                # 也允许用 bag_oss_keys 追加 / 覆盖调试
                extra = parse_bag_oss_keys(get_arg("bag_oss_keys"))
                if extra:
                    bag_keys = sorted(set(bag_keys) | set(extra))

            print(
                "DISCOVER_LIST_JSON="
                + json.dumps(
                    {
                        "discover_mode": discover_mode,
                        "scan_prefix": scan_prefix,
                        "bag_count": len(bag_keys),
                        "bag_keys": bag_keys[:20],
                        "truncated": len(bag_keys) > 20,
                    },
                    ensure_ascii=False,
                )
            )
            discovered = discover_bags_via_hash(
                bag_keys=bag_keys,
                md=md,
                pd=pd,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=storage_options,
                hash_batch_rows=hash_batch_rows,
                dpe_parallel=dpe_parallel,
            )

        job_rows = build_job_rows_from_discovered(
            discovered,
            max_bags=max_bags,
            run_id_prefix=get_arg("run_id_prefix", "demo-run") or "demo-run",
        )
        print(
            "DISCOVERED_ROWS_JSON="
            + json.dumps(
                {
                    "hashed_or_demo_count": len(discovered),
                    "runnable": len(job_rows),
                    "items": job_rows,
                },
                ensure_ascii=False,
            )
        )

        if skip_pipeline:
            print("skip_pipeline=1：只完成发现，不跑 pipeline apply_chunk")
            return
        if not job_rows:
            print("没有可跑的 bag（max_bags 过滤后为空）")
            return

        # ========== ② pipeline apply / apply_chunk ==========
        input_df = md.DataFrame(pd.DataFrame(job_rows))

        # 并发设置①：rebalance → 多分区，便于多 Worker 并行
        parallel = min(dpe_parallel, len(job_rows))
        if parallel > 1:
            input_df = input_df.mf.rebalance(num_partitions=parallel)

        print(
            json.dumps(
                {
                    "mode": mode,
                    "rows": len(job_rows),
                    "batch_rows": batch_rows,
                    "hash_batch_rows": hash_batch_rows,
                    "dpe_parallel_requested": dpe_parallel,
                    "partitions": parallel,
                    "hint": (
                        "发现阶段用 hash_batch_rows；"
                        "流水线阶段 partitions≈并行 Worker 数，batch_rows=每 Worker 单次吃几行。"
                    ),
                },
                ensure_ascii=False,
            )
        )

        if mode == "row":
            # ---- 模式 A：一行一次 ----
            udf = build_row_udf(
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=storage_options,
            )
            result_df = input_df.apply(
                udf,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "ok": "boolean",
                    "output_relpath": "string",
                    "bytes_written": "int64",
                },
                skip_infer=True,
            )
        else:
            # ---- 模式 B：apply_chunk（推荐）----
            udf = build_chunk_udf(
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=storage_options,
                sdk_stages=sdk_stages,
            )
            result_df = input_df.mf.apply_chunk(
                udf,
                batch_rows=batch_rows,
                output_type="dataframe",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "ok": "boolean",
                    "error": "string",
                    "stages_done": "string",
                    "run_relpath": "string",
                },
                skip_infer=True,
            )

        # execute：提交到 MaxCompute；fetch：把结果拉回 Driver
        out = result_df.execute().fetch()
        print("RESULT_JSON=" + out.to_json(orient="records", force_ascii=False))

    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    # 本机直接运行只会打印提示；真正执行请粘贴到 DataWorks
    try:
        o  # type: ignore[name-defined]  # noqa: F401
    except NameError:
        print(
            "本脚本需在 DataWorks PyODPS3 节点中运行（需要全局对象 o / args）。\n"
            "请打开本文件阅读注释，或把 main() 及相关函数粘贴到节点后配置参数：\n"
            "  oss_bucket / dpe_image / oss_ram_role_arn\n"
            "  discover_mode=auto|keys|demo\n"
            "  scan_prefix=rosbags/   （auto）\n"
            "  bag_oss_keys=rosbags/a.bag,rosbags/b.bag   （keys 或 auto 追加）\n"
            "  hash_batch_rows（发现阶段，建议 32）\n"
            "  batch_rows（流水线阶段，建议先 1）\n"
            "  dpe_parallel / max_bags / skip_pipeline=1（只验发现）\n"
            "  demo_mode=chunk 或 row\n"
            "生产完整实现见 pipeline/dataworks/sdk_pipeline_driver_node.py"
        )
        _teaching_notes_only()
    else:
        main()
