"""Derive dataset snapshots from a ready parent with balance / recipe lineage."""

from __future__ import annotations

from typing import Any

from hmi.dataset.assemble import normalize_filter
from hmi.dataset.lineage import build_lineage_for_parent
from hmi.dataset.taxonomy_crop import crop_taxonomy_version, resolve_crop_source_version_id
from hmi.dataset_db import create_snapshot, get_snapshot


def resolve_augmentation_mode(
    *,
    balance_by_label: str | None,
    aug_recipe_id: str | None,
) -> str:
    if aug_recipe_id:
        return "recipe_attached"
    if balance_by_label:
        return "oversample_only"
    return "none"


def build_derivation_json(
    *,
    parent_snapshot_id: str,
    filter_json: dict[str, Any],
    aug_recipe_id: str | None = None,
    aug_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "parent_snapshot_id": parent_snapshot_id,
    }
    for key in (
        "balance_by_label",
        "min_per_class",
        "max_per_class",
        "oversample_policy",
        "oversample_max_multiplier",
        "export_preset",
        "label_filters",
    ):
        if filter_json.get(key) is not None:
            out[key] = filter_json[key]
    try:
        out.update(build_lineage_for_parent(parent_snapshot_id))
    except ValueError:
        pass
    if aug_recipe_id:
        out["aug_recipe_id"] = aug_recipe_id
    if aug_recipe:
        out["aug_recipe"] = {
            "recipe_id": aug_recipe["id"],
            "recipe_code": aug_recipe["recipe_code"],
            "version": aug_recipe["version"],
        }
    return out


def derive_snapshot_from_parent(
    parent_id: str,
    *,
    name: str,
    description: str | None = None,
    filter_overrides: dict[str, Any] | None = None,
    taxonomy_crop_label_ids: list[str] | None = None,
    aug_recipe_id: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    parent = get_snapshot(parent_id.strip())
    if parent is None:
        raise ValueError(f"parent snapshot not found: {parent_id}")
    if parent["status"] != "ready":
        raise ValueError(f"parent snapshot must be ready (current: {parent['status']})")

    parent_filter = dict(parent.get("filter_json") or {})
    filt = dict(parent_filter)
    if filter_overrides:
        filt.update(filter_overrides)
    filt = normalize_filter(filt)

    target_spec_json: dict[str, Any] | None = None
    taxonomy_crop_meta: dict[str, Any] | None = None
    if taxonomy_crop_label_ids:
        selected = [str(lid).strip() for lid in taxonomy_crop_label_ids if str(lid).strip()]
        if not selected:
            raise ValueError("taxonomy_crop_label_ids must not be empty when provided")
        source_version_id = resolve_crop_source_version_id(parent)
        crop_result = crop_taxonomy_version(
            source_version_id,
            selected,
            created_by=created_by,
        )
        cropped = crop_result["version"]
        export_label_ids = crop_result["export_label_ids"]
        filt["export_taxonomy_version_id"] = crop_result["cropped_version_id"]
        filt["export_label_ids"] = export_label_ids
        taxonomy_crop_meta = {
            "source_version_id": crop_result["source_version_id"],
            "cropped_version_id": crop_result["cropped_version_id"],
            "selected_label_ids": crop_result["selected_label_ids"],
            "export_label_ids": export_label_ids,
            "cropped_version_code": cropped.get("version_code"),
        }
        target_spec_json = {
            "y": ["clip_label_review.labels_json"],
            "y_label_ids": export_label_ids,
            "export_taxonomy_version_id": crop_result["cropped_version_id"],
        }

    aug_recipe: dict[str, Any] | None = None
    if aug_recipe_id:
        from hmi.dataset.aug_recipe_db import get_published_recipe

        aug_recipe = get_published_recipe(aug_recipe_id)

    augmentation_mode = resolve_augmentation_mode(
        balance_by_label=filt.get("balance_by_label"),
        aug_recipe_id=aug_recipe_id,
    )
    derivation_json = build_derivation_json(
        parent_snapshot_id=parent_id,
        filter_json=filt,
        aug_recipe_id=aug_recipe_id,
        aug_recipe=aug_recipe,
    )
    if taxonomy_crop_meta:
        derivation_json["taxonomy_crop"] = taxonomy_crop_meta
    export_preset = filt.get("export_preset") or parent.get("export_preset") or "minimal"

    return create_snapshot(
        name.strip(),
        description=description,
        filter_json=filt,
        target_spec_json=target_spec_json,
        created_by=created_by,
        export_preset=str(export_preset),
        parent_snapshot_id=parent_id,
        derivation_json=derivation_json,
        augmentation_mode=augmentation_mode,
        aug_recipe_id=aug_recipe_id,
    )
