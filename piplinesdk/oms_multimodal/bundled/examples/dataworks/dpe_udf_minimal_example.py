# =============================================================================
# 最简示范：PyODPS3 Driver 如何调用 DPE UDF
# 粘贴整文件到 DataWorks PyODPS3 节点即可理解调用链。
#
# 调用链（3 步）：
#   1. Driver：new_session(o) 创建 MaxFrame 会话
#   2. Driver：input_df.apply(udf, axis=1) 把 UDF 提交到 DPE
#   3. DPE worker：udf(row) 在挂载的 OSS 上执行，返回 dict → Driver fetch 结果
#
# 工作流参数：oss_bucket, cloud_region, dpe_image（可选）
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options


def get_arg(name: str, default: str | None = None) -> str | None:
    try:
        v = args.get(name)  # type: ignore[name-defined]
    except NameError:
        v = None
    return default if not v or not str(v).strip() else str(v).strip()


# ── ① 定义 UDF：在 DPE worker 里跑（可读写 OSS 挂载路径）────────────────────

def _build_my_udf(*, oss_mount_url: str, mount_path: str, storage_options: dict):
    def _my_row(row: pd.Series) -> dict:
        # row 是 Driver 传入的一行参数（dict/Series）
        target = Path(mount_path) / str(row["output_relpath"]) / "hello.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"clip_id={row['clip_id']}\n", encoding="utf-8")
        return {
            "clip_id": str(row["clip_id"]),
            "bytes_written": target.stat().st_size,
            "output_relpath": str(row["output_relpath"]),
        }

    # 装饰器顺序：先 DPE 资源，再 OSS 挂载（与 Job1 一致）
    fn = with_running_options(engine="dpe", cpu=1, memory=4)(_my_row)
    fn = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(fn)
    return fn


# ── ② Driver：组 1 行输入，apply UDF，取回结果 ─────────────────────────────

def main() -> None:
    account = o.account  # type: ignore[name-defined]
    oss_bucket = get_arg("oss_bucket", "rosbag-labels-pipline-bucket")
    region = get_arg("cloud_region", "cn_shanghai")
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_image = get_arg("dpe_image")  # 例如 rosbag_dpe_deps；空则用平台默认镜像

    # OSS 内网挂载 URL（@with_fs_mount 用）
    oss_mount_url = f"oss://{oss_bucket}.oss-{region}-internal.aliyuncs.com/"
    storage_options = {
        "oss_access_key_id": account.access_id,
        "oss_access_key_secret": account.secret_access_key,
    }

    # 强制走 DPE 引擎 + 指定 Python 镜像
    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings
    mf_options.local_execution.enabled = False

    # 传给 DPE 的一行业务参数（可以是 dispatch 里的 clip_id/run_id 等）
    job_row = {
        "clip_id": get_arg("clip_id", "demo-clip"),
        "output_relpath": "pipeline/dpe_demo/output",
    }

    my_udf = _build_my_udf(
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=storage_options,
    )

    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")

        # 关键 API：DataFrame.apply(udf, axis=1) → 每行调用一次 UDF
        input_df = md.DataFrame(pd.DataFrame([job_row]))
        result_df = input_df.apply(
            my_udf,
            axis=1,                    # 按行调用
            output_type="dataframe",   # UDF 返回 dict → 展开成列
            result_type="expand",
            dtypes={                   # 输出列类型（skip_infer 必须显式声明）
                "clip_id": "string",
                "bytes_written": "int64",
                "output_relpath": "string",
            },
            skip_infer=True,
        )

        # execute() 提交到 MaxCompute；fetch() 拉回 Driver
        out = result_df.execute().fetch()
        row = out.iloc[0]
        print(json.dumps({"ok": True, "result": row.to_dict()}, ensure_ascii=False))

    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
