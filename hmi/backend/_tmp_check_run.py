import sqlite3
from pathlib import Path

p = Path(r"D:\cursor_project\rosbag_to_labels_pipline\hmi\data\hmi_runtime\hmi.db")
c = sqlite3.connect(p)
c.row_factory = sqlite3.Row
rid = "3fcea5a8-205c-40cf-9984-dfdb7fb053f0"
for row in c.execute(
    "select step_id, status, error_message from pipeline_step where run_id=? order by step_id",
    (rid,),
):
    print(dict(row))
run = c.execute("select status, updated_at from pipeline_run where run_id=?", (rid,)).fetchone()
print("pipeline_run", dict(run) if run else None)

work = Path(r"D:\cursor_project\rosbag_to_labels_pipline\hmi\data\hmi_runtime\work\sdk_runs\output")
print("work_run exists", work.is_dir())
if work.is_dir():
    for f in sorted(work.iterdir()):
        print(" ", f.name)
