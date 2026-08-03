"""Dataset snapshot derivation lineage (parent chain + children)."""

from __future__ import annotations

from typing import Any

from hmi.dataset_db import get_snapshot

MAX_LINEAGE_DEPTH = 64


def _snapshot_ref(snap: dict[str, Any]) -> dict[str, str]:
    return {"id": str(snap["id"]), "name": str(snap.get("name") or snap["id"])}


def resolve_ancestor_chain(snapshot_id: str) -> list[dict[str, str]]:
    """Root → immediate parent (excludes snapshot_id itself)."""
    chain: list[dict[str, str]] = []
    snap = get_snapshot(snapshot_id.strip())
    if snap is None:
        return []
    walk_id = snap.get("parent_snapshot_id")
    seen: set[str] = set()
    while walk_id:
        pid = str(walk_id)
        if pid in seen:
            break
        seen.add(pid)
        parent = get_snapshot(pid)
        if parent is None:
            break
        chain.insert(0, _snapshot_ref(parent))
        walk_id = parent.get("parent_snapshot_id")
        if len(chain) >= MAX_LINEAGE_DEPTH:
            break
    return chain


def resolve_root_snapshot_id(snapshot_id: str) -> str:
    ancestors = resolve_ancestor_chain(snapshot_id)
    if ancestors:
        return str(ancestors[0]["id"])
    return snapshot_id.strip()


def resolve_derivation_depth(snapshot_id: str) -> int:
    return len(resolve_ancestor_chain(snapshot_id))


def list_direct_children(parent_snapshot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    from hmi.dataset_db import db_conn

    limit = max(1, min(limit, 200))
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, status, parent_snapshot_id, created_at
            FROM dataset_snapshot
            WHERE parent_snapshot_id = ? AND status != 'archived'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (parent_snapshot_id.strip(), limit),
        ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "name": str(r["name"]),
            "status": str(r["status"]),
            "parent_snapshot_id": r["parent_snapshot_id"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def build_lineage_for_parent(parent_id: str) -> dict[str, Any]:
    """Lineage fields stored on a newly derived snapshot's derivation_json."""
    parent = get_snapshot(parent_id.strip())
    if parent is None:
        raise ValueError(f"parent snapshot not found: {parent_id}")

    ancestor_chain = resolve_ancestor_chain(parent_id)
    if parent.get("parent_snapshot_id"):
        full_to_parent = ancestor_chain + [_snapshot_ref(parent)]
    else:
        full_to_parent = [_snapshot_ref(parent)]

    root_id = full_to_parent[0]["id"] if full_to_parent else parent_id
    return {
        "root_snapshot_id": root_id,
        "derivation_depth": len(full_to_parent),
        "lineage_chain": full_to_parent,
    }


def get_snapshot_lineage_context(snapshot_id: str) -> dict[str, Any]:
    snap = get_snapshot(snapshot_id.strip())
    if snap is None:
        raise ValueError(f"snapshot not found: {snapshot_id}")

    ancestor_chain = resolve_ancestor_chain(snapshot_id)
    root_id = ancestor_chain[0]["id"] if ancestor_chain else str(snap["id"])
    depth = len(ancestor_chain)
    children = list_direct_children(snapshot_id)

    return {
        "snapshot_id": str(snap["id"]),
        "root_snapshot_id": root_id,
        "derivation_depth": depth,
        "ancestor_chain": ancestor_chain,
        "derived_children": children,
        "is_root": not bool(snap.get("parent_snapshot_id")),
    }
