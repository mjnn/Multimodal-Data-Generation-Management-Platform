"""One-off: align pipeline/dataworks/*.md paths with monorepo layout."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dw = root / "pipeline" / "dataworks"

replacements = [
    ("backend/hmi/", "hmi/backend/hmi/"),
    ("data/hmi_local/", "hmi/data/hmi_local/"),
    ("`config.yaml`", "`shared/config.yaml`"),
    ("config.yaml` →", "shared/config.yaml` →"),
    ("见 `config.yaml`", "见 `shared/config.yaml`"),
    ("定义于 `config.yaml`", "定义于 `shared/config.yaml`"),
    ("| `config.yaml` |", "| `shared/config.yaml` |"),
    ("python scripts/", "py -3 pipeline/scripts/"),
    ("`scripts/", "`pipeline/scripts/"),
    ("dataworks/bundled/", "pipeline/dataworks/bundled/"),
    ("`dataworks/", "`pipeline/dataworks/"),
    ("见 `dataworks/", "见 `pipeline/dataworks/"),
    ("（`dataworks/", "（`pipeline/dataworks/"),
    ("粘贴 **`dataworks/", "粘贴 **`pipeline/dataworks/"),
    ("`dataworks/job", "`pipeline/dataworks/job"),
    ("`dataworks/workflow", "`pipeline/dataworks/workflow"),
    ("`dataworks/pipeline", "`pipeline/dataworks/pipeline"),
    ("`dataworks/mf_ai", "`pipeline/dataworks/mf_ai"),
    ("`dataworks/MAXFRAME", "`pipeline/dataworks/MAXFRAME"),
    ("`dataworks/DISPATCH", "`pipeline/dataworks/DISPATCH"),
    ("`dataworks/PARAMETERS", "`pipeline/dataworks/PARAMETERS"),
    ("`dataworks/label_merge", "`pipeline/dataworks/label_merge"),
    ("`dataworks/WORKFLOW", "`pipeline/dataworks/WORKFLOW"),
    ("`dataworks/sample_sync", "`pipeline/dataworks/sample_sync"),
    ("`dataworks/oms_time", "`pipeline/dataworks/oms_time"),
    ("`sql/maxcompute/", "`pipeline/sql/maxcompute/"),
    ("../sql/", "../pipeline/sql/"),  # avoid double if any
    ("`../dataworks/", "`../pipeline/dataworks/"),
    ("archive/legacy-scripts/mock_pipeline_artifacts.py", "archive/legacy-scripts/mock_pipeline_artifacts.py"),
]

# Fix double pipeline/pipeline
fix_double = [
    ("pipeline/pipeline/", "pipeline/"),
    ("py -3 pipeline/pipeline/scripts/", "py -3 pipeline/scripts/"),
]

for path in sorted(dw.glob("*.md")):
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in replacements:
        text = text.replace(a, b)
    for a, b in fix_double:
        text = text.replace(a, b)
    # mock script path
    text = text.replace(
        "py -3 pipeline/scripts/mock_pipeline_artifacts.py",
        "py -3 archive/legacy-scripts/mock_pipeline_artifacts.py",
    )
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("updated", path.name)

print("done")
