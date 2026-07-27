"""Align .cursor/rules/*.mdc with monorepo paths."""
from pathlib import Path

rules = Path(__file__).resolve().parents[1] / ".cursor" / "rules"

pairs = [
    ("backend/hmi/", "hmi/backend/hmi/"),
    ("frontend/", "hmi/frontend/"),
    ("scripts/sync_hmi_local", "hmi/scripts/sync_hmi_local"),
    ("scripts/import_real_data", "hmi/scripts/import_real_data"),
    ("python scripts/", "py -3 pipeline/scripts/"),
    ("`scripts/", "`pipeline/scripts/"),
    ("globs: dataworks/", "globs: pipeline/dataworks/"),
    ('globs: "dataworks/', 'globs: "pipeline/dataworks/'),
    ("`dataworks/", "`pipeline/dataworks/"),
    ("见 `dataworks/", "见 `pipeline/dataworks/"),
    ("：`dataworks/", "：`pipeline/dataworks/"),
    ("： `dataworks/", "： `pipeline/dataworks/"),
    ("粘贴 `dataworks/", "粘贴 `pipeline/dataworks/"),
    ("粘贴 **`dataworks/", "粘贴 **`pipeline/dataworks/"),
    ("详见 **`dataworks/", "详见 **`pipeline/dataworks/"),
    ("详见 `dataworks/", "详见 `pipeline/dataworks/"),
    ("`sql/maxcompute/", "`pipeline/sql/maxcompute/"),
]

fix = [
    ("pipeline/pipeline/", "pipeline/"),
    ("py -3 pipeline/scripts/bundle_all_dataworks", "py -3 pipeline/scripts/bundle_all_dataworks"),
    ("hmi/hmi/frontend", "hmi/frontend"),
    ("hmi/backend/hmi/backend/hmi", "hmi/backend/hmi"),
]

for path in sorted(rules.glob("*.mdc")):
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in pairs:
        if "pipeline/dataworks/" in b and a == "`dataworks/":
            # skip already prefixed
            pass
        text = text.replace(a, b)
    for a, b in fix:
        text = text.replace(a, b)
    # second pass: bare dataworks/ at word boundary in paths not yet prefixed
    import re

    text = re.sub(
        r"(?<![/\w])dataworks/",
        "pipeline/dataworks/",
        text,
    )
    text = text.replace("pipeline/pipeline/dataworks/", "pipeline/dataworks/")
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("updated", path.name)

print("done")
