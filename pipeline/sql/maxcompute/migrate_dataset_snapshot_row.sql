-- M4 dataset snapshot rows (HMI export after reviewed clip assembly)
-- Run once on existing MaxCompute project when M4 dataset build goes live.

CREATE TABLE IF NOT EXISTS aig_rosbag__dataset_snapshot_row (
  snapshot_id           STRING COMMENT 'dataset_snapshot UUID',
  clip_id               STRING,
  run_id                STRING,
  x_json                STRING COMMENT 'JSON array of fact_embedding rows',
  y_json                STRING COMMENT 'JSON object from clip_label_review.labels_json',
  taxonomy_version_id   STRING,
  taxonomy_version_code STRING,
  ds                    STRING COMMENT 'pipeline run ds yyyyMMdd'
)
COMMENT 'HMI dataset snapshot export rows (one row per clip)'
PARTITIONED BY (snapshot_id STRING);
