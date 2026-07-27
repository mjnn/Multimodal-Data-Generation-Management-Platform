import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hmi.data_source import LOCAL_DB_PATH
from hmi.local import store
from hmi.local.store import ensure_db
from hmi.services import clips_local

print("db_path:", ensure_db())
print("expected:", LOCAL_DB_PATH)
print("same:", Path(ensure_db()) == LOCAL_DB_PATH)

demo = store.query("SELECT clip_id, clip_dir_name, active_run_id FROM dim_clip WHERE clip_id LIKE 'sha256:demo_%'")
print("demo_in_dim_clip:", len(demo))
for r in demo:
    print(" ", r["clip_dir_name"], r["clip_id"])

all_clips = store.query("SELECT COUNT(*) AS c FROM dim_clip")[0]["c"]
print("total_dim_clip:", all_clips)

light = clips_local.list_clips_light()
demo_light = [c for c in light if "demo_" in c["clip_id"]]
print("demo_in_list_clips_light:", len(demo_light))
for c in demo_light:
    print(" ", c["clip_dir_name"], c.get("clip_label_ready"), c.get("label_granularity"))
