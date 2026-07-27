-- OPTIONAL: DataWorks Standard+ assignment node only (not required for OSS path).
-- See dataworks/DISPATCH_PARAMS.md
SELECT TO_JSON(
  NAMED_STRUCT(
    'action', action,
    'reason', reason,
    'clip_id', clip_id,
    'run_id', run_id,
    'clip_dir_name', clip_dir_name,
    'bag_oss_key', bag_oss_key,
    'dispatched_at', dispatched_at
  )
) AS dispatch_json
FROM ${table_prefix}dispatch_staging
WHERE ds = '${ds}'
LIMIT 1;
