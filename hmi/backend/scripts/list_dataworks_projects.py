"""List DataWorks projects visible to current AK (debug helper)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=True)

from alibabacloud_dataworks_public20200518.client import Client
from alibabacloud_dataworks_public20200518 import models as m
from alibabacloud_tea_openapi import models as open_api_models


def main() -> None:
    region = os.getenv("DATAWORKS_REGION_ID", "cn-shanghai")
    config = open_api_models.Config(
        access_key_id=os.environ["ODPS_ACCESS_ID"],
        access_key_secret=os.environ["ODPS_ACCESS_KEY"],
        region_id=region,
    )
    config.endpoint = f"dataworks.{region}.aliyuncs.com"
    client = Client(config)

    print("configured PROJECT_NAME=", repr(os.getenv("DATAWORKS_PROJECT_NAME")))
    print("configured FLOW_NAME=", repr(os.getenv("DATAWORKS_FLOW_NAME")))
    print("configured NODE_ID=", repr(os.getenv("DATAWORKS_NODE_ID")))
    print("configured ENV=", repr(os.getenv("DATAWORKS_PROJECT_ENV")))

    # Prefer ListProjects if present
    if hasattr(client, "list_projects"):
        req = m.ListProjectsRequest(page_number=1, page_size=50)
        resp = client.list_projects(req)
        body = resp.body
        data = getattr(body, "page_result", None) or getattr(body, "data", None) or body
        projects = getattr(data, "project_list", None) or getattr(data, "projects", None) or []
        print("ListProjects count=", len(projects) if projects else 0)
        for p in projects or []:
            pid = getattr(p, "project_id", None) or getattr(p, "project_identifier", None)
            ident = getattr(p, "project_identifier", None) or getattr(p, "project_name", None)
            name = getattr(p, "project_name", None) or getattr(p, "project_name_cn", None)
            print(f"  id={pid} identifier={ident!r} name={name!r}")
        return

    # Fallback: ListMetaDB / GetProjectDetail by name
    if hasattr(client, "get_project_detail"):
        name = os.getenv("DATAWORKS_PROJECT_NAME") or ""
        try:
            resp = client.get_project_detail(m.GetProjectDetailRequest(project_id=None, project_identifier=name))
            print("GetProjectDetail ok", resp.body)
        except Exception as exc:
            print("GetProjectDetail failed:", exc)

    print("No ListProjects on this SDK; methods with Project:", [x for x in dir(client) if "Project" in x][:40])


if __name__ == "__main__":
    main()
