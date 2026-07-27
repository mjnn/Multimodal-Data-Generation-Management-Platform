-- Clip-level pipeline facts (future DataWorks: 1 clip = 1 label + 1 vector)

CREATE TABLE IF NOT EXISTS fact_clip_label (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  taxonomy_version_id TEXT,
  model_version TEXT,
  label_source TEXT NOT NULL DEFAULT 'ai',
  anchor_timestamp_ns INTEGER,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (clip_id, run_id, ds)
);
CREATE INDEX IF NOT EXISTS idx_fact_clip_label_run
  ON fact_clip_label (clip_id, run_id);

CREATE TABLE IF NOT EXISTS fact_clip_embedding (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  dim INTEGER NOT NULL,
  model_version TEXT,
  aggregation_method TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (clip_id, run_id, ds)
);
CREATE INDEX IF NOT EXISTS idx_fact_clip_embedding_run
  ON fact_clip_embedding (clip_id, run_id);
