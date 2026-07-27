-- Taxonomy version UUID on Job3 image labels (M2)
-- Run once on existing MaxCompute project after M2 taxonomy publish pipeline is live.

ALTER TABLE aig_rosbag__fact_image_label ADD COLUMNS (
  taxonomy_version_id STRING COMMENT 'HMI taxonomy version UUID'
);
