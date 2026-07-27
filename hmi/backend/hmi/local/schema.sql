-- HMI local mirror of MaxCompute tables (subset used by FastAPI)

CREATE TABLE IF NOT EXISTS dim_clip (
  clip_id TEXT PRIMARY KEY,
  clip_dir_name TEXT,
  content_hash TEXT,
  bag_oss_key TEXT,
  active_run_id TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_run (
  run_id TEXT NOT NULL,
  clip_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  status TEXT,
  label_granularity TEXT,
  started_at TEXT,
  updated_at TEXT,
  completed_at TEXT,
  PRIMARY KEY (clip_id, run_id, ds)
);

CREATE TABLE IF NOT EXISTS pipeline_step (
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  step_id TEXT NOT NULL,
  status TEXT,
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  PRIMARY KEY (run_id, ds, step_id)
);

CREATE TABLE IF NOT EXISTS clip_parse_summary (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  bag_stem TEXT,
  bag_file TEXT,
  duration_ns INTEGER,
  duration_sec REAL,
  start_time_ns INTEGER,
  end_time_ns INTEGER,
  message_count INTEGER,
  topics_json TEXT,
  parsed_at TEXT,
  PRIMARY KEY (clip_id, run_id, ds)
);

CREATE TABLE IF NOT EXISTS fact_frame (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  bag_stem TEXT,
  camera TEXT NOT NULL,
  frame_idx INTEGER NOT NULL,
  timestamp_ns INTEGER NOT NULL,
  topic TEXT,
  image_path TEXT,
  PRIMARY KEY (clip_id, run_id, ds, camera, frame_idx)
);
CREATE INDEX IF NOT EXISTS idx_fact_frame_ts
  ON fact_frame (clip_id, run_id, ds, timestamp_ns);

CREATE TABLE IF NOT EXISTS fact_event (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  bag_stem TEXT,
  timestamp_ns INTEGER NOT NULL,
  event_data TEXT,
  PRIMARY KEY (clip_id, run_id, ds, timestamp_ns, event_data)
);
CREATE INDEX IF NOT EXISTS idx_fact_event_ts
  ON fact_event (clip_id, run_id, ds, timestamp_ns);

CREATE TABLE IF NOT EXISTS fact_audio_segment (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  segment_id INTEGER NOT NULL,
  start_ns INTEGER NOT NULL,
  end_ns INTEGER NOT NULL,
  asr_text TEXT,
  confidence REAL,
  model_version TEXT,
  source_chunk_from INTEGER,
  source_chunk_to INTEGER,
  audio_relpath TEXT,
  PRIMARY KEY (clip_id, run_id, ds, segment_id)
);

CREATE TABLE IF NOT EXISTS fact_image_label (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  frame_id TEXT NOT NULL,
  timestamp_ns INTEGER NOT NULL,
  labels_json TEXT,
  model_version TEXT,
  sync_group_id TEXT,
  anchor_timestamp_ns INTEGER,
  label_scope TEXT,
  PRIMARY KEY (clip_id, run_id, ds, frame_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_image_label_ts
  ON fact_image_label (clip_id, run_id, ds, timestamp_ns);

CREATE TABLE IF NOT EXISTS fact_sample_sync_group (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  sync_group_id TEXT NOT NULL,
  anchor_timestamp_ns INTEGER,
  sample_policy TEXT,
  align_window_ms INTEGER,
  frame_ids_json TEXT,
  created_at TEXT,
  PRIMARY KEY (clip_id, run_id, ds, sync_group_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_sample_sync_group_anchor
  ON fact_sample_sync_group (clip_id, run_id, ds, anchor_timestamp_ns);

CREATE TABLE IF NOT EXISTS fact_embedding (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  timestamp_ns INTEGER,
  start_ns INTEGER,
  end_ns INTEGER,
  vector_json TEXT,
  model_version TEXT,
  dim INTEGER,
  storage_mode TEXT,
  PRIMARY KEY (clip_id, run_id, ds, object_type, object_id)
);

CREATE TABLE IF NOT EXISTS sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

-- Clip-level pipeline facts (future: 1 clip = 1 label + 1 aligned vector)
CREATE TABLE IF NOT EXISTS fact_clip_label (
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  taxonomy_version_id TEXT,
  model_version TEXT,
  label_source TEXT NOT NULL DEFAULT 'ai',
  anchor_timestamp_ns INTEGER,
  multi_ai_meta_json TEXT,
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
