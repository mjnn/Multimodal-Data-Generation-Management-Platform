-- 四路同步抽样 + Job3 对齐打标（在已有项目上执行一次）
-- 新表
CREATE TABLE IF NOT EXISTS aig_rosbag__fact_sample_sync_group (
  clip_id              STRING,
  run_id               STRING,
  sync_group_id        STRING,
  anchor_timestamp_ns  BIGINT COMMENT '对齐锚点时间（record_time_ns）',
  sample_policy        STRING,
  align_window_ms      BIGINT,
  frame_ids_json       STRING COMMENT 'JSON 数组：camera:frame_idx',
  created_at           STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Job2 四路时间对齐抽样组'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

-- 扩展 Job3 标签表（若列已存在可忽略报错）
ALTER TABLE aig_rosbag__fact_image_label ADD COLUMNS (
  sync_group_id         STRING COMMENT 'uniform_sync 对齐组 id',
  anchor_timestamp_ns   BIGINT COMMENT '对齐锚点；L1.1 时间标签基准',
  label_scope           STRING COMMENT 'frame|sync_group'
);
