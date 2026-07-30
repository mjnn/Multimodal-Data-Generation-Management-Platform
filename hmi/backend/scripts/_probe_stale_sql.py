import os
import sqlite3

root = os.environ.get("HMI_RUNTIME_ROOT", "")
db = os.path.join(root, "hmi.db")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT run_id, clip_id, started_at,
           datetime(replace(replace(started_at, 'T', ' '), 'Z', '')) AS parsed,
           datetime('now') AS now_utc,
           datetime('now', '-10 minutes') AS cutoff
    FROM pipeline_step
    WHERE step_id='sdk_infer' AND status='running'
    """
).fetchall()
for r in rows:
    print(dict(r))
