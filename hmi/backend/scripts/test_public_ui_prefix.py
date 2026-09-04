"""直连 :8012/tools/rosbag-labels/ 时剥前缀，assets 与 /api/health 可用。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from hmi.public_prefix import strip_ui_prefix_scope, ui_public_prefix


def test_prefix_parse() -> None:
    os.environ["HMI_PUBLIC_API_BASE"] = "/tools/rosbag-labels/api"
    assert ui_public_prefix() == "/tools/rosbag-labels"
    os.environ["HMI_PUBLIC_API_BASE"] = "/api"
    assert ui_public_prefix() == ""
    os.environ["HMI_PUBLIC_API_BASE"] = "tools/rosbag-labels/api"
    assert ui_public_prefix() == "/tools/rosbag-labels"


def test_strip_scope() -> None:
    os.environ["HMI_PUBLIC_API_BASE"] = "/tools/rosbag-labels/api"
    scope = {
        "path": "/tools/rosbag-labels/assets/index-dWQdwbLO.js",
        "raw_path": b"/tools/rosbag-labels/assets/index-dWQdwbLO.js",
    }
    strip_ui_prefix_scope(scope)
    assert scope["path"] == "/assets/index-dWQdwbLO.js"
    assert scope["raw_path"] == b"/assets/index-dWQdwbLO.js"

    health = {"path": "/tools/rosbag-labels/api/health", "raw_path": b"/tools/rosbag-labels/api/health"}
    strip_ui_prefix_scope(health)
    assert health["path"] == "/api/health"

    already = {"path": "/api/health", "raw_path": b"/api/health"}
    strip_ui_prefix_scope(already)
    assert already["path"] == "/api/health"

    spa = {"path": "/tools/rosbag-labels/", "raw_path": b"/tools/rosbag-labels/"}
    strip_ui_prefix_scope(spa)
    assert spa["path"] == "/"


def test_http_prefixed_routes() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="hmi-prefix-"))
    assets = tmp / "assets"
    assets.mkdir()
    js_name = "index-dWQdwbLO.js"
    (assets / js_name).write_text("window.__HMI_PREFIX_OK=1;\n", encoding="utf-8")
    (tmp / "index.html").write_text(
        "<!doctype html><title>多模数据管理平台</title><div id='root'></div>\n",
        encoding="utf-8",
    )
    os.environ["FRONTEND_DIST"] = str(tmp)
    os.environ["HMI_PUBLIC_API_BASE"] = "/tools/rosbag-labels/api"
    os.environ.setdefault("HMI_JWT_SECRET", "test-secret-public-prefix")
    os.environ.setdefault("HMI_DATA_SOURCE", "local")
    os.environ.setdefault("HMI_TEST_MODE", "1")

    from fastapi.testclient import TestClient

    from hmi.main import app

    client = TestClient(app)
    js = client.get(f"/tools/rosbag-labels/assets/{js_name}")
    assert js.status_code == 200, js.text
    assert "HMI_PREFIX_OK" in js.text
    assert "text/javascript" in (js.headers.get("content-type") or "") or js.text.startswith("window")

    html = client.get("/tools/rosbag-labels/")
    assert html.status_code == 200
    assert "多模数据管理平台" in html.text
    assert html.headers.get("content-type", "").startswith("text/html")

    health = client.get("/tools/rosbag-labels/api/health")
    assert health.status_code == 200, health.text
    assert health.json().get("ok") is True

    bare = client.get("/api/health")
    assert bare.status_code == 200


def main() -> None:
    test_prefix_parse()
    print("OK prefix parse")
    test_strip_scope()
    print("OK strip scope")
    test_http_prefixed_routes()
    print("OK HTTP prefixed assets + health")


if __name__ == "__main__":
    main()
