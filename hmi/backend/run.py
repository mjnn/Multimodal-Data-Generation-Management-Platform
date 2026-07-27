#!/usr/bin/env python3
"""Start HMI API: uvicorn hmi.main:app --reload --port 8000"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("hmi.main:app", host="127.0.0.1", port=8000, reload=True)
