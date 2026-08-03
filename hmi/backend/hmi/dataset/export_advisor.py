"""Export format advisor based on dataset preview stats (M7.6)."""

from __future__ import annotations

from typing import Any

from hmi.dataset.assemble import MAX_CLIP_COUNT

# Heuristics — tune from preview only; no extra OSS/build cost.
PARQUET_LINE_THRESHOLD = 2_000
PARQUET_LABEL_COL_THRESHOLD = 15
PARQUET_CLIP_THRESHOLD = 2_000
BATCH_CLIP_THRESHOLD = 8_000
SMALL_CLIP_THRESHOLD = 500

BYTES_PER_JSONL_ROW = 450


def _estimate_sizes(
    *,
    line_count: int,
    export_preset: str,
    include_parquet: bool,
) -> dict[str, Any]:
    line_count = max(0, line_count)
    jsonl_mb = round(line_count * BYTES_PER_JSONL_ROW / (1024 * 1024), 2)
    zip_mb = jsonl_mb * 1.08 + 0.05
    if include_parquet:
        zip_mb += jsonl_mb * 0.35
    full_media_note = None
    if export_preset == "full":
        full_media_note = "完整包含 parsed 媒体，实际体积通常远大于下表 JSONL 估算"
        zip_mb = None
    return {
        "line_count": line_count,
        "jsonl_mb_estimated": jsonl_mb,
        "zip_mb_estimated": round(zip_mb, 2) if zip_mb is not None else None,
        "full_media_note": full_media_note,
    }


def build_export_recommendation(
    *,
    filter_json: dict[str, Any],
    estimated_clip_count: int,
    estimated_line_count: int,
    label_column_count: int,
    embedding_summary: dict[str, Any] | None = None,
    distribution_after: dict[str, int] | None = None,
    exceeds_clip_limit: bool = False,
    clip_limit: int = MAX_CLIP_COUNT,
    preview_error: str | None = None,
) -> dict[str, Any]:
    """Return suggested export options and human-readable reasons."""
    filt = filter_json or {}
    emb = embedding_summary or {}
    schemas = emb.get("schemas") or []
    balance_key = filt.get("balance_by_label")
    dist_after = distribution_after or {}

    reasons: list[str] = []
    suggested_preset = "minimal"
    suggested_parquet = False
    suggested_batch = False
    suggested_sample_size: int | None = None

    clip_count = max(0, int(estimated_clip_count))
    line_count = max(0, int(estimated_line_count))
    label_cols = max(0, int(label_column_count))

    if preview_error:
        reasons.append(f"预览组装异常：{preview_error}；请先缩小筛选条件")
        return {
            "suggested_export_preset": suggested_preset,
            "suggested_include_parquet": suggested_parquet,
            "suggested_batch": suggested_batch,
            "suggested_sample_size": suggested_sample_size,
            "reasons": reasons,
            "estimates": _estimate_sizes(
                line_count=line_count,
                export_preset=suggested_preset,
                include_parquet=suggested_parquet,
            ),
            "stats": {
                "clip_count": clip_count,
                "line_count": line_count,
                "label_column_count": label_cols,
                "embedding_schemas": schemas,
                "balance_class_count": len(dist_after) if balance_key else None,
            },
            "confidence": "low",
        }

    # Preset: embedding-only → minimal; user must opt-in to full for multimodal.
    if "frame_embeddings_v1" in schemas and "clip_embedding_v1" not in schemas:
        reasons.append("样本主要为 frame 级向量；若训练需原始图像/音频，请自行改选「完整包」")
    else:
        reasons.append("当前特征以 clip 级向量为主，建议「精简」预设（体积更小）")

    if filt.get("export_preset") == "full":
        suggested_preset = "full"
        reasons.append("已选完整包：将包含 parsed 媒体，下载体积显著增大")

    # Parquet heuristics
    if (
        line_count >= PARQUET_LINE_THRESHOLD
        or clip_count >= PARQUET_CLIP_THRESHOLD
        or label_cols >= PARQUET_LABEL_COL_THRESHOLD
    ):
        suggested_parquet = True
        parts: list[str] = []
        if line_count >= PARQUET_LINE_THRESHOLD:
            parts.append(f"导出行约 {line_count}")
        if clip_count >= PARQUET_CLIP_THRESHOLD:
            parts.append(f"clip 约 {clip_count}")
        if label_cols >= PARQUET_LABEL_COL_THRESHOLD:
            parts.append(f"标签列 {label_cols}")
        reasons.append(f"规模较大（{' · '.join(parts)}），建议勾选 Parquet 便于 pandas/Spark 读取")
    elif clip_count <= SMALL_CLIP_THRESHOLD:
        reasons.append(f"规模较小（≤{SMALL_CLIP_THRESHOLD} clip），JSONL 足够，Parquet 可选")

    # Batch / sample
    if exceeds_clip_limit or clip_count > clip_limit:
        suggested_batch = True
        suggested_sample_size = clip_limit
        reasons.append(
            f"匹配 clip 超过上限 {clip_limit}，建议随机取样 {clip_limit} 或拆成多个快照"
        )
    elif clip_count > BATCH_CLIP_THRESHOLD:
        suggested_batch = True
        reasons.append(f"clip 数 > {BATCH_CLIP_THRESHOLD}，可考虑分批导出以便管理")

    # Balance / class imbalance hint
    if balance_key and dist_after:
        counts = [v for k, v in dist_after.items() if k != "__missing__"]
        if counts:
            min_c, max_c = min(counts), max(counts)
            if max_c > 0 and min_c < max(1, max_c // 10):
                reasons.append(f"平衡维度 `{balance_key}` 类别不均衡（最少 {min_c} / 最多 {max_c}）")

    min_per = filt.get("min_per_class")
    if min_per and balance_key and dist_after:
        scarce = [k for k, v in dist_after.items() if v < int(min_per) and k != "__missing__"]
        if scarce:
            reasons.append(f"{len(scarce)} 个类别低于 min_per_class={min_per}，构建时将过采样")

    confidence = "high" if clip_count > 0 and line_count > 0 else "low"

    return {
        "suggested_export_preset": suggested_preset,
        "suggested_include_parquet": suggested_parquet,
        "suggested_batch": suggested_batch,
        "suggested_sample_size": suggested_sample_size,
        "reasons": reasons,
        "estimates": _estimate_sizes(
            line_count=line_count,
            export_preset=str(filt.get("export_preset") or suggested_preset),
            include_parquet=bool(filt.get("include_parquet") or suggested_parquet),
        ),
        "stats": {
            "clip_count": clip_count,
            "line_count": line_count,
            "label_column_count": label_cols,
            "embedding_schemas": list(schemas),
            "balance_class_count": len(dist_after) if balance_key else None,
        },
        "confidence": confidence,
    }
