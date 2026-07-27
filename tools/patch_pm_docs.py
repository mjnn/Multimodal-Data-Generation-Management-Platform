"""Update project-management + docs/m*.md for monorepo paths."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]

pairs = [
    ("backend/hmi/", "hmi/backend/hmi/"),
    ("backend/scripts/", "hmi/backend/scripts/"),
    ("`backend/hmi/", "`hmi/backend/hmi/"),
    ("scripts/enqueue_review_clips.py", "hmi/scripts/enqueue_review_clips.py"),
    ("scripts/build_dataset_snapshot.py", "hmi/scripts/build_dataset_snapshot.py"),
    ("scripts/import_taxonomy_yaml.py", "hmi/scripts/import_taxonomy_yaml.py"),
    ("scripts/bootstrap_admin.py", "hmi/scripts/bootstrap_admin.py"),
    ("dataworks/", "pipeline/dataworks/"),
    ("data/app.db", "hmi/data/app.db"),
    ("data/hmi_local", "hmi/data/hmi_local"),
]

fix = [
    ("pipeline/pipeline/dataworks/", "pipeline/dataworks/"),
    ("hmi/hmi/backend/", "hmi/backend/"),
]

paths = list((root / "project-management").rglob("*.md"))
paths += list((root / "docs").glob("m*.md"))

for path in paths:
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in pairs:
        text = text.replace(a, b)
    for a, b in fix:
        text = text.replace(a, b)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("updated", path.relative_to(root))

print("done")
