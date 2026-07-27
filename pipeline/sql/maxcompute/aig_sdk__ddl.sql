-- MaxCompute DDL: SDK-first pipeline (layout_version sdk_v1)
-- Table prefix: aig_sdk__
-- Partition ds: yyyyMMdd ingest date

CREATE TABLE IF NOT EXISTS aig_sdk__dim_clip (
  clip_id         STRING COMMENT 'sha256:{bag_content_hex}',
  clip_dir_name   STRING COMMENT 'SDK run folder name or display label',
  content_hash    STRING COMMENT 'SHA256 hex without sha256: prefix',
  bag_oss_key     STRING COMMENT 'rosbags/... object key',
  active_run_id   STRING COMMENT 'current pipeline run_id',
  layout_version  STRING COMMENT 'sdk_v1',
  created_at      STRING COMMENT 'ISO8601 UTC',
  updated_at      STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Clip dimension (SDK)';

CREATE TABLE IF NOT EXISTS aig_sdk__dispatch_staging (
  action          STRING,
  reason          STRING,
  clip_id         STRING,
  run_id          STRING,
  clip_dir_name   STRING,
  bag_oss_key     STRING,
  layout_version  STRING,
  dispatched_at   STRING
)
COMMENT 'Dispatch staging row'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__pipeline_run (
  run_id            STRING,
  clip_id           STRING,
  status            STRING COMMENT 'pending/running/completed/failed',
  layout_version    STRING COMMENT 'sdk_v1',
  label_granularity STRING COMMENT 'clip',
  started_at        STRING,
  updated_at        STRING,
  completed_at      STRING
)
COMMENT 'SDK pipeline run'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__pipeline_step (
  run_id          STRING,
  step_id         STRING COMMENT 'sdk_discover/sdk_infer/sdk_upload/sdk_mc_write/sdk_dispatch',
  status          STRING,
  started_at      STRING,
  finished_at     STRING,
  error_message   STRING
)
COMMENT 'SDK pipeline steps'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__clip_parse_summary (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  bag_file        STRING,
  duration_ns     BIGINT,
  duration_sec    DOUBLE,
  start_time_ns   BIGINT,
  end_time_ns     BIGINT,
  camera_count    BIGINT,
  parsed_at       STRING
)
COMMENT 'Clip summary from labels.jsonl + clip_videos.jsonl'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__fact_clip_label (
  clip_id               STRING,
  run_id                STRING,
  labels_json           STRING,
  taxonomy_version_id   STRING,
  model_version         STRING,
  label_source          STRING COMMENT 'ai|human',
  anchor_timestamp_ns   BIGINT,
  scene_summary         STRING,
  labels_jsonl_oss_key  STRING,
  created_at            STRING,
  updated_at            STRING
)
COMMENT 'Clip labels from labels.jsonl'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__fact_clip_embedding (
  clip_id               STRING,
  run_id                STRING,
  vector_json           STRING,
  dim                   BIGINT,
  model_version         STRING,
  aggregation_method    STRING,
  embeddings_jsonl_oss_key STRING,
  created_at            STRING,
  updated_at            STRING
)
COMMENT 'Clip embedding from fusion_embeddings.jsonl'
PARTITIONED BY (ds STRING);

CREATE TABLE IF NOT EXISTS aig_sdk__fact_audio_segment (
  clip_id           STRING,
  run_id            STRING,
  segment_id        BIGINT,
  start_ns          BIGINT,
  end_ns            BIGINT,
  asr_text          STRING,
  confidence        DOUBLE,
  model_version     STRING,
  audio_relpath     STRING COMMENT 'preview/audio.wav under run prefix'
)
COMMENT 'ASR from labels.jsonl'
PARTITIONED BY (ds STRING);
