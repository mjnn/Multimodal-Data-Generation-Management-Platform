"""DataWorks 节点用 alibabacloud_oss_v2 薄封装（粘贴节点时可复制本文件函数到节点内）。"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any, Iterator

import alibabacloud_oss_v2 as oss


def normalize_oss_region(region: str) -> str:
    return region.replace("_", "-")


def make_oss_client(
    *,
    access_key_id: str,
    access_key_secret: str,
    region: str,
    endpoint: str | None = None,
) -> oss.Client:
    cfg = oss.config.load_default()
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
        access_key_id,
        access_key_secret,
    )
    cfg.region = normalize_oss_region(region)
    if endpoint:
        cfg.endpoint = endpoint
    return oss.Client(cfg)


def iter_object_keys(
    client: oss.Client,
    *,
    bucket: str,
    prefix: str = "",
    suffix: str = "",
    max_count: int | None = None,
) -> Iterator[str]:
    paginator = client.list_objects_v2_paginator()
    count = 0
    for page in paginator.iter_page(
        oss.ListObjectsV2Request(bucket=bucket, prefix=prefix or None)
    ):
        for obj in page.contents or []:
            key = obj.key
            if suffix and not key.endswith(suffix):
                continue
            yield key
            count += 1
            if max_count is not None and count >= max_count:
                return


def stream_object_sha256(client: oss.Client, *, bucket: str, object_key: str) -> str:
    """与 clip_id._hash_file 一致：先 hash 文件名，再 hash 内容。"""
    hasher = hashlib.sha256()
    hasher.update(PurePosixPath(object_key).name.encode("utf-8"))
    result = client.get_object(oss.GetObjectRequest(bucket=bucket, key=object_key))
    with result.body as stream:
        for chunk in stream.iter_bytes():
            hasher.update(chunk)
    return hasher.hexdigest()


def get_object_text(client: oss.Client, *, bucket: str, object_key: str) -> str:
    result = client.get_object(oss.GetObjectRequest(bucket=bucket, key=object_key))
    with result.body as stream:
        return stream.read().decode("utf-8")
