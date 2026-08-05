"""MaxCompute / MaxFrame 后端配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

McImageMode = Literal["auto", "base64", "oss_url"]

DEFAULT_MODELSET_PROJECT = "bigdata_public_modelset"


@dataclass
class McBackendConfig:
    """``MODEL_BACKEND=mc`` 时的 MaxFrame AI 运行参数。"""

    odps_entry: Any | None = None
    modelset_project: str = DEFAULT_MODELSET_PROJECT
    cloud_region: str = "cn-shanghai"
    oss_bucket: str = ""
    dpe_image: str | None = None
    cu_quota_name: str | None = None
    gu_quota_name: str | None = None
    total_rpm_limit: int | None = None
    request_timeout_sec: int | None = None
    ai_memory: str | None = None
    image_mode: McImageMode = "auto"
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    # Omni 未上架 modelset 前，用 VL 模型（如 qwen3.6-plus）做结构化打标
    omni_fallback_model: str | None = None
    parallel_partitions: int = 1

    @classmethod
    def from_env(cls, *, odps_entry: Any | None = None) -> McBackendConfig:
        image_raw = os.getenv("MC_IMAGE_MODE", "auto").strip().lower()
        image_mode: McImageMode = image_raw if image_raw in {"auto", "base64", "oss_url"} else "auto"
        rpm_raw = os.getenv("MC_TOTAL_RPM_LIMIT", "").strip()
        timeout_raw = os.getenv("MC_REQUEST_TIMEOUT_SEC", "").strip()
        partitions_raw = os.getenv("MC_PARALLEL_PARTITIONS", "1").strip()
        return cls(
            odps_entry=odps_entry,
            modelset_project=os.getenv("MC_MODELSET_PROJECT", DEFAULT_MODELSET_PROJECT).strip()
            or DEFAULT_MODELSET_PROJECT,
            cloud_region=os.getenv("MC_CLOUD_REGION", "cn-shanghai").strip() or "cn-shanghai",
            oss_bucket=os.getenv("MC_OSS_BUCKET", os.getenv("OSS_BUCKET", "")).strip(),
            dpe_image=os.getenv("MC_DPE_IMAGE", os.getenv("DPE_IMAGE", "")).strip() or None,
            cu_quota_name=os.getenv("MC_AI_CU_QUOTA_NAME", os.getenv("AI_CU_QUOTA_NAME", "")).strip() or None,
            gu_quota_name=os.getenv("MC_AI_GU_QUOTA_NAME", os.getenv("AI_GU_QUOTA_NAME", "")).strip() or None,
            total_rpm_limit=int(rpm_raw) if rpm_raw.isdigit() else None,
            request_timeout_sec=int(timeout_raw) if timeout_raw.isdigit() else None,
            ai_memory=os.getenv("MC_AI_MEMORY", "").strip() or None,
            image_mode=image_mode,
            oss_access_key_id=os.getenv("OSS_VL_ACCESS_KEY_ID", os.getenv("MC_OSS_ACCESS_KEY_ID", "")).strip()
            or None,
            oss_access_key_secret=os.getenv("OSS_VL_ACCESS_KEY_SECRET", os.getenv("MC_OSS_ACCESS_KEY_SECRET", "")).strip()
            or None,
            omni_fallback_model=os.getenv("MC_OMNI_FALLBACK_MODEL", "").strip() or None,
            parallel_partitions=max(int(partitions_raw), 1) if partitions_raw.isdigit() else 1,
        )

    def storage_options(self) -> dict[str, str] | None:
        ak = (self.oss_access_key_id or "").strip()
        sk = (self.oss_access_key_secret or "").strip()
        if ak and sk:
            return {"access_key_id": ak, "access_key_secret": sk}
        return None

    def resolved_image_mode(self) -> McImageMode:
        if self.image_mode != "auto":
            return self.image_mode
        if self.storage_options() and self.oss_bucket:
            return "oss_url"
        return "base64"
