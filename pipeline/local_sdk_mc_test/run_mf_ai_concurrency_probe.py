#!/usr/bin/env python3
# =============================================================================
# Local MaxFrame AI multi-partition concurrency probe (driver bare ASR).
#
# NOT the SDK run_mc_oss_verify serial path. Builds a multi-row DataFrame,
# rebalance(num_partitions=N), and times bare llm.generate (ASR) serial vs concurrent.
# =============================================================================

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DATAWORKS = REPO_ROOT / "pipeline" / "dataworks"
DEFAULT_AUDIO = HERE / "output" / "local_verify_mc" / "preview" / "audio.wav"
DEFAULT_MODEL = "qwen3-asr-flash"
DEFAULT_MODELSET = "bigdata_public_modelset"
DEFAULT_QUOTA = "ai_InferenceQuota"

# dataworks for sdk_driver_bare_asr; local sdk_node_common loaded by file path
# (both packages expose sdk_node_common.py — avoid sys.path shadowing).
if str(DATAWORKS) not in sys.path:
    sys.path.insert(0, str(DATAWORKS))

import importlib.util

_local_common_spec = importlib.util.spec_from_file_location(
    "local_sdk_node_common",
    HERE / "sdk_node_common.py",
)
assert _local_common_spec and _local_common_spec.loader
_local_common = importlib.util.module_from_spec(_local_common_spec)
sys.modules["local_sdk_node_common"] = _local_common
_local_common_spec.loader.exec_module(_local_common)
get_arg = _local_common.get_arg
load_local_env = _local_common.load_local_env


def _load_root_env_nonsecret() -> None:
    """Best-effort load repo-root .env (may be GBK) without overriding local values."""
    root_env = REPO_ROOT / ".env"
    if not root_env.is_file():
        return
    raw = root_env.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return
    for line in text.splitlines():
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        key, value = t.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key not in os.environ or not str(os.environ.get(key, "")).strip():
            os.environ[key] = value


def _resolve_inference_quota() -> str | None:
    for name in (
        "MC_INFERENCE_QUOTA_NAME",
        "AI_INFERENCE_QUOTA_NAME",
        "INFERENCE_QUOTA_NAME",
        "inference_quota_name",
        "MC_AI_CU_QUOTA_NAME",
        "MC_AI_GU_QUOTA_NAME",
        "ai_cu_quota_name",
        "ai_gu_quota_name",
    ):
        val = (get_arg(name) or os.environ.get(name) or "").strip()
        if val:
            return val
    # Match DataWorks workflow-params default when local .env leaves quota empty.
    return DEFAULT_QUOTA


def _build_odps() -> Any:
    from odps import ODPS

    access_id = (os.environ.get("ODPS_ACCESS_ID") or "").strip()
    access_key = (os.environ.get("ODPS_ACCESS_KEY") or "").strip()
    project = (os.environ.get("ODPS_PROJECT") or "rogbag_label_pipline").strip()
    endpoint = (
        os.environ.get("ODPS_ENDPOINT")
        or "https://service.cn-shanghai.maxcompute.aliyun.com/api"
    ).strip()
    if not access_id or not access_key:
        raise SystemExit("ODPS_ACCESS_ID / ODPS_ACCESS_KEY missing (check local_sdk_mc_test/.env)")
    print(f"ODPS project={project} endpoint={endpoint} access_id_set={bool(access_id)}")
    return ODPS(access_id, access_key, project=project, endpoint=endpoint)


def _truncate(text: str, n: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 3] + "..."


def _run_one(
    odps_entry: Any,
    *,
    rows_in: list[dict[str, str]],
    asr_model: str,
    modelset_project: str,
    inference_quota_name: str | None,
    parallel_partitions: int,
    catalog_endpoint: str | None,
) -> dict[str, Any]:
    """Time one bare ASR generate; capture logview + ok/fail per row."""
    label = f"partitions={parallel_partitions}"
    print(f"\n=== RUN {label} rows={len(rows_in)} ===")
    t0 = time.perf_counter()
    logview: str | None = None
    try:
        # Timed variant of sdk_driver_bare_asr.driver_bare_asr_generate (returns logview).
        result = _driver_bare_asr_timed(
            odps_entry,
            rows_in=rows_in,
            asr_model=asr_model,
            modelset_project=modelset_project,
            inference_quota_name=inference_quota_name,
            parallel_partitions=parallel_partitions,
            catalog_endpoint=catalog_endpoint,
        )
        logview = result.get("logview")
        texts = list(result.get("texts") or [])
        ok = sum(1 for t in texts if t and not str(t).startswith("ERROR:"))
        fail = len(rows_in) - ok if texts else len(rows_in)
        return {
            "mode": "serial" if parallel_partitions <= 1 else "concurrent",
            "parallel_partitions": parallel_partitions,
            "elapsed_sec": round(float(result["elapsed_sec"]), 3),
            "ok": ok,
            "fail": fail,
            "texts": texts,
            "sample_texts": [_truncate(t) for t in texts[:3]],
            "logview": logview,
            "error": None,
            "mc_mode": result.get("mc_mode"),
        }
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}"
        print(f"RUN_FAIL {label}: {err}")
        traceback.print_exc()
        fail_logview = logview or getattr(exc, "logview", None)
        return {
            "mode": "serial" if parallel_partitions <= 1 else "concurrent",
            "parallel_partitions": parallel_partitions,
            "elapsed_sec": round(elapsed, 3),
            "ok": 0,
            "fail": len(rows_in),
            "texts": [],
            "sample_texts": [],
            "logview": fail_logview,
            "error": err,
            "mc_mode": None,
        }


def _driver_bare_asr_timed(
    odps_entry: Any,
    *,
    rows_in: list[dict[str, str]],
    asr_model: str,
    modelset_project: str,
    inference_quota_name: str | None,
    parallel_partitions: int,
    catalog_endpoint: str | None,
) -> dict[str, Any]:
    """Same as driver_bare_asr_generate but returns logview + wall elapsed."""
    import pandas as pd
    import maxframe.dataframe as md
    from maxframe.learn.utils import read_odps_model
    from maxframe.session import new_session

    from sdk_driver_bare_asr import (
        _normalize_llm_output,
        configure_driver_mc_ai_session,
        ensure_odps_catalog_for_driver,
    )

    if not rows_in:
        raise FileNotFoundError("no ASR audio rows")

    configure_driver_mc_ai_session(inference_quota_name=inference_quota_name)
    ensure_odps_catalog_for_driver(odps_entry, catalog_endpoint)

    try:
        model_obj = odps_entry.get_model(asr_model, modelset_project, None)
        model_obj.reload()
        fmt = getattr(getattr(model_obj, "type", None), "value", None) or getattr(
            model_obj, "type", "?"
        )
        tasks = list(getattr(model_obj, "tasks", None) or [])
        print(f"DRIVER_ASR_MODEL_META format={fmt} tasks={tasks}")
    except Exception as meta_exc:  # noqa: BLE001
        print(f"DRIVER_ASR_MODEL_META_WARN {type(meta_exc).__name__}: {meta_exc}")

    llm = read_odps_model(asr_model, project=modelset_project, odps_entry=odps_entry)
    clip_ids = [str(r["clip_id"]) for r in rows_in]
    for r in rows_in:
        url = str(r.get("audio_url") or "")
        mode = "b64" if url.startswith("data:") else "oss_url"
        print(
            f"DRIVER_ASR_WAV clip_id={r.get('clip_id')} key={r.get('audio_oss_key')} mode={mode}"
        )

    df = md.DataFrame(pd.DataFrame(rows_in))
    if parallel_partitions > 1:
        npart = min(int(parallel_partitions), len(rows_in))
        print(f"REBALANCE num_partitions={npart}")
        df = df.mf.rebalance(num_partitions=npart)
    else:
        print("REBALANCE skipped (parallel_partitions=1)")

    params: dict[str, Any] = {"asr_options": {"enable_itn": True, "language": "zh"}}
    gen_kwargs: dict[str, Any] = {"simple_output": True, "params": params}

    if hasattr(llm, "content_part"):
        from maxframe.learn.contrib.llm import AudioContentType

        cp = llm.content_part
        audio_part: dict[str, Any] = {
            "data": getattr(df, "audio_url"),
            "type": AudioContentType.URL,
            "mime_type": "audio/wav",
        }
        messages = [{"role": "user", "content": [cp.audio(**audio_part)]}]
        mc_mode = "content_part_audio"
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": "{audio_url}"}}
                ],
            }
        ]
        mc_mode = "legacy_input_audio"

    session = new_session(odps_entry)
    logview = None
    t0 = time.perf_counter()
    try:
        logview = session.get_logview_address()
        print(f"DRIVER_ASR_LOGVIEW={logview}")
        try:
            result_df = llm.generate(df, messages=messages, **gen_kwargs)
        except TypeError:
            result_df = llm.generate(df, prompt_template=messages, **gen_kwargs)
        pdf = result_df.execute().fetch()
    except Exception as exc:
        print(f"DRIVER_ASR_LOGVIEW_ON_FAIL={logview}")
        if logview:
            try:
                exc.logview = logview  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        elapsed = time.perf_counter() - t0
        try:
            session.destroy()
        except Exception:  # noqa: BLE001
            pass

    out_cols = list(pdf.columns)
    text_col = next(
        (c for c in ("output", "generated_text", "text", "content", "response") if c in out_cols),
        out_cols[0] if out_cols else None,
    )
    if text_col is None:
        raise RuntimeError(f"ASR result has no text column: {out_cols}")

    texts: list[str] = []
    for i, _clip_id in enumerate(clip_ids):
        raw = pdf.iloc[i][text_col] if i < len(pdf) else ""
        texts.append(_normalize_llm_output(raw))

    return {
        "elapsed_sec": elapsed,
        "logview": logview,
        "texts": texts,
        "mc_mode": mc_mode,
        "row_count": len(texts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MaxFrame AI multi-partition ASR concurrency probe (local driver)"
    )
    parser.add_argument("--rows", type=int, default=4, help="duplicate ASR task count")
    parser.add_argument(
        "--partitions",
        type=int,
        default=None,
        help="rebalance partition count for concurrent run (default=rows)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=DEFAULT_AUDIO,
        help="WAV path (default: local_verify_mc preview audio.wav)",
    )
    parser.add_argument("--skip-serial", action="store_true", help="skip parallel_partitions=1 run")
    parser.add_argument("--model", default=None, help="ASR model name")
    parser.add_argument(
        "--modelset",
        default=None,
        help="modelset project (default: MC_MODELSET_PROJECT or bigdata_public_modelset)",
    )
    args = parser.parse_args()

    load_local_env(override=False)
    _load_root_env_nonsecret()

    rows_n = max(1, int(args.rows))
    partitions = int(args.partitions) if args.partitions is not None else rows_n
    partitions = max(1, min(partitions, rows_n))
    audio_path = Path(args.audio)
    if not audio_path.is_file():
        raise SystemExit(f"audio not found: {audio_path}")

    asr_model = (
        (args.model or get_arg("asr_model") or os.environ.get("ASR_MODEL") or DEFAULT_MODEL)
        .strip()
    )
    modelset = (
        (
            args.modelset
            or get_arg("mc_modelset_project")
            or os.environ.get("MC_MODELSET_PROJECT")
            or DEFAULT_MODELSET
        )
        .strip()
    )
    quota = _resolve_inference_quota()
    catalog = (
        get_arg("odps_catalog_endpoint")
        or os.environ.get("ODPS_CATALOG_ENDPOINT")
        or os.environ.get("odps_catalog_endpoint")
        or None
    )

    wav_bytes = audio_path.read_bytes()
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    print(
        f"PROBE audio={audio_path} bytes={len(wav_bytes)} rows={rows_n} "
        f"partitions={partitions} model={asr_model} modelset={modelset} "
        f"quota={quota or '(unset)'} skip_serial={args.skip_serial}"
    )

    from sdk_driver_bare_asr import build_asr_input_rows_from_b64

    items = [
        {
            "clip_id": f"probe_{i:04d}",
            "audio_oss_key": f"local/{audio_path.name}",
            "audio_b64": b64,
        }
        for i in range(rows_n)
    ]
    rows_in = build_asr_input_rows_from_b64(items)
    odps = _build_odps()

    runs: list[dict[str, Any]] = []
    if not args.skip_serial:
        runs.append(
            _run_one(
                odps,
                rows_in=rows_in,
                asr_model=asr_model,
                modelset_project=modelset,
                inference_quota_name=quota,
                parallel_partitions=1,
                catalog_endpoint=catalog,
            )
        )
    runs.append(
        _run_one(
            odps,
            rows_in=rows_in,
            asr_model=asr_model,
            modelset_project=modelset,
            inference_quota_name=quota,
            parallel_partitions=partitions,
            catalog_endpoint=catalog,
        )
    )

    serial = next((r for r in runs if r["mode"] == "serial"), None)
    concurrent = next((r for r in runs if r["mode"] == "concurrent"), None)
    if concurrent is None and partitions <= 1:
        concurrent = runs[-1] if runs else None

    serial_sec = serial["elapsed_sec"] if serial else None
    concurrent_sec = concurrent["elapsed_sec"] if concurrent else None
    speedup = None
    if serial_sec and concurrent_sec and concurrent_sec > 0:
        speedup = round(serial_sec / concurrent_sec, 3)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = HERE / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"mf_ai_concurrency_probe_{ts}.json"

    report: dict[str, Any] = {
        "timestamp_utc": ts,
        "rows": rows_n,
        "partitions": partitions,
        "model": asr_model,
        "modelset": modelset,
        "quota_set": bool(quota),
        "quota_name": quota,
        "audio": str(audio_path),
        "audio_bytes": len(wav_bytes),
        "skip_serial": bool(args.skip_serial),
        "serial_sec": serial_sec,
        "concurrent_sec": concurrent_sec,
        "speedup": speedup,
        "runs": runs,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== SUMMARY ==========")
    print(f"rows={rows_n} partitions={partitions}")
    print(f"serial_sec={serial_sec} concurrent_sec={concurrent_sec} speedup={speedup}")
    if serial:
        print(f"serial ok/fail={serial['ok']}/{serial['fail']} samples={serial['sample_texts']}")
        if serial.get("logview"):
            print(f"serial_logview={serial['logview']}")
        if serial.get("error"):
            print(f"serial_error={serial['error']}")
    if concurrent:
        print(
            f"concurrent ok/fail={concurrent['ok']}/{concurrent['fail']} "
            f"samples={concurrent['sample_texts']}"
        )
        if concurrent.get("logview"):
            print(f"concurrent_logview={concurrent['logview']}")
        if concurrent.get("error"):
            print(f"concurrent_error={concurrent['error']}")
    print(f"REPORT={report_path}")

    any_fail = any(r.get("fail", 0) > 0 or r.get("error") for r in runs)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
