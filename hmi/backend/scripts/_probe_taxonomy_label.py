import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hmi.local.pipeline_settings import get_pipeline_settings
s = get_pipeline_settings()
print("id", s.get("taxonomy_version_id"))
print("label", s.get("taxonomy_version_label"))
