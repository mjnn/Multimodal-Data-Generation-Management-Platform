"""Same basename + different content must not overwrite bag storage paths."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from hmi.data_source import LOCAL_OSS_ROOT  # noqa: E402
from hmi.local.bag_upload import bag_storage_dir_name, save_uploaded_rosbag  # noqa: E402


def main() -> None:
    a = b"bag-content-aaa"
    b = b"bag-content-bbb"
    assert a != b

    dir_a = bag_storage_dir_name("output.bag", __import__("hashlib").sha256(a).hexdigest())
    dir_b = bag_storage_dir_name("output.bag", __import__("hashlib").sha256(b).hexdigest())
    assert dir_a != dir_b, (dir_a, dir_b)
    assert dir_a.startswith("output__") and dir_b.startswith("output__")
    print("OK storage dir unique for same basename")

    # Isolate writes under a temp OSS root via env if LOCAL_OSS_ROOT is fixed;
    # exercise save_uploaded_rosbag against real runtime only when writable.
    # Lightweight check: paths differ and both files survive sequential saves.
    import hashlib

    digest_a = hashlib.sha256(a).hexdigest()
    digest_b = hashlib.sha256(b).hexdigest()
    run_id = "00000000-0000-4000-8000-000000000099"
    sa = save_uploaded_rosbag("output.bag", a, run_id=run_id, ds="20990101")
    sb = save_uploaded_rosbag("output.bag", b, run_id=run_id, ds="20990101")
    assert sa["clip_id"] != sb["clip_id"]
    assert sa["oss_key"] != sb["oss_key"]
    assert sa["bag_oss_key"] != sb["bag_oss_key"]
    path_a = Path(str(sa["local_path"]))
    path_b = Path(str(sb["local_path"]))
    assert path_a.is_file() and path_b.is_file()
    assert path_a.read_bytes() == a
    assert path_b.read_bytes() == b
    assert digest_a in sa["clip_id"] and digest_b in sb["clip_id"]
    print("OK sequential same-name uploads keep distinct bag bytes")

    from hmi.local.bag_upload import collection_dir_from_filename

    assert collection_dir_from_filename("0804caiji/20250804_120000/output.bag") == "20250804_120000"
    assert collection_dir_from_filename("output.bag") == "output"
    print("OK collection_dir prefers parent folder for nested paths")
    print("ALL bag_upload unique path checks passed")
    print(f"(LOCAL_OSS_ROOT={LOCAL_OSS_ROOT})")


if __name__ == "__main__":
    main()
