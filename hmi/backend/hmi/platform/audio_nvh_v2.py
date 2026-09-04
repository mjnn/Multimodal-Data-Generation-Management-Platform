"""audio_nvh-v2: 78-leaf SPL / noise ground-truth taxonomy for HEAD 4-ch arrays.

Canonical node list used by YAML dump and platform seed (draft, not published).
Spatial nodes are inter-channel proxies — not DOA / beamforming.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

VERSION_CODE = "audio_nvh-v2"
TAXONOMY_ID = "audio_nvh"
LABEL_COUNT = 78

PREF_PA = 2e-5
CH_NAMES = ("VL", "VR", "HL", "HR")


def _ch_fields(unit: str) -> list[dict[str, str]]:
    return [{"name": n, "type": "float", "unit": unit} for n in CH_NAMES]


def _composite(unit: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "composite", "unit": unit, "fields": _ch_fields(unit)}
    if extra:
        schema.update(extra)
    return schema


def _json_ref(*, content: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "json_ref",
        "fields": [
            {"name": "_ref", "type": "string", "description": "相对 runs/{run_id}/ 的路径"},
            {"name": "_sha256", "type": "string", "optional": True},
        ],
        "content": content,
    }
    if extra:
        schema.update(extra)
    return schema


def _node(
    *,
    no: int,
    label_id: str,
    level_code: str,
    level_name: str,
    name: str,
    definition: str,
    dtype: str,
    value_schema: dict[str, Any],
    derivation: str,
    l2_source: str | None = None,
    selection_reason: str = "",
) -> dict[str, Any]:
    schema = dict(value_schema)
    schema["derivation"] = derivation
    if l2_source:
        schema["l2_source"] = l2_source
    item: dict[str, Any] = {
        "no": no,
        "level_code": level_code,
        "level_name": level_name,
        "id": label_id,
        "name": name,
        "definition": definition,
        "dtype": dtype,
        "value_schema": schema,
        "values_hint": selection_reason or derivation,
        "selection_reason": selection_reason or definition,
    }
    return item


def build_labels() -> list[dict[str, Any]]:
    n = 0

    def nxt() -> int:
        nonlocal n
        n += 1
        return n

    labels: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        labels.append(_node(no=nxt(), **kwargs))

    # --- L0 meta (8) ---
    add(
        label_id="nvh.meta.format",
        level_code="L0",
        level_name="元数据",
        name="文件格式",
        definition="HEAD 采集文件格式标识",
        dtype="enum",
        value_schema={"type": "enum", "values": ["head_acoustics_hdf_v4", "wav", "other"]},
        derivation="auto",
        l2_source="head_meta.json.format",
    )
    add(
        label_id="nvh.meta.fs_hz",
        level_code="L0",
        level_name="元数据",
        name="采样率",
        definition="HEAD .dat 解析后的采样频率",
        dtype="float",
        value_schema={"type": "float", "unit": "Hz", "range_hint": "8000 ~ 192000"},
        derivation="auto",
        l2_source="head_meta.json.fs_hz",
    )
    add(
        label_id="nvh.meta.duration_s",
        level_code="L0",
        level_name="元数据",
        name="时长",
        definition="有效 PCM 时长",
        dtype="float",
        value_schema={"type": "float", "unit": "s", "range_hint": ">0"},
        derivation="auto",
        l2_source="head_meta.json.duration_s",
    )
    add(
        label_id="nvh.meta.n_channels",
        level_code="L0",
        level_name="元数据",
        name="通道数",
        definition="同步声压通道数（HEAD 阵列通常为 4）",
        dtype="int",
        value_schema={"type": "int", "range_hint": "1 ~ 8"},
        derivation="auto",
        l2_source="head_meta.json.n_channels",
    )
    add(
        label_id="nvh.meta.unit",
        level_code="L0",
        level_name="元数据",
        name="物理单位",
        definition="时域样本物理单位；本切片固定 Pa",
        dtype="enum",
        value_schema={"type": "enum", "values": ["Pa"]},
        derivation="auto",
        l2_source="head_meta.json.unit",
    )
    add(
        label_id="nvh.meta.channel_layout",
        level_code="L0",
        level_name="元数据",
        name="通道布局",
        definition="通道名序列；HEAD 默认 VL_VR_HL_HR",
        dtype="enum",
        value_schema={"type": "enum", "values": ["VL_VR_HL_HR", "other"]},
        derivation="auto",
        l2_source="head_meta.json.channels[].name",
    )
    add(
        label_id="nvh.meta.channels",
        level_code="L0",
        level_name="元数据",
        name="通道校准信息",
        definition="每通道名称、map factor、校准说明",
        dtype="composite",
        value_schema={
            "type": "composite",
            "fields": [
                {"name": "name", "type": "string"},
                {"name": "map_factor", "type": "float"},
                {"name": "calibration", "type": "string", "optional": True},
            ],
        },
        derivation="auto",
        l2_source="head_meta.json.channels",
    )
    add(
        label_id="nvh.meta.record_context",
        level_code="L0",
        level_name="元数据",
        name="录制场景说明",
        definition="试验工况、车速、部位、测点文字描述",
        dtype="text",
        value_schema={"type": "string"},
        derivation="human",
    )

    # --- L1.1 clip SPL (10) ---
    add(
        label_id="nvh.clip.spl.leq_db_mean",
        level_code="L1.1",
        level_name="片段级声压",
        name="四通道 Leq 均值",
        definition=f"mean(ch.leq_db)，参考 {PREF_PA} Pa",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/summary.json.channels[].leq_db",
    )
    add(
        label_id="nvh.clip.spl.leq_db_max",
        level_code="L1.1",
        level_name="片段级声压",
        name="四通道 Leq 最大",
        definition="max(ch.leq_db)",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/summary.json",
    )
    add(
        label_id="nvh.clip.spl.leq_db_min",
        level_code="L1.1",
        level_name="片段级声压",
        name="四通道 Leq 最小",
        definition="min(ch.leq_db)",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/summary.json",
    )
    add(
        label_id="nvh.clip.spl.leq_db_spread",
        level_code="L1.1",
        level_name="片段级声压",
        name="通道 Leq 极差",
        definition="max(ch.leq_db) − min(ch.leq_db)",
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="audio_spec/summary.json",
    )
    add(
        label_id="nvh.clip.spl.leq_db_std",
        level_code="L1.1",
        level_name="片段级声压",
        name="通道 Leq 标准差",
        definition="std(ch.leq_db)",
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="audio_spec/summary.json",
    )
    add(
        label_id="nvh.clip.spl.rms_pa_mean",
        level_code="L1.1",
        level_name="片段级声压",
        name="四通道 RMS 均值",
        definition="mean(ch.rms_pa)",
        dtype="float",
        value_schema={"type": "float", "unit": "Pa"},
        derivation="auto",
        l2_source="audio_spec/summary.json.channels[].rms_pa",
    )
    add(
        label_id="nvh.clip.spl.peak_pa_max",
        level_code="L1.1",
        level_name="片段级声压",
        name="全 clip 峰值声压",
        definition="max(|pcm_pa|) 全矩阵",
        dtype="float",
        value_schema={"type": "float", "unit": "Pa"},
        derivation="auto",
        l2_source="pcm_pa.npy",
    )
    add(
        label_id="nvh.clip.spl.peak_db_max",
        level_code="L1.1",
        level_name="片段级声压",
        name="全 clip 峰值 SPL",
        definition="20*log10(peak_pa / 20µPa)",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="pcm_pa.npy",
    )
    add(
        label_id="nvh.clip.spl.dynamic_range_db",
        level_code="L1.1",
        level_name="片段级声压",
        name="动态范围",
        definition="全通道 spl_timeline Lmax − Lmin",
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.spl.level_class",
        level_code="L1.1",
        level_name="片段级声压",
        name="声压等级分档",
        definition="由 leq_db_mean 映射：<70 low / 70–85 medium / 85–100 high / >100 very_high（固定阈值，可后续改配置表）",
        dtype="enum",
        value_schema={"type": "enum", "values": ["low", "medium", "high", "very_high"]},
        derivation="semi",
        l2_source="nvh.clip.spl.leq_db_mean",
    )

    # --- L1.2 clip spec (6) ---
    add(
        label_id="nvh.clip.spec.centroid_hz_mean",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="平均谱质心",
        definition="四通道 STFT 能量加权频率均值",
        dtype="float",
        value_schema={"type": "float", "unit": "Hz"},
        derivation="auto",
        l2_source="audio_spec/{ch}/stft_*.npy",
    )
    add(
        label_id="nvh.clip.spec.dominant_fc_hz",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="主导 1/3 倍频程中心频率",
        definition="四通道 third_octave 能量最大 band 的 fc（能量加权）",
        dtype="float",
        value_schema={"type": "float", "unit": "Hz"},
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )
    add(
        label_id="nvh.clip.spec.low_mid_high_ratio",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="低/中/高频能量比",
        definition="20–500 / 500–2000 / 2–20k Hz 功率比（dB）",
        dtype="composite",
        value_schema={
            "type": "composite",
            "unit": "dB",
            "fields": [
                {"name": "low_db", "type": "float", "unit": "dB_SPL"},
                {"name": "mid_db", "type": "float", "unit": "dB_SPL"},
                {"name": "high_db", "type": "float", "unit": "dB_SPL"},
            ],
        },
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )
    add(
        label_id="nvh.clip.spec.tonality_index",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="纯音感指数",
        definition="max(spl)−median(spl) 相对 15 dB 归一化到 0–1，四通道均值",
        dtype="float",
        value_schema={"type": "float", "range_hint": "0 ~ 1"},
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )
    add(
        label_id="nvh.clip.spec.broadband_flatness",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="宽带平坦度",
        definition="1/3 oct 谱几何均值 / 算术均值，1=完全平坦",
        dtype="float",
        value_schema={"type": "float", "range_hint": "0 ~ 1"},
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )
    add(
        label_id="nvh.clip.spec.spectral_slope_db_oct",
        level_code="L1.2",
        level_name="片段级频域摘要",
        name="谱斜率",
        definition="100 Hz–8 kHz 线性回归斜率",
        dtype="float",
        value_schema={"type": "float", "unit": "dB/oct"},
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )

    # --- L1.3 clip time (8) ---
    add(
        label_id="nvh.clip.time.lmax_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="Lmax",
        definition="全通道 spl_timeline 最大值",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.lmin_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="Lmin",
        definition="全通道 spl_timeline 最小值",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.l10_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="L10",
        definition="合并 timeline 10% 超越级",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.l50_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="L50",
        definition="50% 超越级",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.l90_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="L90",
        definition="90% 超越级（背景噪声近似）",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.crest_factor_db",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="峰值因子",
        definition="Lmax − Leq_mean",
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="nvh.clip.time.lmax_db,nvh.clip.spl.leq_db_mean",
    )
    add(
        label_id="nvh.clip.time.steady_state",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="稳态段判定",
        definition="中间 80% 时长 spl_db 标准差 < 3 dB",
        dtype="bool",
        value_schema={"type": "bool", "values": ["true", "false"]},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.clip.time.active_ratio",
        level_code="L1.3",
        level_name="片段级时域统计",
        name="有效声压占比",
        definition="SPL > (Leq−10 dB) 的时间占比",
        dtype="float",
        value_schema={"type": "float", "range_hint": "0 ~ 1"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )

    # --- L2 channel (12) ---
    ch_defs = (
        ("nvh.ch.leq_db", "各通道 Leq", "全 clip 等效连续声压级", "dB_SPL", "audio_spec/summary.json"),
        ("nvh.ch.lmax_db", "各通道 Lmax", "spl_timeline 最大值", "dB_SPL", "audio_spec/{ch}/spl_timeline.jsonl"),
        ("nvh.ch.lmin_db", "各通道 Lmin", "spl_timeline 最小值", "dB_SPL", "audio_spec/{ch}/spl_timeline.jsonl"),
        ("nvh.ch.l10_db", "各通道 L10", "10% 超越级", "dB_SPL", "audio_spec/{ch}/spl_timeline.jsonl"),
        ("nvh.ch.l90_db", "各通道 L90", "90% 超越级", "dB_SPL", "audio_spec/{ch}/spl_timeline.jsonl"),
        ("nvh.ch.peak_pa", "各通道峰值 Pa", "max |waveform|", "Pa", "pcm_pa.npy"),
        ("nvh.ch.rms_pa", "各通道 RMS Pa", "summary rms_pa", "Pa", "audio_spec/summary.json"),
        ("nvh.ch.crest_factor_db", "各通道峰值因子", "Lmax − Leq", "dB", "derived"),
        ("nvh.ch.low_band_db", "低频带 Leq", "20–500 Hz 1/3 oct 功率和", "dB_SPL", "audio_spec/{ch}/third_octave.json"),
        ("nvh.ch.mid_band_db", "中频带 Leq", "500–2000 Hz", "dB_SPL", "audio_spec/{ch}/third_octave.json"),
        ("nvh.ch.high_band_db", "高频带 Leq", "2–20 kHz", "dB_SPL", "audio_spec/{ch}/third_octave.json"),
        ("nvh.ch.dominant_fc_hz", "各通道主导频率", "third_octave 峰值 fc", "Hz", "audio_spec/{ch}/third_octave.json"),
    )
    for lid, name, definition, unit, src in ch_defs:
        add(
            label_id=lid,
            level_code="L2",
            level_name="通道级",
            name=name,
            definition=definition,
            dtype="composite",
            value_schema=_composite(unit),
            derivation="auto",
            l2_source=src,
        )

    # --- L3 band (8) ---
    add(
        label_id="nvh.band.third_octave",
        level_code="L3",
        level_name="频域明细",
        name="1/3 倍频程谱索引",
        definition="各通道 third_octave.json 路径索引",
        dtype="json_ref",
        value_schema=_json_ref(content="per-channel [{fc_hz, spl_db}, ...]"),
        derivation="auto",
        l2_source="audio_spec/{ch}/third_octave.json",
    )
    add(
        label_id="nvh.band.third_octave_matrix",
        level_code="L3",
        level_name="频域明细",
        name="四通道 1/3 倍频程矩阵",
        definition="聚合 {VL,VR,HL,HR} → [{fc_hz, spl_db}]",
        dtype="json_ref",
        value_schema=_json_ref(content="{VL:[...], VR:[...], HL:[...], HR:[...]}"),
        derivation="auto",
        l2_source="audio_spec/third_octave_matrix.json",
    )
    add(
        label_id="nvh.band.peak_list",
        level_code="L3",
        level_name="频域明细",
        name="显著谱峰列表",
        definition="STFT 局部峰值 top-N：{fc_hz, spl_db, ch, bw_hz}",
        dtype="json_ref",
        value_schema=_json_ref(content="[{fc_hz, spl_db, ch, bw_hz}]"),
        derivation="auto",
        l2_source="audio_spec/{ch}/stft_*.npy",
    )
    add(
        label_id="nvh.band.masking_band",
        level_code="L3",
        level_name="频域明细",
        name="掩蔽频带",
        definition="人工标注主听频段 {f_lo, f_hi}",
        dtype="composite",
        value_schema={
            "type": "composite",
            "fields": [
                {"name": "f_lo_hz", "type": "float", "unit": "Hz"},
                {"name": "f_hi_hz", "type": "float", "unit": "Hz"},
            ],
        },
        derivation="semi",
    )
    add(
        label_id="nvh.band.tonal_components",
        level_code="L3",
        level_name="频域明细",
        name="纯音成分",
        definition="自动检测 + 人工确认的 tonal peaks",
        dtype="json_ref",
        value_schema=_json_ref(content="[{fc_hz, spl_db, prominence_db, confirmed}]"),
        derivation="semi",
        l2_source="audio_spec/{ch}/stft_*.npy",
    )
    add(
        label_id="nvh.band.stft_ref",
        level_code="L3",
        level_name="频域明细",
        name="STFT 产物引用",
        definition="{ch: audio_spec/{ch}/stft_mag.npy}",
        dtype="json_ref",
        value_schema=_json_ref(content="per-channel npy path map"),
        derivation="auto",
        l2_source="audio_spec/{ch}/stft_*.npy",
    )
    add(
        label_id="nvh.band.mel_ref",
        level_code="L3",
        level_name="频域明细",
        name="Mel 谱引用",
        definition="mel_matrix.npy 路径",
        dtype="json_ref",
        value_schema=_json_ref(content="per-channel npy path map"),
        derivation="auto",
        l2_source="audio_spec/{ch}/mel_matrix.npy",
    )
    add(
        label_id="nvh.band.a_weighted_leq_db",
        level_code="L3",
        level_name="频域明细",
        name="A 计权 Leq",
        definition="对 PCM 应用 A-weighting 后算 Leq（扩展算子）",
        dtype="composite",
        value_schema=_composite("dB(A)"),
        derivation="auto",
        l2_source="pcm_pa.npy",
        selection_reason="对标 dB(A) 规范",
    )

    # --- L4 time (6) ---
    add(
        label_id="nvh.time.spl_timeline_ref",
        level_code="L4",
        level_name="时域明细",
        name="SPL 时间曲线引用",
        definition="{VL,VR,HL,HR} → spl_timeline.jsonl",
        dtype="json_ref",
        value_schema=_json_ref(
            content="per-channel jsonl [{t_s, spl_db}]",
            extra={"path_map_keys": list(CH_NAMES)},
        ),
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.time.steady_window",
        level_code="L4",
        level_name="时域明细",
        name="稳态分析窗",
        definition="中间稳态窗 {t_start_s, t_end_s, leq_db}",
        dtype="composite",
        value_schema={
            "type": "composite",
            "fields": [
                {"name": "t_start_s", "type": "float", "unit": "s"},
                {"name": "t_end_s", "type": "float", "unit": "s"},
                {"name": "leq_db", "type": "float", "unit": "dB_SPL"},
            ],
        },
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.time.transient_events",
        level_code="L4",
        level_name="时域明细",
        name="瞬态事件列表",
        definition="超 Leq+6 dB 且 <200 ms 的脉冲 [{t_s, ch, peak_db, dur_ms}]",
        dtype="json_ref",
        value_schema=_json_ref(content="[{t_s, ch, peak_db, dur_ms}]"),
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.time.modulation_index",
        level_code="L4",
        level_name="时域明细",
        name="调制/波动指数",
        definition="spl_timeline 一阶差分 RMS / 均值",
        dtype="float",
        value_schema={"type": "float", "range_hint": "0 ~ 1"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.time.onset_count",
        level_code="L4",
        level_name="时域明细",
        name="起振次数",
        definition="能量上升沿检测计数",
        dtype="int",
        value_schema={"type": "int", "range_hint": ">=0"},
        derivation="auto",
        l2_source="audio_spec/{ch}/spl_timeline.jsonl",
    )
    add(
        label_id="nvh.time.waveform_ref",
        level_code="L4",
        level_name="时域明细",
        name="波形预览引用",
        definition="waveform.json 路径",
        dtype="json_ref",
        value_schema=_json_ref(content="per-channel waveform.json"),
        derivation="auto",
        l2_source="audio_spec/{ch}/waveform.json",
    )

    # --- L5 spatial proxy (10) — NOT DOA ---
    spatial_note = "通道间 proxy，非 DOA / 无波束成形"
    add(
        label_id="nvh.spatial.lr_imbalance_db",
        level_code="L5",
        level_name="通道间空间proxy",
        name="左右不平衡",
        definition="20*log10(mean(VL,HL)/mean(VR,HR)) 基于线性功率。" + spatial_note,
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="nvh.ch.leq_db",
        selection_reason=spatial_note,
    )
    add(
        label_id="nvh.spatial.fb_imbalance_db",
        level_code="L5",
        level_name="通道间空间proxy",
        name="前后不平衡",
        definition="20*log10(mean(VL,VR)/mean(HL,HR))。" + spatial_note,
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="nvh.ch.leq_db",
        selection_reason=spatial_note,
    )
    add(
        label_id="nvh.spatial.max_interchannel_delta_db",
        level_code="L5",
        level_name="通道间空间proxy",
        name="最大通道间 Leq 差",
        definition="max |Li−Lj|",
        dtype="float",
        value_schema={"type": "float", "unit": "dB"},
        derivation="auto",
        l2_source="nvh.ch.leq_db",
    )
    add(
        label_id="nvh.spatial.energy_centroid_lr",
        level_code="L5",
        level_name="通道间空间proxy",
        name="左右能量重心",
        definition="(E_left−E_right)/(E_left+E_right)，E=Leq 线性功率，范围 −1~1",
        dtype="float",
        value_schema={"type": "float", "range_hint": "-1 ~ 1"},
        derivation="auto",
        l2_source="nvh.ch.leq_db",
    )
    add(
        label_id="nvh.spatial.energy_centroid_fb",
        level_code="L5",
        level_name="通道间空间proxy",
        name="前后能量重心",
        definition="前 vs 后能量重心，范围 −1~1",
        dtype="float",
        value_schema={"type": "float", "range_hint": "-1 ~ 1"},
        derivation="auto",
        l2_source="nvh.ch.leq_db",
    )
    add(
        label_id="nvh.spatial.correlation_matrix",
        level_code="L5",
        level_name="通道间空间proxy",
        name="通道互相关系数",
        definition="4×4 Pearson r，由 pcm_pa 计算。" + spatial_note,
        dtype="json_ref",
        value_schema=_json_ref(content="4x4 float matrix, channel order VL VR HL HR"),
        derivation="auto",
        l2_source="pcm_pa.npy",
        selection_reason=spatial_note,
    )
    add(
        label_id="nvh.spatial.coherence_1khz",
        level_code="L5",
        level_name="通道间空间proxy",
        name="1kHz 相干系数",
        definition="STFT 1 kHz bin 跨通道 coherence。无几何时不解读 DOA。",
        dtype="composite",
        value_schema=_composite("coherence", extra={"range_hint": "0 ~ 1"}),
        derivation="auto",
        l2_source="audio_spec/{ch}/stft_*.npy",
        selection_reason=spatial_note,
    )
    add(
        label_id="nvh.spatial.phase_diff_deg_1khz",
        level_code="L5",
        level_name="通道间空间proxy",
        name="1kHz 相位差",
        definition="仅供参考，无阵列几何时不解读 DOA。",
        dtype="composite",
        value_schema=_composite("deg"),
        derivation="auto",
        l2_source="audio_spec/{ch}/stft_*.npy",
        selection_reason=spatial_note,
    )
    add(
        label_id="nvh.spatial.channel_balance_grade",
        level_code="L5",
        level_name="通道间空间proxy",
        name="通道平衡等级",
        definition="spread=max−min Leq：<1 excellent / <3 good / <6 fair / else poor",
        dtype="enum",
        value_schema={"type": "enum", "values": ["excellent", "good", "fair", "poor"]},
        derivation="semi",
        l2_source="nvh.clip.spl.leq_db_spread",
    )
    add(
        label_id="nvh.spatial.symmetry_flag",
        level_code="L5",
        level_name="通道间空间proxy",
        name="左右对称性",
        definition="|lr_imbalance_db| < 2 dB",
        dtype="bool",
        value_schema={"type": "bool", "values": ["true", "false"]},
        derivation="auto",
        l2_source="nvh.spatial.lr_imbalance_db",
    )

    # --- L6 semantic (10) ---
    add(
        label_id="nvh.sem.noise_category",
        level_code="L6",
        level_name="语义主观",
        name="主导噪音类别",
        definition="单一主导类别（enum_tree，含动力总成子类）",
        dtype="enum_tree",
        value_schema={
            "type": "enum_tree",
            "values": [
                {
                    "id": "powertrain",
                    "children": [{"id": "engine"}, {"id": "motor"}, {"id": "transmission"}],
                },
                {"id": "road"},
                {"id": "wind"},
                {"id": "brake"},
                {"id": "hvac"},
                {"id": "electrical"},
                {"id": "structure"},
                {"id": "impulse"},
                {"id": "tonal"},
                {"id": "broadband"},
                {"id": "speech"},
                {"id": "media"},
                {"id": "unknown"},
            ],
        },
        derivation="human",
    )
    add(
        label_id="nvh.sem.noise_sources",
        level_code="L6",
        level_name="语义主观",
        name="噪音来源",
        definition="多选来源列表",
        dtype="composite",
        value_schema={
            "type": "enum",
            "multi": True,
            "values": [
                "engine",
                "tire",
                "aero",
                "fan",
                "compressor",
                "bearing",
                "panel_rattle",
                "road_texture",
                "exhaust",
                "inverter",
                "other",
            ],
        },
        derivation="human",
    )
    add(
        label_id="nvh.sem.tonal_annoyance",
        level_code="L6",
        level_name="语义主观",
        name="纯音烦扰度",
        definition="主观纯音烦扰",
        dtype="enum",
        value_schema={"type": "enum", "values": ["none", "low", "medium", "high"]},
        derivation="human",
    )
    add(
        label_id="nvh.sem.broadband_annoyance",
        level_code="L6",
        level_name="语义主观",
        name="宽带烦扰度",
        definition="主观宽带烦扰",
        dtype="enum",
        value_schema={"type": "enum", "values": ["none", "low", "medium", "high"]},
        derivation="human",
    )
    add(
        label_id="nvh.sem.quality_grade",
        level_code="L6",
        level_name="语义主观",
        name="主观品质等级",
        definition="NVH 主观打分档",
        dtype="enum",
        value_schema={"type": "enum", "values": ["A", "B", "C", "D"]},
        derivation="human",
    )
    add(
        label_id="nvh.sem.spec_compliance",
        level_code="L6",
        level_name="语义主观",
        name="规范符合性",
        definition="相对试验规范的符合性判定",
        dtype="enum",
        value_schema={"type": "enum", "values": ["pass", "fail", "marginal", "na"]},
        derivation="human",
    )
    add(
        label_id="nvh.sem.spec_limit_db",
        level_code="L6",
        level_name="语义主观",
        name="适用限值",
        definition="试验规范中的声压阈值",
        dtype="float",
        value_schema={"type": "float", "unit": "dB_SPL"},
        derivation="human",
    )
    add(
        label_id="nvh.sem.test_point",
        level_code="L6",
        level_name="语义主观",
        name="测点位置",
        definition="如「左前门板」「boardline」",
        dtype="text",
        value_schema={"type": "string"},
        derivation="human",
    )
    add(
        label_id="nvh.sem.annotator_notes",
        level_code="L6",
        level_name="语义主观",
        name="校核备注",
        definition="自由文本",
        dtype="text",
        value_schema={"type": "string"},
        derivation="human",
    )
    add(
        label_id="nvh.sem.ai_hypothesis",
        level_code="L6",
        level_name="语义主观",
        name="AI 辅助猜测",
        definition="可选 VL label stage 预填；首版 deriver 不写入。不覆盖人工字段。",
        dtype="text",
        value_schema={"type": "string"},
        derivation="semi",
    )

    if len(labels) != LABEL_COUNT:
        raise RuntimeError(f"expected {LABEL_COUNT} labels, got {len(labels)}")
    return labels


def yaml_document() -> dict[str, Any]:
    labels = build_labels()
    return {
        "version": VERSION_CODE,
        "taxonomy_id": TAXONOMY_ID,
        "source": "TAX-AUDIO-NVH-v2 HEAD 4ch SPL/noise ground truth",
        "label_count": len(labels),
        "excluded_labels": [],
        "notes": {
            "spatial": "inter-channel proxy only; no DOA / beamforming",
            "json_ref_root": "relative to runs/{run_id}/",
            "level_class_thresholds_db": [70, 85, 100],
            "label_stage": (
                "derive_nvh_labels + stages.label (nvh_sem_ast|nvh_sem_heuristic|nvh_sem_vl); "
                "binds draft audio_nvh-v2; do not global-publish"
            ),
        },
        "labels": labels,
    }


def dump_yaml(path: Path | None = None) -> Path:
    import yaml

    from repo_paths import SHARED_ROOT

    dest = path or (SHARED_ROOT / "config" / "audio_nvh_taxonomy.yaml")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        yaml.dump(yaml_document(), allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return dest


def yaml_labels_for_import() -> list[dict[str, Any]]:
    """Shape expected by taxonomy_import.yaml_labels_to_nodes."""
    return build_labels()


if __name__ == "__main__":
    print(dump_yaml())
