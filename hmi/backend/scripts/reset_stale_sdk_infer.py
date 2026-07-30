import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hmi.local import pipeline_run as pr

if __name__ == "__main__":
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    n = pr.reset_stale_sdk_infer_jobs(stale_minutes=minutes)
    print("reset", n, "job(s) older than", minutes, "minutes")
