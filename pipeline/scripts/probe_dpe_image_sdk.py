#!/usr/bin/env python3
"""Probe MaxCompute DPE image for oms-multimodal-sdk.

Usage (Python 3.11 + maxframe)::

    cd pipeline
    py -3.11 scripts/probe_dpe_image_sdk.py
    py -3.11 scripts/probe_dpe_image_sdk.py --image sq_maxframe
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "pipeline"
for p in (REPO / "shared", PIPELINE / "local_sdk_mc_test", PIPELINE, REPO / "hmi" / "backend"):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


def _load_env() -> None:
    for env_path in (
        PIPELINE / "local_sdk_mc_test" / ".env",
        REPO / ".env",
    ):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=os.environ.get("DPE_IMAGE", "sq_maxframe"))
    args = parser.parse_args()
    _load_env()

    access_id = os.environ.get("ODPS_ACCESS_ID", "")
    access_key = os.environ.get("ODPS_ACCESS_KEY", "")
    project = os.environ.get("ODPS_PROJECT", "rogbag_label_pipline")
    endpoint = os.environ.get(
        "ODPS_ENDPOINT",
        "https://service.cn-shanghai.maxcompute.aliyun.com/api",
    )
    if not access_id or not access_key:
        raise SystemExit("ODPS_ACCESS_ID/KEY missing (local_sdk_mc_test/.env or root .env)")

    from odps import ODPS
    import maxframe.dataframe as md
    import pandas as pd
    from maxframe.config import options as mf_options
    from maxframe.session import new_session
    from maxframe.udf import with_running_options

    o = ODPS(access_id, access_key, project=project, endpoint=endpoint)
    dpe_image = str(args.image).strip()
    print(json.dumps({"probe": "dpe_image_sdk", "dpe_image": dpe_image, "project": project}, ensure_ascii=False))

    def _probe_row(row: pd.Series) -> dict:
        del row  # unused; one-row probe
        out: dict = {
            "ok": False,
            "sdk_version": "",
            "has_content_parts": False,
            "has_rosbags": False,
            "error": "",
            "python": "",
        }
        try:
            import sys as _sys

            out["python"] = _sys.version.split()[0]
            import rosbags  # noqa: F401

            out["has_rosbags"] = True
            import oms_multimodal
            from oms_multimodal.mc import content_parts

            out["sdk_version"] = str(oms_multimodal.__version__)
            out["has_content_parts"] = hasattr(content_parts, "build_omni_label_parts")
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    udf = with_running_options(engine="dpe", cpu=1, memory=4)(_probe_row)

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings
    mf_options.local_execution.enabled = False

    session = new_session(o)
    try:
        print(f"Logview: {session.get_logview_address()}")
        input_df = md.DataFrame(pd.DataFrame([{"probe_id": "sdk"}]))
        result_df = input_df.apply(
            udf,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "ok": "bool",
                "sdk_version": "string",
                "has_content_parts": "bool",
                "has_rosbags": "bool",
                "error": "string",
                "python": "string",
            },
            skip_infer=True,
        )
        out = result_df.execute().fetch()
        row = out.iloc[0].to_dict()
        print("PROBE_RESULT=" + json.dumps(row, ensure_ascii=False, default=str))
        if not row.get("ok"):
            raise SystemExit(f"SDK missing or import failed in image {dpe_image!r}: {row.get('error')}")
        print(f"OK: image={dpe_image} sdk={row.get('sdk_version')} content_parts={row.get('has_content_parts')}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
