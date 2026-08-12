from __future__ import annotations

# =============================================================================
# DataWorks PyODPS3: SDK single-driver (discover + pipeline apply_chunk)
# Production discovery uses two apply_chunk passes in this one Driver node:
# (1) hash bag bytes on the OSS mount; (2) run selected SDK pipeline stages.
# =============================================================================

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd

from pipeline_dispatch import (
    DEFAULT_DISPATCH_OSS_KEY,
    resolve_oss_http_endpoint,
    utc_now_iso,
)
from sdk_driver_bare_asr import (
    asr_jsonl_body,
    attach_asr_text_to_pack_rows,
    build_asr_input_rows_from_b64,
    build_asr_input_rows_from_oss_keys,
    clip_id_from_audio_key,
    driver_bare_asr_generate,
    parse_audio_keys_json,
    resolve_ai_media_mode,
    resolve_driver_oss_ak_sk,
)
from sdk_driver_bare_embed import (
    driver_bare_embed_generate,
    embeddings_jsonl_body,
)
from sdk_driver_bare_label import (
    driver_bare_label_generate,
    labels_jsonl_body,
)
from sdk_dpe_common import (
    apply_dpe_runtime_settings,
    collect_sdk_env_for_dpe,
    configure_dpe_engine,
    get_dw_arg,
    get_dw_float_arg,
    make_batch_input_df,
    oss_internal_url,
    patch_mc_catalog_runtime_for_dpe,
    storage_options,
    wrap_dpe_udf,
    _all_dw_arg_sources,
)
from sdk_mc_ingest import (
    build_run_json_document,
    format_run_json_body,
    ingest_sdk_run,
)
from sdk_pipeline_driver_lib import (
    batch_summary,
    build_job_rows,
    chunk_output_dtypes,
    content_hash_to_clip_id,
    filter_already_completed,
    make_run_id,
    run_oss_prefix_from_relpath,
    split_stages,
    trim_discovered_bags,
)


def _explicit_bag_from_args() -> list[dict[str, str]] | None:
    bag_oss_key = get_dw_arg("bag_oss_key")
    clip_id = get_dw_arg("clip_id")
    run_id = get_dw_arg("run_id")
    if bag_oss_key or clip_id:
        if not bag_oss_key or not clip_id:
            raise ValueError("bag_oss_key and clip_id must be provided together")
        return [
            {
                "bag_oss_key": str(bag_oss_key),
                "clip_id": str(clip_id),
                "run_id": str(run_id or make_run_id()),
            }
        ]
    return None


def _debug_bag_keys_from_args() -> list[str]:
    raw_keys = get_dw_arg("bag_oss_keys", "") or ""
    return [
        key.strip()
        for key in re.split(r"[\r\n,]+", raw_keys)
        if key.strip().lower().endswith(".bag")
    ]


def _list_bag_keys_from_oss(
    account: Any,
    *,
    oss_bucket: str,
    cloud_region: str,
) -> list[str]:
    """Scan bags on OSS. Prefer long-term AK (oss_access_key_*); o.account STS often AccessDenied."""
    from pipeline_dispatch import resolve_dispatch_oss_credentials
    from oss_v2_dw import iter_object_keys, make_oss_client

    endpoint = resolve_oss_http_endpoint(
        cloud_region,
        get_arg=get_dw_arg,
        explicit_endpoint=get_dw_arg("oss_endpoint"),
    )
    access_id, secret, token = resolve_dispatch_oss_credentials(
        account, get_arg=get_dw_arg
    )
    client = make_oss_client(
        access_key_id=access_id,
        access_key_secret=secret,
        region=cloud_region,
        endpoint=endpoint,
        security_token=token or None,
    )
    return list(
        iter_object_keys(
            client,
            bucket=oss_bucket,
            prefix=get_dw_arg("scan_prefix", "rosbags/") or "rosbags/",
            suffix=".bag",
            max_count=int(get_dw_arg("max_scan", "1000") or "1000"),
        )
    )


def _hash_chunk_output_dtypes() -> dict[str, str]:
    return {
        "clip_id": "string",
        "bag_oss_key": "string",
        "content_hash": "string",
    }


def _build_hash_chunk_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _hash_chunk(df: pd.DataFrame) -> pd.DataFrame:
        from pathlib import Path
        import hashlib

        rows_out: list[dict[str, str]] = []
        for _, row in df.iterrows():
            bag_oss_key = str(row["bag_oss_key"])
            hasher = hashlib.sha256()
            with (Path(mount_path) / bag_oss_key).open("rb") as bag_file:
                while True:
                    block = bag_file.read(1024 * 1024)
                    if not block:
                        break
                    hasher.update(block)
            content_hash = hasher.hexdigest()
            rows_out.append(
                {
                    "clip_id": f"sha256:{content_hash}",
                    "bag_oss_key": bag_oss_key,
                    "content_hash": content_hash,
                }
            )
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _hash_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _completed_clip_ids(
    client: Any,
    *,
    table_prefix: str,
    clip_ids: list[str],
) -> set[str]:
    """Find clips whose active SDK run is completed; failures are handled by caller."""
    completed: set[str] = set()
    for start in range(0, len(clip_ids), 50):
        batch = clip_ids[start : start + 50]
        quoted = ",".join("'" + cid.replace("'", "''") + "'" for cid in batch)
        sql = (
            f"SELECT d.clip_id FROM {table_prefix}dim_clip d "
            f"JOIN {table_prefix}pipeline_run r "
            "ON d.clip_id = r.clip_id AND d.active_run_id = r.run_id "
            f"WHERE d.clip_id IN ({quoted}) AND r.status = 'completed'"
        )
        with client.execute_sql(sql).open_reader() as reader:
            for record in reader:
                completed.add(str(record[0]))
    return completed


def _build_pipeline_chunk_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
    sdk_env: dict[str, str],
    udf_stages_frozen: frozenset[str],
    clip_min_sec: float,
    clip_max_sec: float,
    sample_fps: float,
    model_backend: str,
    cleanup_work: bool,
):
    def _pipeline_chunk(df: pd.DataFrame) -> pd.DataFrame:
        import json
        import os
        from pathlib import Path

        for key, value in sdk_env.items():
            if value:
                os.environ[key] = str(value)
        patch_mc_catalog_runtime_for_dpe()

        from oms_multimodal import ClipConfig, OmsMultimodalClient, run_stages

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            clip_id = str(row["clip_id"])
            run_id = str(row["run_id"])
            bag_oss_key = str(row["bag_oss_key"])
            run_relpath = str(row["run_relpath"])
            ds = str(row["ds"])
            try:
                bag_path = Path(mount_path) / bag_oss_key
                run_out = Path(mount_path) / run_relpath
                run_out.mkdir(parents=True, exist_ok=True)
                client = OmsMultimodalClient(
                    work_dir=run_out / "_sdk_work",
                    load_dotenv=False,
                )
                try:
                    ctx = client.make_run_context(
                        run_out,
                        media_mode="local",
                        clip_id=clip_id,
                        run_id=run_id,
                    )
                    result = run_stages(
                        ctx,
                        bag_path,
                        client,
                        stages=udf_stages_frozen,
                        clip_config=ClipConfig(
                            min_sec=clip_min_sec,
                            max_sec=clip_max_sec,
                            sample_fps=sample_fps,
                        ),
                        bag_oss_key=bag_oss_key,
                        ds=ds,
                        model_backend=model_backend,
                        cleanup_work=cleanup_work,
                    )
                finally:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()

                # Any capability error blocks Driver-side mc_write for this row.
                ok = len(result.errors) == 0
                error = str(result.errors[0])[:500] if result.errors else ""
                # Prefer _sdk_work/.../clips/*/audio.wav over preview/audio.wav
                # (never ASR both for the same bag/subclip). Logic inlined for DPE pickle.
                all_wav = sorted(
                    {
                        p.relative_to(Path(mount_path)).as_posix()
                        for p in run_out.rglob("audio.wav")
                        if p.is_file()
                    }
                )
                work_wav = [
                    k
                    for k in all_wav
                    if "/_sdk_work/" in f"/{k}"
                    and "/clips/" in k
                    and k.endswith("/audio.wav")
                ]
                wav_keys = work_wav if work_wav else [
                    k for k in all_wav if "/preview/" not in f"/{k}"
                ] or all_wav
                rows_out.append(
                    {
                        "clip_id": clip_id,
                        "run_id": run_id,
                        "bag_oss_key": bag_oss_key,
                        "ds": ds,
                        "ok": ok,
                        "error": error,
                        "stages_done": ",".join(result.stages_done),
                        "run_relpath": run_relpath,
                        "labels_relpath": f"{run_relpath}/labels.jsonl",
                        "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                        "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                        "preview_ok": bool(result.preview_ok),
                        "audio_keys_json": json.dumps(wav_keys, ensure_ascii=False),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows_out.append(
                    {
                        "clip_id": clip_id,
                        "run_id": run_id,
                        "bag_oss_key": bag_oss_key,
                        "ds": ds,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                        "stages_done": "",
                        "run_relpath": run_relpath,
                        "labels_relpath": f"{run_relpath}/labels.jsonl",
                        "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                        "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                        "preview_ok": False,
                        "audio_keys_json": "[]",
                    }
                )
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _pipeline_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _build_load_audio_b64_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    """Read audio.wav from OSS mount → base64 (Driver STS cannot List/Get business bucket)."""

    def _load_chunk(df: pd.DataFrame) -> pd.DataFrame:
        import base64
        from pathlib import Path

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            key = str(row["audio_oss_key"]).replace("\\", "/").lstrip("/")
            path = Path(mount_path) / key
            data = path.read_bytes()
            rows_out.append(
                {
                    "clip_id": str(row["clip_id"]),
                    "run_id": str(row["run_id"]),
                    "run_relpath": str(row["run_relpath"]),
                    "audio_oss_key": key,
                    "audio_b64": base64.b64encode(data).decode("ascii"),
                    "bytes": len(data),
                }
            )
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _load_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _build_write_text_file_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _write_chunk(df: pd.DataFrame) -> pd.DataFrame:
        from pathlib import Path

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rel = str(row["relpath"]).replace("\\", "/").lstrip("/")
            path = Path(mount_path) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(row["body"]), encoding="utf-8")
            rows_out.append({"relpath": rel, "written": 1})
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _write_chunk,
        dpe_cpu=max(1, dpe_cpu // 4) if dpe_cpu > 1 else 1,
        dpe_memory=max(2, min(dpe_memory, 4)),
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _build_write_asr_jsonl_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _write_chunk(df: pd.DataFrame) -> pd.DataFrame:
        from pathlib import Path

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rel = str(row["asr_relpath"]).replace("\\", "/").lstrip("/")
            path = Path(mount_path) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(row["asr_jsonl"]), encoding="utf-8")
            rows_out.append({"asr_relpath": rel, "written": 1})
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _write_chunk,
        dpe_cpu=max(1, dpe_cpu // 4) if dpe_cpu > 1 else 1,
        dpe_memory=max(2, min(dpe_memory, 4)),
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _build_media_pack_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
    media_mode: str = "dpe_base64",
):
    """Pack per-clip frames/audio/taxonomy_prompt for Driver label+embed.

    media_mode:
      - oss_url: return OSS object keys only (no file bytes / base64)
      - dpe_base64: existing base64 pack for Tunnel fallback
    """

    def _pack_chunk(df: pd.DataFrame) -> pd.DataFrame:
        import base64
        import json
        from pathlib import Path

        pack_mode = str(media_mode or "dpe_base64").strip().lower()
        if pack_mode in ("base64", "b64"):
            pack_mode = "dpe_base64"
        use_oss_keys = pack_mode == "oss_url"

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            run_relpath = str(row["run_relpath"]).replace("\\", "/").strip("/")
            run_dir = Path(mount_path) / run_relpath
            work = run_dir / "_sdk_work"
            bases = [run_dir, work, Path(mount_path)]

            # Taxonomy prompt via SDK wheel on DPE image.
            taxonomy_prompt = ""
            try:
                from oms_multimodal import bundled_taxonomy_path
                from oms_multimodal.taxonomy import load_taxonomy, taxonomy_prompt_block

                taxonomy_prompt = taxonomy_prompt_block(
                    load_taxonomy(bundled_taxonomy_path())
                )
            except Exception as tax_exc:  # noqa: BLE001
                taxonomy_prompt = (
                    "请输出 JSON：{scene_summary, labels:{<id>:{value,confidence,evidence}}}"
                )
                print(f"PACK_TAXONOMY_WARN {type(tax_exc).__name__}: {tax_exc}")

            asr_map: dict[str, dict[str, Any]] = {}
            asr_path = run_dir / "asr.jsonl"
            if asr_path.is_file():
                for line in asr_path.read_text(encoding="utf-8").splitlines():
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        rec = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    for key_name in ("sdk_clip_id", "clip_id"):
                        key = str(rec.get(key_name) or "").strip()
                        if key:
                            asr_map[key] = rec

            # Bag-level sha256 clip_id from Driver (OSS prefix / MC join key).
            bag_clip_id = str(row.get("bag_clip_id") or row.get("clip_id") or "").strip()

            index_path = run_dir / "clips_index.jsonl"
            if not index_path.is_file():
                raise FileNotFoundError(f"missing {index_path}")

            def _resolve(path_str: str) -> Path | None:
                raw = str(path_str or "").strip()
                if not raw:
                    return None
                p = Path(raw)
                if p.is_file():
                    return p
                for base in bases:
                    for cand in (base / raw, base / raw.lstrip("/\\")):
                        if cand.is_file():
                            return cand
                name = Path(raw).name
                if work.exists():
                    for hit in work.rglob(name):
                        if hit.is_file():
                            return hit
                return None

            def _find_clip_dir(clip_id: str) -> Path | None:
                if not work.exists():
                    return None
                for hit in work.rglob(clip_id):
                    if hit.is_dir() and (hit / "audio.wav").is_file():
                        return hit
                return None

            def _b64(path: Path | None) -> str:
                if path is None or not path.is_file():
                    return ""
                return base64.b64encode(path.read_bytes()).decode("ascii")

            def _oss_key(path: Path | None) -> str:
                if path is None:
                    return ""
                try:
                    if not path.is_file():
                        return ""
                except OSError:
                    return ""
                mount = Path(mount_path)
                try:
                    rel = path.resolve().relative_to(mount.resolve())
                    return str(rel).replace("\\", "/")
                except (OSError, ValueError):
                    raw = str(path).replace("\\", "/")
                    prefix = str(mount).replace("\\", "/").rstrip("/") + "/"
                    if raw.startswith(prefix):
                        return raw[len(prefix) :].lstrip("/")
                    return ""

            for line in index_path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                clip_row = json.loads(text)
                if not isinstance(clip_row, dict):
                    continue
                # SDK subclip dir name (output_0000); MC / outer id is bag_clip_id.
                sdk_clip_id = str(clip_row.get("clip_id") or "").strip()
                clip_dir = _find_clip_dir(sdk_clip_id)
                asr_rec = (
                    asr_map.get(sdk_clip_id)
                    or asr_map.get(bag_clip_id)
                    or (next(iter(asr_map.values())) if len(asr_map) == 1 else {})
                )
                asr_text = str(
                    asr_rec.get("text")
                    or clip_row.get("asr_text")
                    or ""
                )
                asr_model = str(
                    asr_rec.get("model") or clip_row.get("asr_model") or "qwen3-asr-flash"
                )

                label_frames: list[Path] = []
                for fr in (clip_row.get("frames") or [])[:12]:
                    if not isinstance(fr, dict):
                        continue
                    resolved = _resolve(str(fr.get("image_path") or ""))
                    if resolved is not None:
                        label_frames.append(resolved)
                    if len(label_frames) >= 4:
                        break
                if not label_frames and clip_dir is not None:
                    label_frames = sorted(clip_dir.rglob("*.jpg"))[:4]

                embed_frames: list[Path] = []
                for fr in (clip_row.get("embedding_frames") or clip_row.get("frames") or []):
                    if not isinstance(fr, dict):
                        continue
                    resolved = _resolve(str(fr.get("image_path") or ""))
                    if resolved is not None:
                        embed_frames.append(resolved)
                    if len(embed_frames) >= 3:
                        break
                panel = None
                if clip_row.get("acoustic_panel_path"):
                    panel = _resolve(str(clip_row.get("acoustic_panel_path")))
                if panel is None and clip_dir is not None:
                    cand = clip_dir / "acoustic_panel.png"
                    if cand.is_file():
                        panel = cand
                embed_images = list(embed_frames)
                if panel is not None:
                    embed_images.append(panel)

                audio_path = None
                audio_obj = clip_row.get("audio") or {}
                if isinstance(audio_obj, dict):
                    audio_path = _resolve(str(audio_obj.get("audio_path") or ""))
                if audio_path is None and clip_dir is not None:
                    cand = clip_dir / "audio.wav"
                    if cand.is_file():
                        audio_path = cand

                primary_clip_id = bag_clip_id or sdk_clip_id
                out: dict[str, Any] = {
                    "run_relpath": run_relpath,
                    "clip_id": primary_clip_id,
                    "sdk_clip_id": sdk_clip_id,
                    "bag_name": str(clip_row.get("bag_name") or ""),
                    "start_timestamp_ns": int(clip_row.get("start_timestamp_ns") or 0),
                    "end_timestamp_ns": int(clip_row.get("end_timestamp_ns") or 0),
                    "duration_sec": float(clip_row.get("duration_sec") or 0.0),
                    "source_topics": json.dumps(
                        clip_row.get("source_topics") or [], ensure_ascii=False
                    ),
                    "asr_text": asr_text,
                    "asr_model": asr_model,
                    "taxonomy_prompt": taxonomy_prompt,
                    "image_count": 0,
                    "embed_image_count": 0,
                    "audio_b64": "",
                    "audio_oss_key": "",
                }
                for i in range(4):
                    out[f"image_b64_{i}"] = ""
                    out[f"image_oss_key_{i}"] = ""
                for i in range(8):
                    out[f"embed_image_b64_{i}"] = ""
                    out[f"embed_image_oss_key_{i}"] = ""

                if use_oss_keys:
                    out["audio_oss_key"] = _oss_key(audio_path)
                    for i, fp in enumerate(label_frames[:4]):
                        out[f"image_oss_key_{i}"] = _oss_key(fp)
                        out["image_count"] = i + 1
                    for i, fp in enumerate(embed_images[:8]):
                        out[f"embed_image_oss_key_{i}"] = _oss_key(fp)
                        out["embed_image_count"] = i + 1
                    media_ok = bool(out["audio_oss_key"]) or out["image_count"] > 0
                else:
                    out["audio_b64"] = _b64(audio_path)
                    out["audio_oss_key"] = _oss_key(audio_path)
                    for i, fp in enumerate(label_frames[:4]):
                        out[f"image_b64_{i}"] = _b64(fp)
                        out[f"image_oss_key_{i}"] = _oss_key(fp)
                        out["image_count"] = i + 1
                    for i, fp in enumerate(embed_images[:8]):
                        out[f"embed_image_b64_{i}"] = _b64(fp)
                        out[f"embed_image_oss_key_{i}"] = _oss_key(fp)
                        out["embed_image_count"] = i + 1
                    media_ok = bool(out["audio_b64"]) or out["image_count"] > 0

                rows_out.append(out)
                print(
                    f"PACK_CLIP clip_id={primary_clip_id} sdk_clip_id={sdk_clip_id} "
                    f"label_images={out['image_count']} "
                    f"embed_images={out['embed_image_count']} "
                    f"media_mode={pack_mode} media_ok={media_ok} "
                    f"asr_chars={len(asr_text)}"
                )

        if not rows_out:
            raise FileNotFoundError(f"no clips packed under {run_relpath}")
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _pack_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )



def main() -> None:
    import json as _json

    resolved_preview = {
        k: resolved_v
        for k, resolved_v in _all_dw_arg_sources().items()
        if k not in {"odps_access_key", "odps_access_id", "dashscope_api_key"}
    }
    print(
        "DW_ARGS_DEBUG="
        + _json.dumps(
            {
                "keys": sorted(resolved_preview.keys()),
                "skynet_args_nonempty": bool(os.environ.get("SKYNET_ARGS", "").strip()),
            },
            ensure_ascii=False,
        )
    )

    stages_raw = get_dw_arg("stages")
    ai_submitter = (get_dw_arg("ai_submitter", "driver") or "driver").strip().lower()
    driver_stages, udf_stages, driver_ai_stages = split_stages(
        stages_raw, ai_submitter=ai_submitter
    )
    print(
        f"STAGES_SPLIT driver={sorted(driver_stages)} "
        f"udf={sorted(udf_stages)} driver_ai={sorted(driver_ai_stages)} "
        f"ai_submitter={ai_submitter}"
    )
    if driver_ai_stages - {"asr", "label", "embed"}:
        print(
            "WARN: unsupported driver_ai stages: "
            + ",".join(sorted(driver_ai_stages - {"asr", "label", "embed"}))
        )
    cleanup_work = (get_dw_arg("cleanup_work", "false") or "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if driver_ai_stages & {"asr", "label", "embed"} and cleanup_work:
        print(
            "WARN: cleanup_work=true would delete _sdk_work media needed by "
            "driver bare AI; forcing cleanup_work=false"
        )
        cleanup_work = False
    ds = get_dw_arg("ds") or datetime.now(timezone.utc).strftime("%Y%m%d")
    account = o.account  # type: ignore[name-defined]
    oss_bucket = get_dw_arg("oss_bucket")
    if not oss_bucket:
        raise ValueError("Missing required parameter: oss_bucket")
    cloud_region = get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    dpe_image = (get_dw_arg("dpe_image") or "").strip()
    if not dpe_image:
        raise ValueError("Missing required parameter: dpe_image")
    mount_path = get_dw_arg("mount_path", get_dw_arg("dpe_mount_path", "/mnt/oss")) or "/mnt/oss"
    batch_rows = int(get_dw_arg("batch_rows", "1") or "1")
    if batch_rows < 1:
        raise ValueError("batch_rows must be >= 1")
    dpe_parallel = int(get_dw_arg("dpe_parallel", "1") or "1")
    if dpe_parallel < 1:
        raise ValueError("dpe_parallel must be >= 1")
    hash_batch_rows = int(get_dw_arg("hash_batch_rows", "32") or "32")
    if hash_batch_rows < 1:
        raise ValueError("hash_batch_rows must be >= 1")
    dpe_cpu = int(get_dw_arg("dpe_cpu", "4") or "4")
    dpe_memory = int(get_dw_arg("dpe_memory_gb", "16") or "16")
    clip_min_sec = get_dw_float_arg("clip_min_sec", 15.0)
    clip_max_sec = get_dw_float_arg("clip_max_sec", 20.0)
    sample_fps = get_dw_float_arg("sample_fps", 1.0)
    sdk_env = collect_sdk_env_for_dpe(account, odps_entry=o)  # type: ignore[name-defined]
    # Workflow secret args override account-derived values; project/endpoint
    # fall back to the current Driver ODPS entry when available.
    odps_env_values = {
        "ODPS_ACCESS_ID": get_dw_arg("odps_access_id"),
        "ODPS_ACCESS_KEY": get_dw_arg("odps_access_key"),
        "ODPS_PROJECT": get_dw_arg("odps_project") or getattr(o, "project", ""),  # type: ignore[name-defined]
        "ODPS_ENDPOINT": get_dw_arg("odps_endpoint") or getattr(o, "endpoint", ""),  # type: ignore[name-defined]
    }
    for env_name, value in odps_env_values.items():
        if value:
            sdk_env[env_name] = str(value)
    model_backend = sdk_env["MODEL_BACKEND"]

    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()

    import maxframe.dataframe as md
    from maxframe.session import new_session

    mount_url = oss_internal_url(
        cloud_region,
        oss_bucket,
        get_dw_arg("oss_mount_prefix", "") or "",
    )
    mount_storage = storage_options(
        get_dw_arg("oss_ram_role_arn"),
        account,
        oss_bucket=oss_bucket,
    )
    mc_env_preview = collect_sdk_env_for_dpe(account, odps_entry=o)  # type: ignore[name-defined]
    inference_quota = (
        mc_env_preview.get("MC_INFERENCE_QUOTA_NAME")
        or mc_env_preview.get("AI_INFERENCE_QUOTA_NAME")
        or ""
    )
    if inference_quota and (
        "dataworks" in inference_quota.lower() or "resource_group" in inference_quota.lower()
    ):
        print(
            "WARN: inference_quota_name looks like a DataWorks resource group, not MC Token "
            "Inference Quota. Use MC console → Quota 管理 (e.g. ai_InferenceQuota)."
        )
    print(
        f"MOUNT_URL={mount_url} MOUNT_BUCKET={oss_bucket} "
        f"ODPS_CATALOG_ENDPOINT={mc_env_preview.get('ODPS_CATALOG_ENDPOINT', '')} "
        f"ODPS_STS_TOKEN_SET={bool(mc_env_preview.get('ODPS_STS_TOKEN'))} "
        f"INFERENCE_QUOTA_SET={bool(inference_quota)} "
        f"INFERENCE_QUOTA_NAME={inference_quota or '(unset)'}"
    )
    session = new_session(o)  # type: ignore[name-defined]
    ok_rows: list[dict[str, Any]] = []
    try:
        print(f"Logview: {session.get_logview_address()}")
        explicit_bags = _explicit_bag_from_args()
        if explicit_bags is not None:
            discovered_bags: list[dict[str, Any]] = explicit_bags
            print("DEBUG_OVERRIDE: using explicit clip_id/run_id/bag_oss_key")
        else:
            bag_keys = _debug_bag_keys_from_args()
            if not bag_keys:
                bag_keys = _list_bag_keys_from_oss(
                    account,
                    oss_bucket=oss_bucket,
                    cloud_region=cloud_region,
                )
            if not bag_keys:
                raise ValueError(
                    "no bags discovered from OSS; set scan_prefix or bag_oss_keys"
                )
            hash_input_df = md.DataFrame(
                pd.DataFrame([{"bag_oss_key": key} for key in bag_keys])
            )
            hash_parallel = min(max(dpe_parallel, 1), len(bag_keys))
            if hash_parallel > 1:
                hash_input_df = hash_input_df.mf.rebalance(num_partitions=hash_parallel)
            print(
                f"DPE_HASH_PARALLEL partitions={hash_parallel} "
                f"bags={len(bag_keys)} batch_rows={hash_batch_rows}"
            )
            hash_udf = _build_hash_chunk_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=mount_url,
                mount_path=mount_path,
                storage_options_dict=mount_storage,
            )
            hash_result = (
                hash_input_df.mf.apply_chunk(
                    hash_udf,
                    batch_rows=hash_batch_rows,
                    output_type="dataframe",
                    dtypes=_hash_chunk_output_dtypes(),
                    skip_infer=True,
                )
                .execute()
                .fetch()
            )
            discovered_bags = [
                {
                    "clip_id": content_hash_to_clip_id(str(row["content_hash"])),
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "content_hash": str(row["content_hash"]),
                }
                for _, row in hash_result.iterrows()
            ]

        force_rerun = (get_dw_arg("force_rerun", "false") or "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        completed_clip_ids: set[str] = set()
        if not force_rerun:
            table_prefix = (
                get_dw_arg("sdk_table_prefix")
                or get_dw_arg("table_prefix")
                or "aig_sdk__"
            )
            try:
                completed_clip_ids = _completed_clip_ids(
                    o,  # type: ignore[name-defined]
                    table_prefix=table_prefix,
                    clip_ids=[str(bag["clip_id"]) for bag in discovered_bags],
                )
            except Exception as exc:  # noqa: BLE001
                # A first deployment may run before SDK tables exist. Discovery
                # remains usable and mc_write can create/populate them later.
                print(
                    "WARNING: completed-run lookup failed; continuing without skip: "
                    f"{type(exc).__name__}: {exc}"
                )
        runnable_bags = filter_already_completed(
            discovered_bags,
            completed_clip_ids=completed_clip_ids,
            force_rerun=force_rerun,
        )
        max_bags_raw = get_dw_arg("max_bags")
        runnable_bags = trim_discovered_bags(
            runnable_bags,
            max_bags=None if max_bags_raw is None else int(max_bags_raw),
        )
        for bag in runnable_bags:
            bag.setdefault("run_id", make_run_id())
        job_rows = build_job_rows(runnable_bags, ds=ds)
        print(
            "DISCOVERED_ROWS_JSON="
            + json.dumps(
                {
                    "driver_stages": sorted(driver_stages),
                    "udf_stages": sorted(udf_stages),
                    "driver_ai_stages": sorted(driver_ai_stages),
                    "ai_submitter": ai_submitter,
                    "hashed_count": len(discovered_bags),
                    "skipped_completed": len(discovered_bags) - len(
                        filter_already_completed(
                            discovered_bags,
                            completed_clip_ids=completed_clip_ids,
                            force_rerun=force_rerun,
                        )
                    ),
                    "items": job_rows,
                },
                ensure_ascii=False,
            )
        )
        if not job_rows:
            print("No runnable bags after completed-run skip/max_bags")
            return
        if not udf_stages:
            print("No UDF stages selected; skipping pipeline apply_chunk")
            return

        input_df, extract_parallel = make_batch_input_df(job_rows, dpe_parallel)
        print(
            f"DPE_EXTRACT_PARALLEL partitions={extract_parallel} "
            f"bags={len(job_rows)} batch_rows={batch_rows}"
        )
        pipeline_udf = _build_pipeline_chunk_udf(
            dpe_cpu=dpe_cpu,
            dpe_memory=dpe_memory,
            oss_mount_url=mount_url,
            mount_path=mount_path,
            storage_options_dict=mount_storage,
            sdk_env=sdk_env,
            udf_stages_frozen=frozenset(udf_stages),
            clip_min_sec=clip_min_sec,
            clip_max_sec=clip_max_sec,
            sample_fps=sample_fps,
            model_backend=model_backend,
            cleanup_work=cleanup_work,
        )
        result = (
            input_df.mf.apply_chunk(
                pipeline_udf,
                batch_rows=batch_rows,
                output_type="dataframe",
                dtypes=chunk_output_dtypes(),
                skip_infer=True,
            )
            .execute()
            .fetch()
        )
        result_rows = [row.to_dict() for _, row in result.iterrows()]
        print(
            "BATCH_SUMMARY_JSON="
            + json.dumps(batch_summary(result_rows), ensure_ascii=False, default=str)
        )
        ok_rows = [
            row
            for row in result_rows
            if row.get("ok") is True
            or row.get("ok") == 1
            or str(row.get("ok")).lower() == "true"
        ]
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        # Destroy extract/hash session before Driver bare MaxFrame AI (Job2 pattern).
        session.destroy()

        postprocess_stages = driver_stages & {"mc_write", "dispatch"}
    if (postprocess_stages or driver_ai_stages) and not ok_rows:
            print(
            "WARNING: no successful extract rows; skipping Driver AI / postprocess "
            + ",".join(sorted(postprocess_stages | set(driver_ai_stages)))
        )

    # Per bag-run artifacts kept for mc_write (Driver has no OSS mount).
    run_label_rows: dict[str, list[dict[str, Any]]] = {}
    run_embed_rows: dict[str, list[dict[str, Any]]] = {}
    run_asr_rows: dict[str, list[dict[str, Any]]] = {}

    def _dpe_write_texts(writes: list[dict[str, str]]) -> None:
        if not writes:
            return
        import maxframe.dataframe as md
        from maxframe.session import new_session

        configure_dpe_engine()
        apply_dpe_runtime_settings(dpe_image)
        write_session = new_session(o)  # type: ignore[name-defined]
        try:
            print(f"DRIVER_WRITE_LOGVIEW={write_session.get_logview_address()}")
            write_udf = _build_write_text_file_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=mount_url,
                mount_path=mount_path,
                storage_options_dict=mount_storage,
            )
            (
                md.DataFrame(pd.DataFrame(writes))
                .mf.apply_chunk(
                    write_udf,
                    batch_rows=max(1, len(writes)),
                    output_type="dataframe",
                    dtypes={"relpath": "string", "written": "int64"},
                    skip_infer=True,
                )
                .execute()
                .fetch()
            )
        finally:
            write_session.destroy()

    asr_ok = 0
    asr_fail = 0
    if "asr" in driver_ai_stages and ok_rows:
        # Job2 同款：o.account STS 不能直连业务桶 → 挂载读 WAV / 写 asr.jsonl；
        # AI 在 Driver。无长期 AK 时走 DPE base64；有 oss_vl_/oss_access_ AK 时走 OSS URL。
        # Multi-bag: collect audio rows across ok_rows → one bare generate + rebalance.
        catalog_ep = (
            get_dw_arg("odps_catalog_endpoint")
            or sdk_env.get("ODPS_CATALOG_ENDPOINT")
            or ""
        )
        asr_model = (
            get_dw_arg("mc_asr_model")
            or get_dw_arg("asr_model")
            or "qwen3-asr-flash"
        )
        modelset = (
            get_dw_arg("mc_modelset_project")
            or sdk_env.get("MC_MODELSET_PROJECT")
            or "bigdata_public_modelset"
        )
        parallel = int(get_dw_arg("asr_parallel_partitions", "1") or "1")
        oss_ak = resolve_driver_oss_ak_sk(get_dw_arg)
        audio_mode = "oss_url" if oss_ak else "dpe_base64"

        import maxframe.dataframe as md
        from maxframe.session import new_session

        # Re-apply DPE-only engine for mount I/O helpers (AI session reconfigures elsewhere).
        configure_dpe_engine()
        apply_dpe_runtime_settings(dpe_image)

        # (run_relpath, bag_row, audio_oss_key) alignment for result split.
        audio_meta: list[tuple[str, dict[str, Any], str]] = []
        load_rows: list[dict[str, Any]] = []
        rows_in: list[dict[str, str]] = []
        audio_storage: dict[str, str] | None = None

        try:
            for row in ok_rows:
                wav_keys = parse_audio_keys_json(row.get("audio_keys_json"))
                if not wav_keys:
                    raise FileNotFoundError(
                        f"audio_keys_json empty for run_relpath={row.get('run_relpath')} "
                        "(extract must keep audio.wav; cleanup_work=false)"
                    )
                bag_clip_id = str(row.get("clip_id") or "").strip()
                run_key = str(row["run_relpath"])
                if audio_mode == "oss_url":
                    bag_rows = build_asr_input_rows_from_oss_keys(
                        wav_keys,
                        bucket=oss_bucket,
                        cloud_region=cloud_region,
                        bag_clip_id=bag_clip_id,
                    )
                    for br in bag_rows:
                        key = str(br.get("audio_oss_key") or "")
                        audio_meta.append((run_key, row, key))
                        rows_in.append(br)
                    audio_storage = oss_ak
                else:
                    for key in wav_keys:
                        audio_meta.append((run_key, row, key))
                        load_rows.append(
                            {
                                "clip_id": bag_clip_id or clip_id_from_audio_key(key),
                                "sdk_clip_id": clip_id_from_audio_key(key),
                                "run_id": str(row["run_id"]),
                                "run_relpath": run_key,
                                "audio_oss_key": key,
                            }
                        )

            if audio_mode == "dpe_base64":
                load_session = new_session(o)  # type: ignore[name-defined]
                try:
                    print(f"DRIVER_ASR_LOAD_LOGVIEW={load_session.get_logview_address()}")
                    load_udf = _build_load_audio_b64_udf(
                        dpe_cpu=dpe_cpu,
                        dpe_memory=dpe_memory,
                        oss_mount_url=mount_url,
                        mount_path=mount_path,
                        storage_options_dict=mount_storage,
                    )
                    loaded = (
                        md.DataFrame(pd.DataFrame(load_rows))
                        .mf.apply_chunk(
                            load_udf,
                            batch_rows=max(1, len(load_rows)),
                            output_type="dataframe",
                            dtypes={
                                "clip_id": "string",
                                "run_id": "string",
                                "run_relpath": "string",
                                "audio_oss_key": "string",
                                "audio_b64": "string",
                                "bytes": "int64",
                            },
                            skip_infer=True,
                        )
                        .execute()
                        .fetch()
                    )
                finally:
                    load_session.destroy()
                b64_by_key: dict[str, dict[str, Any]] = {}
                for _, lr in loaded.iterrows():
                    item = lr.to_dict()
                    b64_by_key[str(item.get("audio_oss_key") or "")] = item
                key_to_sdk = {
                    str(r["audio_oss_key"]): str(r.get("sdk_clip_id") or "")
                    for r in load_rows
                }
                b64_items: list[dict[str, Any]] = []
                for run_key, row, key in audio_meta:
                    item = dict(b64_by_key.get(key) or {})
                    if not item.get("audio_b64"):
                        raise FileNotFoundError(f"ASR load missing audio_b64 key={key}")
                    bag_clip_id = str(row.get("clip_id") or "").strip()
                    item["sdk_clip_id"] = key_to_sdk.get(key) or clip_id_from_audio_key(key)
                    item["clip_id"] = bag_clip_id or item["sdk_clip_id"]
                    item["run_relpath"] = run_key
                    print(
                        f"DRIVER_ASR_LOADED key={key} bytes={item.get('bytes')} "
                        f"run={run_key}"
                    )
                    b64_items.append(item)
                rows_in = build_asr_input_rows_from_b64(b64_items)

            print(
                f"DRIVER_BARE_ASR start rows={len(rows_in)} bags={len(ok_rows)} "
                f"model={asr_model} quota={inference_quota or '(unset)'} "
                f"parallel={parallel} audio_mode={audio_mode}"
            )
            summary = driver_bare_asr_generate(
                o,  # type: ignore[name-defined]
                rows_in=rows_in,
                asr_model=asr_model,
                modelset_project=modelset,
                catalog_endpoint=catalog_ep or None,
                inference_quota_name=inference_quota or None,
                parallel_partitions=max(1, parallel),
                audio_storage_options=audio_storage,
            )
            asr_rows_all = list(summary.pop("asr_rows"))
            if len(asr_rows_all) != len(audio_meta):
                raise RuntimeError(
                    f"ASR row count mismatch got={len(asr_rows_all)} "
                    f"expected={len(audio_meta)}"
                )
            for i, (run_key, _row, _key) in enumerate(audio_meta):
                run_asr_rows.setdefault(run_key, []).append(asr_rows_all[i])

            write_payload = [
                {
                    "asr_relpath": f"{run_key.rstrip('/')}/asr.jsonl",
                    "asr_jsonl": asr_jsonl_body(rows),
                }
                for run_key, rows in run_asr_rows.items()
            ]
            configure_dpe_engine()
            apply_dpe_runtime_settings(dpe_image)
            write_session = new_session(o)  # type: ignore[name-defined]
            try:
                print(f"DRIVER_ASR_WRITE_LOGVIEW={write_session.get_logview_address()}")
                write_udf = _build_write_asr_jsonl_udf(
                    dpe_cpu=dpe_cpu,
                    dpe_memory=dpe_memory,
                    oss_mount_url=mount_url,
                    mount_path=mount_path,
                    storage_options_dict=mount_storage,
                )
                (
                    md.DataFrame(pd.DataFrame(write_payload))
                    .mf.apply_chunk(
                        write_udf,
                        batch_rows=max(1, len(write_payload)),
                        output_type="dataframe",
                        dtypes={"asr_relpath": "string", "written": "int64"},
                        skip_infer=True,
                    )
                    .execute()
                    .fetch()
                )
            finally:
                write_session.destroy()

            asr_ok = len(run_asr_rows)
            print(
                "DRIVER_ASR_SUMMARY_JSON="
                + json.dumps(
                    {
                        "bags": len(ok_rows),
                        "audio_rows": len(rows_in),
                        "parallel": parallel,
                        "audio_mode": audio_mode,
                        "runs": sorted(run_asr_rows.keys()),
                        **summary,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
        except Exception as asr_exc:  # noqa: BLE001
            asr_fail = len(ok_rows)
            asr_ok = 0
            print(f"DRIVER_ASR_FAIL bags={len(ok_rows)} {type(asr_exc).__name__}: {asr_exc}")
        print(
            "DRIVER_ASR_BATCH_JSON="
            + json.dumps(
                {
                    "ok_count": asr_ok,
                    "fail_count": asr_fail,
                    "audio_rows": len(rows_in),
                    "parallel": parallel,
                    "submitter": "driver_bare",
                    "audio_mode": audio_mode,
                },
                ensure_ascii=False,
            )
        )
        if asr_fail:
            raise RuntimeError(
                f"driver bare ASR failed for {asr_fail}/{asr_ok + asr_fail} run(s)"
            )

    # Per bag-run artifacts kept for mc_write (Driver has no OSS mount).
    # (run_label_rows / run_embed_rows initialized above)

    def _media_pack_dtypes() -> dict[str, str]:
        dtypes: dict[str, str] = {
            "run_relpath": "string",
            "clip_id": "string",
            "sdk_clip_id": "string",
            "bag_name": "string",
            "start_timestamp_ns": "int64",
            "end_timestamp_ns": "int64",
            "duration_sec": "double",
            "source_topics": "string",
            "asr_text": "string",
            "asr_model": "string",
            "taxonomy_prompt": "string",
            "image_count": "int64",
            "embed_image_count": "int64",
            "audio_b64": "string",
            "audio_oss_key": "string",
        }
        for i in range(4):
            dtypes[f"image_b64_{i}"] = "string"
            dtypes[f"image_oss_key_{i}"] = "string"
        for i in range(8):
            dtypes[f"embed_image_b64_{i}"] = "string"
            dtypes[f"embed_image_oss_key_{i}"] = "string"
        return dtypes

    if driver_ai_stages & {"label", "embed"} and ok_rows:
        import maxframe.dataframe as md
        from maxframe.session import new_session

        catalog_ep = (
            get_dw_arg("odps_catalog_endpoint")
            or sdk_env.get("ODPS_CATALOG_ENDPOINT")
            or ""
        )
        modelset = (
            get_dw_arg("mc_modelset_project")
            or sdk_env.get("MC_MODELSET_PROJECT")
            or "bigdata_public_modelset"
        )
        omni_model = (
            get_dw_arg("omni_model")
            or sdk_env.get("OMNI_MODEL")
            or "qwen3.5-omni-plus"
        )
        embedding_model = (
            get_dw_arg("embedding_model")
            or sdk_env.get("EMBEDDING_MODEL")
            or "qwen3-vl-embedding"
        )
        embedding_dimension = int(
            get_dw_arg("embedding_dimension")
            or sdk_env.get("EMBEDDING_DIMENSION")
            or "1024"
        )
        label_parallel = int(
            get_dw_arg("label_parallel_partitions")
            or get_dw_arg("asr_parallel_partitions", "1")
            or "1"
        )
        embed_parallel = int(
            get_dw_arg("embed_parallel_partitions")
            or get_dw_arg("asr_parallel_partitions", "1")
            or "1"
        )
        # Prefer OSS URL + storage_options when long-term AK present (same as ASR).
        label_embed_oss_ak = resolve_driver_oss_ak_sk(get_dw_arg)
        ai_media_mode = resolve_ai_media_mode(get_dw_arg, oss_ak=label_embed_oss_ak)
        media_storage = label_embed_oss_ak if ai_media_mode == "oss_url" else None
        print(
            f"DRIVER_LABEL_EMBED_MEDIA_MODE={ai_media_mode} "
            f"oss_ak_set={bool(label_embed_oss_ak)}"
        )
        label_ok = 0
        label_fail = 0
        embed_ok = 0
        embed_fail = 0
        bag_by_run = {str(r["run_relpath"]): r for r in ok_rows}

        try:
            # One DPE pack session for all ok bags.
            configure_dpe_engine()
            apply_dpe_runtime_settings(dpe_image)
            pack_inputs = [
                {
                    "run_relpath": str(row["run_relpath"]),
                    "bag_clip_id": str(row.get("clip_id") or ""),
                }
                for row in ok_rows
            ]
            pack_session = new_session(o)  # type: ignore[name-defined]
            try:
                print(
                    f"DRIVER_PACK_LOGVIEW={pack_session.get_logview_address()} "
                    f"bags={len(pack_inputs)} media_mode={ai_media_mode}"
                )
                pack_udf = _build_media_pack_udf(
                    dpe_cpu=dpe_cpu,
                    dpe_memory=dpe_memory,
                    oss_mount_url=mount_url,
                    mount_path=mount_path,
                    storage_options_dict=mount_storage,
                    media_mode=ai_media_mode,
                )
                packed = (
                    md.DataFrame(pd.DataFrame(pack_inputs))
                    .mf.apply_chunk(
                        pack_udf,
                        batch_rows=max(1, len(pack_inputs)),
                        output_type="dataframe",
                        dtypes=_media_pack_dtypes(),
                        skip_infer=True,
                    )
                    .execute()
                    .fetch()
                )
            finally:
                pack_session.destroy()

            all_pack_rows = [r.to_dict() for _, r in packed.iterrows()]
            # Attach ASR per run (in-memory; mount asr.jsonl may miss ids).
            attached: list[dict[str, Any]] = []
            for pack in all_pack_rows:
                run_key = str(pack.get("run_relpath") or "")
                bag_row = bag_by_run.get(run_key) or {}
                attached.extend(
                    attach_asr_text_to_pack_rows(
                        [pack],
                        run_asr_rows.get(run_key) or [],
                        bag_clip_id=str(bag_row.get("clip_id") or ""),
                    )
                )
            all_pack_rows = attached
            packs_by_run: dict[str, list[dict[str, Any]]] = {}
            for pack in all_pack_rows:
                packs_by_run.setdefault(str(pack.get("run_relpath") or ""), []).append(pack)
            print(
                f"DRIVER_PACK_OK bags={len(packs_by_run)} clips={len(all_pack_rows)} "
                f"media_mode={ai_media_mode} "
                f"asr_chars={[len(str(p.get('asr_text') or '')) for p in all_pack_rows]}"
            )

            if "label" in driver_ai_stages:
                label_summary = driver_bare_label_generate(
                    o,  # type: ignore[name-defined]
                    pack_rows=all_pack_rows,
                    omni_model=omni_model,
                    modelset_project=modelset,
                    catalog_endpoint=catalog_ep or None,
                    inference_quota_name=inference_quota or None,
                    parallel_partitions=max(1, label_parallel),
                    media_mode=ai_media_mode,
                    media_storage_options=media_storage,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                )
                label_rows_all = list(label_summary.pop("label_rows"))
                if len(label_rows_all) != len(all_pack_rows):
                    raise RuntimeError(
                        f"label row count mismatch got={len(label_rows_all)} "
                        f"expected={len(all_pack_rows)}"
                    )
                writes: list[dict[str, str]] = []
                for i, pack in enumerate(all_pack_rows):
                    run_key = str(pack.get("run_relpath") or "")
                    run_label_rows.setdefault(run_key, []).append(label_rows_all[i])
                for run_key, rows in run_label_rows.items():
                    writes.append(
                        {
                            "relpath": f"{run_key.rstrip('/')}/labels.jsonl",
                            "body": labels_jsonl_body(rows),
                        }
                    )
                _dpe_write_texts(writes)
                label_ok = len(run_label_rows)
                print(
                    "DRIVER_LABEL_SUMMARY_JSON="
                    + json.dumps(
                        {
                            "bags": label_ok,
                            "clips": len(label_rows_all),
                            "parallel": label_parallel,
                            **label_summary,
                            "scene_summaries": [
                                r.get("scene_summary") for r in label_rows_all
                            ],
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )

            if "embed" in driver_ai_stages:
                label_by_clip: dict[str, dict[str, Any]] = {}
                for rows in run_label_rows.values():
                    for r in rows:
                        cid = str(r.get("clip_id") or "")
                        if cid:
                            label_by_clip[cid] = r
                        sid = str(r.get("sdk_clip_id") or "")
                        if sid:
                            label_by_clip[sid] = r
                embed_summary = driver_bare_embed_generate(
                    o,  # type: ignore[name-defined]
                    pack_rows=all_pack_rows,
                    label_by_clip=label_by_clip,
                    embedding_model=embedding_model,
                    embedding_dimension=embedding_dimension,
                    modelset_project=modelset,
                    catalog_endpoint=catalog_ep or None,
                    inference_quota_name=inference_quota or None,
                    parallel_partitions=max(1, embed_parallel),
                    media_mode=ai_media_mode,
                    media_storage_options=media_storage,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                )
                embed_rows_all = list(embed_summary.pop("embed_rows"))
                if len(embed_rows_all) != len(all_pack_rows):
                    raise RuntimeError(
                        f"embed row count mismatch got={len(embed_rows_all)} "
                        f"expected={len(all_pack_rows)}"
                    )
                writes = []
                for i, pack in enumerate(all_pack_rows):
                    run_key = str(pack.get("run_relpath") or "")
                    run_embed_rows.setdefault(run_key, []).append(embed_rows_all[i])
                for run_key, rows in run_embed_rows.items():
                    writes.append(
                        {
                            "relpath": f"{run_key.rstrip('/')}/fusion_embeddings.jsonl",
                            "body": embeddings_jsonl_body(rows),
                        }
                    )
                _dpe_write_texts(writes)
                embed_ok = len(run_embed_rows)
                print(
                    "DRIVER_EMBED_SUMMARY_JSON="
                    + json.dumps(
                        {
                            "bags": embed_ok,
                            "clips": len(embed_rows_all),
                            "parallel": embed_parallel,
                            **embed_summary,
                            "dims": [len(r.get("embedding") or []) for r in embed_rows_all],
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
        except Exception as ai_exc:  # noqa: BLE001
            if "label" in driver_ai_stages and not run_label_rows:
                label_fail = len(ok_rows)
            elif "label" in driver_ai_stages:
                label_fail = max(0, len(ok_rows) - len(run_label_rows))
            if "embed" in driver_ai_stages and not run_embed_rows:
                embed_fail = len(ok_rows)
            elif "embed" in driver_ai_stages:
                embed_fail = max(0, len(ok_rows) - len(run_embed_rows))
            print(
                "DRIVER_LABEL_EMBED_FAIL "
                f"bags={len(ok_rows)} {type(ai_exc).__name__}: {ai_exc}"
            )

        if "label" in driver_ai_stages:
            print(
                "DRIVER_LABEL_BATCH_JSON="
                + json.dumps(
                    {
                        "ok_count": label_ok,
                        "fail_count": label_fail,
                        "parallel": label_parallel,
                        "media_mode": ai_media_mode,
                        "submitter": "driver_bare",
                    },
                    ensure_ascii=False,
                )
            )
            if label_fail:
                raise RuntimeError(
                    f"driver bare label failed for {label_fail}/{label_ok + label_fail} run(s)"
                )
        if "embed" in driver_ai_stages:
            print(
                "DRIVER_EMBED_BATCH_JSON="
                + json.dumps(
                    {
                        "ok_count": embed_ok,
                        "fail_count": embed_fail,
                        "parallel": embed_parallel,
                        "media_mode": ai_media_mode,
                        "submitter": "driver_bare",
                    },
                    ensure_ascii=False,
                )
            )
            if embed_fail:
                raise RuntimeError(
                    f"driver bare embed failed for {embed_fail}/{embed_ok + embed_fail} run(s)"
                )

    # Hybrid default stages omit SDK "upload"; write run.json after AI artifacts land.
    if ok_rows and (
        "mc_write" in driver_stages
        or "dispatch" in driver_stages
        or bool(driver_ai_stages & {"asr", "label", "embed"})
    ):
        run_json_writes: list[dict[str, str]] = []
        for row in ok_rows:
            done = [
                s.strip()
                for s in str(row.get("stages_done") or "").split(",")
                if s.strip()
            ]
            for stage in ("asr", "label", "embed"):
                if stage in driver_ai_stages and stage not in done:
                    done.append(stage)
            if "upload" not in done:
                done.append("upload")
            doc = build_run_json_document(
                clip_id=str(row["clip_id"]),
                run_id=str(row["run_id"]),
                ds=str(row["ds"]),
                bag_oss_key=str(row["bag_oss_key"]),
                stages_done=done,
                model_backend=model_backend,
            )
            run_json_writes.append(
                {
                    "relpath": f"{str(row['run_relpath']).rstrip('/')}/run.json",
                    "body": format_run_json_body(doc),
                }
            )
        _dpe_write_texts(run_json_writes)
        print(f"RUN_JSON_WRITTEN count={len(run_json_writes)}")

    if "mc_write" in driver_stages and ok_rows:
            table_prefix = (
                get_dw_arg("sdk_table_prefix")
                or get_dw_arg("table_prefix")
                or "aig_sdk__"
            )
            for row in ok_rows:
            run_key = str(row["run_relpath"])
            labels = run_label_rows.get(run_key) or []
            embeds = run_embed_rows.get(run_key) or []
            if not labels or not embeds:
                raise RuntimeError(
                    "mc_write requires labels.jsonl + fusion_embeddings.jsonl in memory; "
                    f"run={run_key} labels={len(labels)} embeds={len(embeds)}. "
                    "Include stages label,embed with ai_submitter=driver."
                )
                ingest_sdk_run(
                    o,  # type: ignore[name-defined]
                    clip_id=str(row["clip_id"]),
                    run_id=str(row["run_id"]),
                    ds=str(row["ds"]),
                    table_prefix=table_prefix,
                    bag_oss_key=str(row["bag_oss_key"]),
                label_row=labels[0],
                embed_row=embeds[0],
                run_doc={
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "source_run_dir": str(
                        labels[0].get("sdk_clip_id") or row["clip_id"]
                    ),
                },
            )
            print(
                f"MC_WRITE_OK clip_id={row.get('clip_id')} run_id={row.get('run_id')} "
                f"label_clips={len(labels)} embed_clips={len(embeds)}"
                )

        if "dispatch" in driver_stages and ok_rows:
            items = [
                {
                    "clip_id": str(row["clip_id"]),
                    "run_id": str(row["run_id"]),
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "ds": str(row["ds"]),
                    "run_relpath": str(row["run_relpath"]),
                "run_oss_prefix": run_oss_prefix_from_relpath(str(row["run_relpath"])),
                }
                for row in ok_rows
            ]
            payload: dict[str, Any] = {
                "action": "run",
                "layout_version": "sdk_v1",
                "pipeline_version": "sdk_v1",
                "batch_size": len(items),
                "items": items,
                "run_oss_prefix": items[0]["run_oss_prefix"],
                "dispatched_at": utc_now_iso(),
            }
        # Compat: HMI / verify expect top-level clip_id/run_id even for multi-bag batches.
                payload.update(items[0])
            dispatch_key = (
                get_dw_arg("dispatch_oss_key", DEFAULT_DISPATCH_OSS_KEY)
                or DEFAULT_DISPATCH_OSS_KEY
            )
        # o.account STS often cannot PutObject; write via DPE mount (Job2 pattern).
        _dpe_write_texts(
            [
                {
                    "relpath": dispatch_key.lstrip("/"),
                    "body": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ]
        )
        print("DISPATCH_JSON=" + json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
