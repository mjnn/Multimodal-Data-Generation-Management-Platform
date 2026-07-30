from pathlib import Path

repo = Path(__file__).resolve().parents[1]

HMI_REPLACE = """REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH
PROJECT_ROOT = HMI_ROOT"""

PIPE_REPLACE = """PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT"""

old = "PROJECT_ROOT = Path(__file__).resolve().parents[1]"

for p in (repo / "hmi" / "scripts").glob("*.py"):
    t = p.read_text(encoding="utf-8")
    if "REPO_ROOT = Path(__file__).resolve().parents[2]" in t:
        continue
    if old not in t:
        continue
    t = t.replace(old, HMI_REPLACE, 1)
    t = t.replace("BACKEND_ROOT = PROJECT_ROOT / \"backend\"", "BACKEND_ROOT = BACKEND")
    p.write_text(t, encoding="utf-8")
    print("hmi", p.name)

for folder in ("scripts", "cloud"):
    for p in (repo / "pipeline" / folder).glob("*.py"):
        t = p.read_text(encoding="utf-8")
        if "PIPELINE_ROOT = Path(__file__).resolve().parents[1]" in t and "REPO_ROOT" in t:
            continue
        if old not in t:
            continue
        t = t.replace(old, PIPE_REPLACE, 1)
        for a, b in [
            ('PROJECT_ROOT / "config.yaml"', "CONFIG_PATH"),
            ('PROJECT_ROOT / "dataworks"', 'PIPELINE_ROOT / "dataworks"'),
            ('PROJECT_ROOT / "scripts"', 'PIPELINE_ROOT / "scripts"'),
        ]:
            t = t.replace(a, b)
        p.write_text(t, encoding="utf-8")
        print("pipe", folder, p.name)

print("pass2 done")
