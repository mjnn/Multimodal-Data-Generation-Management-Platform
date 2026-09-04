#!/usr/bin/env python3
"""启动 HMI API：uvicorn hmi.main:app --reload --port 8000。

在 `hmi/backend` 执行 `py -3 run.py`。前端 Vite 默认把 /api 代理到本端口。
若 Windows 上 health 像旧进程，先结束残留 python 再启动。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "hmi.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT)],
    )
