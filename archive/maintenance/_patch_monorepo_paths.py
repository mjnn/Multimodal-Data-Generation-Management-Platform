from pathlib import Path

repo = Path(__file__).resolve().parents[1]

hmi_old = """PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(PROJECT_ROOT))"""

hmi_new = """REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH"""

pipe_old = """PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(PROJECT_ROOT))"""

pipe_old2 = """PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))"""

pipe_new = """REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT"""


def patch(path: Path, pairs: list[tuple[str, str]]) -> bool:
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in pairs:
        text = text.replace(a, b)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


for p in (repo / "hmi" / "scripts").glob("*.py"):
    patch(p, [(hmi_old, hmi_new)])
    patch(
        p,
        [
            ('PROJECT_ROOT / "config.yaml"', "CONFIG_PATH"),
            ('PROJECT_ROOT / ".env"', "ENV_PATH"),
            ('PROJECT_ROOT / "data" / "real_data"', 'HMI_ROOT / "data" / "real_data"'),
            ('PROJECT_ROOT / "data" / "hmi_local"', 'HMI_ROOT / "data" / "hmi_local"'),
            ("cwd=PROJECT_ROOT", "cwd=str(HMI_ROOT)"),
        ],
    )

for p in (repo / "pipeline" / "scripts").glob("*.py"):
    patch(p, [(pipe_old, pipe_new), (pipe_old2, pipe_new)])
    patch(
        p,
        [
            ('PROJECT_ROOT / "config.yaml"', "CONFIG_PATH"),
            ('PROJECT_ROOT / ".env"', "ENV_PATH"),
            ('PROJECT_ROOT / "sql"', 'PIPELINE_ROOT / "sql"'),
            ('PROJECT_ROOT / "dataworks"', 'PIPELINE_ROOT / "dataworks"'),
            ("PROJECT_ROOT.glob", "PIPELINE_ROOT.glob"),
            ("path.relative_to(PROJECT_ROOT)", "path.relative_to(PIPELINE_ROOT)"),
        ],
    )

print("done")
