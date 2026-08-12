"""Try RunManualDagNodes with known-good project identifier."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=True)

from alibabacloud_dataworks_public20200518.client import Client
from alibabacloud_dataworks_public20200518 import models as m
from alibabacloud_tea_openapi import models as open_api_models


def main() -> None:
    region = os.getenv("DATAWORKS_REGION_ID", "cn-shanghai")
    cfg = open_api_models.Config(
        access_key_id=os.environ["ODPS_ACCESS_ID"],
        access_key_secret=os.environ["ODPS_ACCESS_KEY"],
        region_id=region,
    )
    cfg.endpoint = f"dataworks.{region}.aliyuncs.com"
    c = Client(cfg)

    project = os.environ["DATAWORKS_PROJECT_NAME"].strip()
    node_id = os.environ["DATAWORKS_NODE_ID"].strip()
    env = os.getenv("DATAWORKS_PROJECT_ENV", "PROD")
    print("project=", project, "node=", node_id, "env=", env)

    biz = datetime.now(timezone.utc).date() - timedelta(days=1)
    biz_s = f"{biz.isoformat()} 00:00:00"
    params = json.dumps(
        {node_id: "ds=20260810 bag_oss_keys=rosbags/_probe.bag max_bags=1"},
        ensure_ascii=False,
    )

    for flow in ["test", "rosbag_labels_pipline", "rosbag_lables_pipline", "p0"]:
        try:
            req = m.RunManualDagNodesRequest(
                project_env=env,
                project_name=project,
                flow_name=flow,
                biz_date=biz_s,
                node_parameters=params,
                include_node_ids=node_id,
            )
            resp = c.run_manual_dag_nodes(req)
            print("OK flow=", flow, "dag_id=", resp.body.dag_id)
            return
        except Exception as exc:
            text = str(exc)
            # Prefer Message=...
            marker = "'Message': '"
            if marker in text:
                msg = text.split(marker, 1)[1].split("'", 1)[0]
            else:
                msg = text[:180]
            print("FAIL flow=", flow, "msg=", msg)


if __name__ == "__main__":
    main()
