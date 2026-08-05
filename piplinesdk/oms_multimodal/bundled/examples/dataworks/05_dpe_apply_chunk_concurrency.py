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
  3. ``DataFrame.apply``（一行调一次）和 ``DataFrame.mf.apply_chunk``（一次吃多行）的区别
  4. 两个关键并发旋钮：
       - batch_rows     ：每个 chunk UDF 调用处理几行
       - dpe_parallel   ：把输入拆成多少个分区，以便多个 Worker 并行
  5. 如何在 chunk UDF 里调用本 SDK 的 ``run_stages``

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
# │ 概念图                                                                     │
# │                                                                            │
# │   DataWorks PyODPS3 节点                                                   │
# │   ┌──────────────────────────────┐                                         │
# │   │ Driver（本机脚本进程）          │  组参数、建 DataFrame、提交任务、取结果   │
# │   │  new_session(o)              │                                         │
# │   │  input_df.mf.apply_chunk(...)│──── 序列化 UDF + 数据 ────► MaxCompute    │
# │   └──────────────────────────────┘                                         │
# │                                         │                                  │
# │                                         ▼                                  │
# │                              ┌─────────────────────┐                       │
# │                              │ DPE Worker（远端）     │  真正读 OSS、跑 SDK    │
# │                              │  执行你的 UDF 函数     │                       │
# │                              └─────────────────────┘                       │
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


def _teaching_notes_only() -> None:
    """仅文档用，不会被调用。说明两个并发参数如何配合。"""
    #
    # 假设输入有 8 行（8 个 bag / 8 个任务）：
    #
    #   dpe_parallel=4, batch_rows=2
    #   ────────────────────────────────
    #   先 rebalance 成约 4 个分区（尽量让多个 Worker 同时开工）
    #   每个分区里，apply_chunk 按 batch_rows=2 把行打包：
    #     WorkerA: 处理 [行0, 行1]
    #     WorkerB: 处理 [行2, 行3]
    #     ...
    #
    #   batch_rows=1
    #   ────────────────────────────────
    #   每次 UDF 只处理 1 行。调试 / 调用大模型时更稳妥（失败面小）。
    #   生产探针也常先用 1。
    #
    #   batch_rows 越大：
    #     + 调度次数更少，吞吐可能更高
    #     - 单个 UDF 失败影响的行更多；内存峰值更高
    #
    #   dpe_parallel 越大：
    #     + 更能吃满集群并行度（前提是有足够 Worker / 配额）
    #     - 分区过多时，单分区行太少，收益下降；也可能抢同一模型配额
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
    """构造 chunk UDF：一次收到多行（行数 ≈ batch_rows），返回同样多行。

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
    """Driver 入口：组输入 → 提交 DPE → 取回结果。"""
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

    # 并发相关（本示例的核心）
    batch_rows = get_int_arg("batch_rows", 1)
    # dpe_parallel：希望拆成多少个分区（多个 Worker 并行）
    # 实际分区数不会超过「输入行数」
    dpe_parallel = get_int_arg("dpe_parallel", 2)

    sdk_stages = get_arg("stages", "extract,asr") or "extract,asr"
    mode = (get_arg("demo_mode", DEMO_MODE) or DEMO_MODE).strip().lower()

    if batch_rows < 1:
        raise ValueError("batch_rows 必须 >= 1")
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

    # ---------- OSS 挂载 ----------
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

    # ---------- 构造输入表：一行 = 一个任务 ----------
    # 真实项目里这些行来自「发现 bag」或上游调度；这里写死 2 行方便演示并发。
    job_rows = [
        {
            "clip_id": get_arg("clip_id_0", "demo-clip-0"),
            "run_id": get_arg("run_id_0", "demo-run-0"),
            "bag_oss_key": get_arg("bag_oss_key_0", "rosbags/demo/output.bag"),
            "run_relpath": get_arg("run_relpath_0", "pipeline/dpe_demo/runs/0"),
            "output_relpath": get_arg("run_relpath_0", "pipeline/dpe_demo/runs/0"),
        },
        {
            "clip_id": get_arg("clip_id_1", "demo-clip-1"),
            "run_id": get_arg("run_id_1", "demo-run-1"),
            "bag_oss_key": get_arg("bag_oss_key_1", "rosbags/demo/output.bag"),
            "run_relpath": get_arg("run_relpath_1", "pipeline/dpe_demo/runs/1"),
            "output_relpath": get_arg("run_relpath_1", "pipeline/dpe_demo/runs/1"),
        },
    ]

    input_df = md.DataFrame(pd.DataFrame(job_rows))

    # ---------- 并发设置①：rebalance → 多分区，便于多 Worker 并行 ----------
    # 分区数取 min(你想要的并行度, 行数)，避免空分区
    parallel = min(dpe_parallel, len(job_rows))
    if parallel > 1:
        input_df = input_df.mf.rebalance(num_partitions=parallel)

    print(
        json.dumps(
            {
                "mode": mode,
                "rows": len(job_rows),
                "batch_rows": batch_rows,
                "dpe_parallel_requested": dpe_parallel,
                "partitions": parallel,
                "hint": (
                    "partitions 大致决定能有多少 Worker 同时开工；"
                    "batch_rows 决定每个 Worker 单次 UDF 吃几行。"
                ),
            },
            ensure_ascii=False,
        )
    )

    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")

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
            # 并发设置②：batch_rows
            #   =1 → 每次 UDF 处理 1 行（调试 / 大模型探针常用）
            #   >1 → 每次 UDF 循环处理多行（吞吐更高，失败面更大）
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
            "  batch_rows（建议先 1）\n"
            "  dpe_parallel（建议先 2，且不超过任务行数）\n"
            "  demo_mode=chunk 或 row\n"
            "生产完整实现见 pipeline/dataworks/sdk_pipeline_driver_node.py"
        )
        _teaching_notes_only()
    else:
        main()
