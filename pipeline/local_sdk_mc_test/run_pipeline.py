#!/usr/bin/env python3
"""按 DataWorks 推荐顺序本地串行跑 SDK 原子节点（或单节点 / 复合 infer）。

用法::

    cd pipeline/local_sdk_mc_test
    copy .env.example .env   # 填 BAG_LOCAL_PATH / ODPS_* / MODEL_BACKEND
    py -3 run_pipeline.py                 # extract→asr→preview→label→embed
    py -3 run_pipeline.py extract asr     # 只跑指定节点
    py -3 run_pipeline.py infer           # 复合一步
    py -3 sdk_label_node.py               # 也可直接跑单文件
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# 确保可 import oms_multimodal（editable / wheel）
_REPO = HERE.parents[1]
_SDK = _REPO / "piplinesdk"
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from sdk_node_common import load_local_env, resolve_backend  # noqa: E402

ATOMIC_ORDER = ("extract", "asr", "preview", "label", "embed")
NODE_MODULES = {
    "extract": "sdk_extract_node",
    "asr": "sdk_asr_node",
    "preview": "sdk_preview_node",
    "label": "sdk_label_node",
    "embed": "sdk_embed_node",
    "infer": "sdk_infer_node",
}


def _run_node(name: str) -> None:
    mod_name = NODE_MODULES[name]
    print(f"\n======== NODE {name} ({mod_name}) ========")
    mod = importlib.import_module(mod_name)
    mod.main()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local SDK MC test runner (DataWorks-parity nodes)")
    parser.add_argument(
        "nodes",
        nargs="*",
        help=f"nodes to run (default: {' '.join(ATOMIC_ORDER)}). Also: infer",
    )
    parser.add_argument("--list", action="store_true", help="list nodes and exit")
    args = parser.parse_args()

    if args.list:
        print("atomic:", " ".join(ATOMIC_ORDER))
        print("composite: infer")
        return

    env_path = load_local_env(override=False)
    backend = resolve_backend()
    print(f"env={env_path or '(none — use env vars)'} model_backend={backend}")

    nodes = list(args.nodes) if args.nodes else list(ATOMIC_ORDER)
    unknown = [n for n in nodes if n not in NODE_MODULES]
    if unknown:
        raise SystemExit(f"unknown nodes: {unknown}; choose from {list(NODE_MODULES)}")

    for name in nodes:
        _run_node(name)

    print("\n======== ALL DONE ========")


if __name__ == "__main__":
    main()
