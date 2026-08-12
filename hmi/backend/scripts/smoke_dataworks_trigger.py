"""Smoke: list business flows + try RunManualDagNodes with fixed project name."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=True)

from alibabacloud_dataworks_public20200518.client import Client
from alibabacloud_dataworks_public20200518 import models as m
from alibabacloud_tea_openapi import models as open_api_models


def client() -> Client:
    region = os.getenv("DATAWORKS_REGION_ID", "cn-shanghai")
    cfg = open_api_models.Config(
        access_key_id=os.environ["ODPS_ACCESS_ID"],
        access_key_secret=os.environ["ODPS_ACCESS_KEY"],
        region_id=region,
    )
    cfg.endpoint = f"dataworks.{region}.aliyuncs.com"
    return Client(cfg)


def main() -> None:
    c = client()
    project = os.environ["DATAWORKS_PROJECT_NAME"]
    print("PROJECT=", project)

    # ListBusiness needs project_id or project_identifier
    # From ListProjects: id=1381309
    req = m.ListBusinessRequest(
        project_id=1381309,
        page_number=1,
        page_size=50,
    )
    try:
        resp = c.list_business(req)
        data = resp.body.data
        biz = getattr(data, "business", None) or getattr(data, "businesses", None) or []
        print("businesses=", len(biz or []))
        for b in biz or []:
            print(
                " ",
                getattr(b, "business_id", None),
                getattr(b, "business_name", None),
                getattr(b, "description", None),
            )
    except Exception as exc:
        print("ListBusiness failed:", type(exc).__name__, exc)

    # ListNodes filtered by keyword if possible
    try:
        nreq = m.ListNodesRequest(
            project_id=1381309,
            project_env=os.getenv("DATAWORKS_PROJECT_ENV", "PROD"),
            page_number=1,
            page_size=50,
        )
        nresp = c.list_nodes(nreq)
        nodes = nresp.body.data.nodes if nresp.body and nresp.body.data else []
        print("nodes sample=", len(nodes or []))
        target = os.getenv("DATAWORKS_NODE_ID")
        for n in nodes or []:
            nid = str(getattr(n, "node_id", "") or "")
            name = getattr(n, "node_name", None)
            if nid == target or (name and "p0" in str(name).lower()) or (name and "sdk" in str(name).lower()):
                print(" MATCH", nid, name, getattr(n, "scheduler_type", None))
        # also print first 15
        for n in (nodes or [])[:15]:
            print(" ", getattr(n, "node_id", None), getattr(n, "node_name", None))
    except Exception as exc:
        print("ListNodes failed:", type(exc).__name__, exc)

    # Dry trigger via our module
    from hmi.services.dataworks_trigger import trigger_sdk_pipeline

    try:
        out = trigger_sdk_pipeline(["rosbags/_hmi_smoke_probe.bag"])
        print("TRIGGER OK", out)
    except Exception as exc:
        print("TRIGGER FAIL", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
