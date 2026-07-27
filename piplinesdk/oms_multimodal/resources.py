"""安装包内随 wheel 分发的资源路径。"""
from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
BUNDLED_DIR = _PKG_DIR / "bundled"


def bundled_taxonomy_path() -> Path:
    return BUNDLED_DIR / "oms_label_taxonomy.yaml"


def bundled_sdk_doc_path() -> Path:
    return BUNDLED_DIR / "SDK.md"


def resolve_taxonomy_path(path: str | Path | None = None) -> Path:
    """解析 taxonomy：显式路径 > 包内 bundled > 项目根默认文件名。"""
    if path is not None:
        candidate = Path(path)
        if candidate.exists():
            return candidate
    bundled = bundled_taxonomy_path()
    if bundled.exists():
        return bundled
    fallback = Path("oms_label_taxonomy.yaml")
    return fallback
