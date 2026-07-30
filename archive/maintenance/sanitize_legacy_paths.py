"""Strip pre-monorepo absolute paths from committed data artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REAL = REPO / "hmi" / "data" / "real_data" / "pipeline_latest"

LEGACY_BAG = re.compile(
    r"D:[/\\]+cursor_project[/\\]+labeling_and_embedding_test[/\\]+testdata[/\\]+([^/\\]+)[/\\]+output\.bag",
    re.I,
)
LEGACY_OUT = re.compile(
    r"D:[/\\]+cursor_project[/\\]+labeling_and_embedding_test[/\\]+output[/\\]+pipeline_latest[/\\]+([^/\\]+)[/\\]+",
    re.I,
)
LEGACY_CLIP = re.compile(
    r"D:[/\\]+cursor_project[/\\]+labeling_and_embedding_test[/\\]+output[/\\]+pipeline_latest[/\\]+[^/\\]+[/\\]+work[/\\]+output[/\\]+clips[/\\]+output_0000[/\\]+clip_preview_camera(\d)\.mp4",
    re.I,
)
REL_OUT = re.compile(
    r"output[/\\]+pipeline_latest[/\\]+([^/\\]+)[/\\]+",
    re.I,
)
LEGACY_CURSOR = re.compile(
    r"D:[/\\]+cursor_project[/\\]+(?:labeling_and_embedding_test|rosbag_to_labels_pipline)[/\\]+",
    re.I,
)
TESTDATA_FULL = re.compile(
    r"D:[/\\]+cursor_project[/\\]+labeling_and_embedding_test[/\\]+output[/\\]+testdata_full[/\\]+",
    re.I,
)


def read_text_auto(path: Path) -> str | None:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scrub_text(text: str) -> str:
    text = LEGACY_BAG.sub(r"fixtures/bags/\1/output.bag", text)
    text = TESTDATA_FULL.sub("", text)
    text = LEGACY_OUT.sub(r"\1/", text)
    text = LEGACY_CLIP.sub(r"work/output/clips/output_0000/clip_preview_camera\1.mp4", text)
    text = REL_OUT.sub(r"\1/", text)
    text = LEGACY_CURSOR.sub("", text)
    text = text.replace("labeling_and_embedding_test", "oms-multimodal-sdk")
    text = text.replace("AIG_Projects", "rosbag-labels")
    return text


def scrub_jsonl_clip_videos(path: Path) -> None:
    line = path.read_text(encoding="utf-8").strip()
    if not line:
        return
    row = json.loads(line)
    run_name = path.parent.name
    base = f"work/output/clips/output_0000"
    row["clip_video_path"] = f"{base}/clip_preview_camera0.mp4"
    paths = row.get("clip_video_paths") or {}
    for topic, _old in list(paths.items()):
        cam = "0"
        if "camera1" in topic or "camera1" in str(_old):
            cam = "1"
        elif "camera2" in topic:
            cam = "2"
        paths[topic] = f"{base}/clip_preview_camera{cam}.mp4"
    row["clip_video_paths"] = paths
    cfg = row.get("clip_video_config") or {}
    enc = cfg.get("encoded_cameras") or []
    for item in enc:
        if isinstance(item, dict) and "path" in item:
            topic = str(item.get("camera_topic") or "")
            cam = "0"
            if "camera1" in topic:
                cam = "1"
            elif "camera2" in topic:
                cam = "2"
            item["path"] = f"{base}/clip_preview_camera{cam}.mp4"
    if cfg:
        row["clip_video_config"] = cfg
    ap = row.get("audio_path")
    if isinstance(ap, str) and ("\\" in ap or "labeling" in ap or "cursor_project" in ap):
        row["audio_path"] = f"{base}/audio.wav"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    for path in REAL.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".json", ".jsonl", ".log"}:
            text = read_text_auto(path)
            if text is None:
                continue
            new = scrub_text(text)
            if path.name == "clip_videos.jsonl":
                scrub_jsonl_clip_videos(path)
                print("clip_videos", path.relative_to(REPO))
                continue
            if new != text:
                path.write_text(new, encoding="utf-8")
                print("scrubbed", path.relative_to(REPO))

    manifest = REPO / "pipeline" / "clips" / "2026-06-05_13-27-07" / "rosbag" / "manifest.json"
    if manifest.is_file():
        t = scrub_text(manifest.read_text(encoding="utf-8"))
        t = re.sub(r"D:[/\\][^\"]+[/\\]clips[/\\]", "pipeline/clips/", t)
        manifest.write_text(t, encoding="utf-8")
        print("scrubbed", manifest.relative_to(REPO))


if __name__ == "__main__":
    main()
