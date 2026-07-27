-- MaxCompute DDL for rosbag_to_labels pipeline
-- Table prefix: aig_rosbag__
-- Job1 表结构与本地 timeline.db 1:1（见 timeline_db.py）
-- 分区列 ds：入库日期 yyyyMMdd，写入时由 Job 赋值

-- ---------------------------------------------------------------------------
-- 维度 / 调度（Job0~Job1）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aig_rosbag__dim_clip (
  clip_id         STRING COMMENT '内容 hash，主键，格式 sha256:{hex}',
  clip_dir_name   STRING COMMENT '采集目录名（本地开发用，上云可空）',
  content_hash    STRING COMMENT 'SHA256 hex，不含前缀',
  bag_oss_key     STRING COMMENT 'bag 的 OSS object key；Job0 发现与 Job1 解析同一路径，禁止拷贝',
  active_run_id   STRING COMMENT '当前生效 pipeline run_id',
  created_at      STRING COMMENT 'ISO8601 UTC',
  updated_at      STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Clip 维度表';

-- 已建表环境升级（P4 统一路径；ADD COLUMNS 追加在末列，写入顺序见 job0_discover_node）：
-- ALTER TABLE aig_rosbag__dim_clip ADD COLUMNS (bag_oss_key STRING COMMENT 'bag OSS object key');

-- Job0 dispatch → ODPS SQL 赋值节点 读取；PyODPS3 无法把运行时计算结果导出为节点输出参数
CREATE TABLE IF NOT EXISTS aig_rosbag__dispatch_staging (
  action          STRING COMMENT 'run | idle',
  reason          STRING COMMENT 'new_run | resume_incomplete | no_pending_clip',
  clip_id         STRING,
  run_id          STRING,
  clip_dir_name   STRING,
  bag_oss_key     STRING,
  dispatched_at   STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Job0 dispatch 单行暂存，供 job0_dispatch_out 赋值节点 SELECT'
PARTITIONED BY (ds STRING COMMENT '业务日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__pipeline_run (
  run_id            STRING COMMENT 'UUID',
  clip_id           STRING,
  status            STRING COMMENT 'pending/running/completed/failed',
  started_at        STRING COMMENT 'ISO8601 UTC',
  updated_at        STRING COMMENT 'ISO8601 UTC',
  completed_at      STRING COMMENT 'ISO8601 UTC，可空'
)
COMMENT '管线 run 版本（每次执行一条）'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__pipeline_step (
  run_id          STRING,
  step_id         STRING COMMENT 'job1_parse/job2_sample/job2_asr/job3_label/job4_embed',
  status          STRING,
  started_at      STRING,
  finished_at     STRING,
  error_message   STRING
)
COMMENT '管线步骤明细'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

-- ---------------------------------------------------------------------------
-- Job1 解析产物（时间轴对齐中枢）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_message_timeline (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  topic           STRING,
  msgtype         STRING,
  modality        STRING COMMENT 'frame/audio/metadata/event/unknown',
  timestamp_ns    BIGINT COMMENT 'rosbag record_time_ns，统一时间基准',
  sequence_idx    BIGINT COMMENT 'clip+run+bag 内递增序号'
)
COMMENT '全 topic 消息时间轴'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_frame (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  camera          STRING COMMENT 'camera0..3',
  frame_idx       BIGINT,
  timestamp_ns    BIGINT,
  topic           STRING,
  image_path      STRING COMMENT '相对 parsed 目录或 OSS 路径'
)
COMMENT '相机帧索引'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_audio_chunk (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  chunk_idx       BIGINT,
  timestamp_ns    BIGINT,
  byte_offset     BIGINT,
  byte_length     BIGINT,
  sample_count    BIGINT,
  duration_ns     BIGINT,
  pcm_bytes       BIGINT
)
COMMENT '音频 chunk 索引（对应 chunks.jsonl）'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_event (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  timestamp_ns    BIGINT,
  event_data      STRING COMMENT '原始 event JSON 文本'
)
COMMENT '事件标签时间轴'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__clip_parse_summary (
  clip_id         STRING,
  run_id          STRING,
  bag_stem        STRING,
  bag_file        STRING,
  duration_ns     BIGINT,
  duration_sec      DOUBLE,
  start_time_ns   BIGINT,
  end_time_ns     BIGINT,
  message_count   BIGINT,
  topics_json     STRING COMMENT 'topic 统计 JSON',
  parsed_at       STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Job1 解析汇总'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

-- ---------------------------------------------------------------------------
-- Job2~Job4 产物（占位，后续 MaxFrame Job 写入）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_sample_policy (
  clip_id         STRING,
  run_id          STRING,
  policy_name     STRING,
  policy_params   STRING COMMENT 'JSON：config 快照',
  created_at      STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Job2 抽样策略快照'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_audio_segment (
  clip_id           STRING,
  run_id            STRING,
  segment_id        BIGINT,
  start_ns          BIGINT COMMENT 'bag 绝对时间',
  end_ns            BIGINT,
  asr_text          STRING,
  confidence        DOUBLE,
  model_version     STRING,
  source_chunk_from BIGINT,
  source_chunk_to   BIGINT
)
COMMENT 'Job2 ASR 分段'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

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

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_image_label (
  clip_id               STRING,
  run_id                STRING,
  frame_id              STRING COMMENT 'camera:frame_idx',
  timestamp_ns          BIGINT,
  labels_json           STRING COMMENT 'OMS 标签 JSON',
  model_version         STRING,
  sync_group_id         STRING COMMENT 'uniform_sync 对齐组 id',
  anchor_timestamp_ns   BIGINT COMMENT '对齐锚点；L1.1 时间标签基准',
  label_scope           STRING COMMENT 'frame|sync_group'
)
COMMENT 'Job3 图像打标'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_embedding (
  clip_id         STRING,
  run_id          STRING,
  object_type     STRING COMMENT 'frame|audio_segment|event',
  object_id       STRING,
  timestamp_ns    BIGINT COMMENT '点对象时间戳',
  start_ns        BIGINT COMMENT '段对象起始',
  end_ns          BIGINT COMMENT '段对象结束',
  vector_json     STRING COMMENT '向量 JSON 数组，或后续改 ARRAY<DOUBLE>',
  model_version   STRING,
  dim             BIGINT,
  storage_mode    STRING COMMENT 'separate|unified'
)
COMMENT 'Job4 向量'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

-- ---------------------------------------------------------------------------
-- Clip-level facts (future pipeline: 1 clip = 1 structured label + 1 vector)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_clip_label (
  clip_id               STRING,
  run_id                STRING,
  labels_json           STRING COMMENT 'clip 级 OMS 结构化标签 JSON',
  taxonomy_version_id   STRING COMMENT '打标时选用的已发布 taxonomy 版本',
  model_version         STRING,
  label_source          STRING COMMENT 'ai|human',
  anchor_timestamp_ns   BIGINT COMMENT '代表性时刻，供 HMI 跳转',
  created_at            STRING COMMENT 'ISO8601 UTC',
  updated_at            STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Clip 级结构化标签（未来管线主产物）'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');

CREATE TABLE IF NOT EXISTS aig_rosbag__fact_clip_embedding (
  clip_id               STRING,
  run_id                STRING,
  vector_json           STRING COMMENT 'clip 级多模对齐向量 JSON 数组',
  dim                   BIGINT,
  model_version         STRING,
  aggregation_method    STRING COMMENT 'clip_native|mean_pool|...',
  created_at            STRING COMMENT 'ISO8601 UTC',
  updated_at            STRING COMMENT 'ISO8601 UTC'
)
COMMENT 'Clip 级多模对齐向量（未来管线主产物）'
PARTITIONED BY (ds STRING COMMENT '入库日期 yyyyMMdd');
