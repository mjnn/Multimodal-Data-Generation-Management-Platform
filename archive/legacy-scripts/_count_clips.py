from hmi.local import store

clips = store.query("SELECT clip_id, clip_dir_name FROM dim_clip ORDER BY clip_dir_name")
print("total", len(clips))
demo = [c for c in clips if "demo" in c["clip_id"] or str(c.get("clip_dir_name", "")).startswith("demo_")]
print("demo", len(demo))
for c in clips[:6]:
    print(c["clip_dir_name"])
