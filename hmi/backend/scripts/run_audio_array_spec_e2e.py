"""E2E: upload HEAD .dat -> lake -> audio_array_spec platform_run -> verify artifacts."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8000"
DEFAULT_DAT = Path(r"C:\Users\svw\Downloads\CBK1-4266 saixin steelsuokou-boardline.dat")


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {err}") from exc


def main() -> int:
    dat_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DAT
    if not dat_path.is_file():
        print(f"file not found: {dat_path}", file=sys.stderr)
        return 1

    token = None
    for pwd in ("admin123", "adminpass123"):
        try:
            token = req("POST", "/api/auth/login", {"username": "admin", "password": pwd})["access_token"]
            print(f"login ok (admin / {pwd})")
            break
        except Exception:
            continue
    if not token:
        print("login failed", file=sys.stderr)
        return 1

    types = req("GET", "/api/platform/data-types", token=token)
    ids = [t["id"] for t in types.get("items", [])]
    print("data_types:", ids)
    if "audio_array_spec" not in ids:
        print("audio_array_spec missing — restart backend", file=sys.stderr)
        return 1

    raw = dat_path.read_bytes()
    print(f"uploading {dat_path.name} ({len(raw)} bytes) ...")
    src = req(
        "POST",
        "/api/platform/sources",
        {
            "kind": "audio",
            "filename": dat_path.name,
            "content_b64": base64.b64encode(raw).decode("ascii"),
        },
        token=token,
    )
    print("source_id:", src.get("source_id"))
    print("local_path:", src.get("local_path"))

    sample = req("POST", "/api/platform/samples", {"source_ids": [src["source_id"]]}, token=token)
    print("sample_id:", sample.get("sample_id"))

    pf = req(
        "POST",
        "/api/platform/runs/preflight",
        {"sample_id": sample["sample_id"], "data_type_id": "audio_array_spec"},
        token=token,
    )
    print("preflight:", pf)
    if not pf.get("ok"):
        return 1

    run = req(
        "POST",
        "/api/platform/runs",
        {"sample_id": sample["sample_id"], "data_type_id": "audio_array_spec"},
        token=token,
    )
    run_id = str(run["run_id"])
    print("platform_run_id:", run_id)

    os.environ["HMI_DATA_SOURCE"] = "local"
    runtime = REPO / "hmi" / "data" / "hmi_runtime"
    os.environ["HMI_RUNTIME_ROOT"] = str(runtime)
    sys.path.insert(0, str(REPO / "hmi" / "backend"))

    from hmi.local import store as local_store
    from hmi.platform.store import get_run

    deadline = time.time() + 300
    last_status = None
    while time.time() < deadline:
        row = get_run(run_id)
        st = row["status"] if row else None
        if st != last_status:
            print(f"platform_run status={st}")
            last_status = st
        pr = local_store.query_one("SELECT status FROM pipeline_run WHERE run_id=?", (run_id,))
        if pr:
            print(f"  pipeline_run status={pr['status']}")
        if st in ("completed", "labeled", "failed"):
            break
        time.sleep(5)
    else:
        print("timeout waiting for run completion", file=sys.stderr)

    row = get_run(run_id)
    if not row:
        print("run not found", file=sys.stderr)
        return 1

    print("final status:", row["status"])
    if row["status"] == "failed":
        health = req("GET", "/api/health")
        print("worker last_error:", health.get("local_sdk_poller", {}).get("last_error"))
        steps = local_store.query(
            "SELECT step_id, status, error_message FROM pipeline_step WHERE run_id=?",
            (run_id,),
        )
        for s in steps:
            if s.get("error_message"):
                print(f"  step {s['step_id']}: {s['status']} — {s['error_message'][:500]}")
        return 1

    summaries = sorted(runtime.rglob("audio_spec_summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        print("no audio_spec_summary.json found", file=sys.stderr)
        return 1

    summary_path = summaries[-1]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    spec_dir = summary_path.parent / "audio_spec"
    channel_names = [c.get("name") for c in summary.get("channels", [])]
    print("summary:", summary_path)
    print("channels:", channel_names)
    print("duration_s:", summary.get("duration_s"))
    print("spec_dir exists:", spec_dir.is_dir())
    if spec_dir.is_dir():
        for ch in channel_names or []:
            ch_dir = spec_dir / ch
            if ch_dir.is_dir():
                names = sorted(p.name for p in ch_dir.iterdir())
                print(f"  {ch}: {names}")
            else:
                print(f"  missing channel dir: {ch}")

    health = req("GET", "/api/health")
    poller = health.get("local_sdk_poller", {})
    print("poller last_run_id:", poller.get("last_run_id"))
    print("poller last_error:", poller.get("last_error"))

    ok = row["status"] in ("completed", "labeled") and spec_dir.is_dir() and len(channel_names) == 4
    print("E2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
