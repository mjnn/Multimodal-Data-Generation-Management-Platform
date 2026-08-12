"""Discover manual flow name for node p0 / ListFiles."""

from __future__ import annotations

import os
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
    project_id = 1381309
    env = os.getenv("DATAWORKS_PROJECT_ENV", "PROD")
    node_id = int(os.environ["DATAWORKS_NODE_ID"])

    print("--- GetNode ---")
    nresp = c.get_node(m.GetNodeRequest(node_id=node_id, project_env=env))
    data = nresp.body.data
    for attr in sorted(dir(data)):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(data, attr)
        except Exception:
            continue
        if callable(val):
            continue
        if val is None or val == "" or val == []:
            continue
        print(f"  {attr}={val!r}")

    print("--- ListFiles (keyword / page) ---")
    try:
        fresp = c.list_files(
            m.ListFilesRequest(
                project_id=project_id,
                page_number=1,
                page_size=50,
                keyword="",
            )
        )
        files = fresp.body.data.files if fresp.body and fresp.body.data else []
        print("files=", len(files or []))
        for f in files or []:
            print(
                " ",
                getattr(f, "file_id", None),
                getattr(f, "file_name", None),
                getattr(f, "file_type", None),
                getattr(f, "use_type", None),
                getattr(f, "content_type", None),
                getattr(f, "node_id", None),
            )
    except Exception as exc:
        print("ListFiles failed:", exc)

    print("--- ListFolders ---")
    try:
        fol = c.list_folders(
            m.ListFoldersRequest(project_id=project_id, parent_folder_path="/", page_number=1, page_size=50)
        )
        folders = fol.body.data.folders if fol.body and fol.body.data else []
        for fo in folders or []:
            print(" ", getattr(fo, "folder_path", None), getattr(fo, "folder_id", None))
    except Exception as exc:
        print("ListFolders failed:", exc)

    # CreateManualDagRequest fields
    print("--- CreateManualDagRequest fields ---")
    req = m.CreateManualDagRequest()
    print([a for a in dir(req) if not a.startswith("_") and not callable(getattr(req, a, None))])


if __name__ == "__main__":
    main()
