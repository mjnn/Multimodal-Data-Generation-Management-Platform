"""源湖数据单元：多文件成组，约束多槽开跑只能选自同一单元。"""

from __future__ import annotations

from typing import Any

from hmi.platform.file_kinds import normalize_source_kind


class SourceUnitError(ValueError):
    """Run bind must lock to one lake unit when filling multiple slots."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

    def http_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


def recipe_slots(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (recipe.get("slots") or []) if isinstance(s, dict)]


def recipe_uses_source_units(recipe: dict[str, Any]) -> bool:
    """Multi-input recipes get unit UX (oms_cabin optional slots, audio_defect required pair)."""
    return len(recipe_slots(recipe)) >= 2


def required_slots(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in recipe_slots(recipe) if s.get("required")]


def filled_assignment_count(assignments: list[dict[str, Any]] | None) -> int:
    n = 0
    for asg in assignments or []:
        if not isinstance(asg, dict):
            continue
        if any(str(s).strip() for s in (asg.get("source_ids") or [])):
            n += 1
    return n


def assignments_need_unit(
    recipe: dict[str, Any],
    assignments: list[dict[str, Any]] | None = None,
) -> bool:
    """unit_id required when ≥2 required slots, or this run fills ≥2 slots."""
    if not recipe_uses_source_units(recipe):
        return False
    if len(required_slots(recipe)) >= 2:
        return True
    return filled_assignment_count(assignments) >= 2


def _slot_allowed_kinds(slot: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for kind in slot.get("kinds") or []:
        nk = normalize_source_kind(str(kind)) or str(kind).strip().lower()
        if nk:
            out.add(nk)
    return out


def _norm_kind(raw: str) -> str:
    return normalize_source_kind(str(raw or "")) or str(raw or "").strip().lower()


def _cover_slots(
    member_kinds: list[str],
    slots: list[dict[str, Any]],
    *,
    per_slot_min: int | None = None,
) -> int:
    """Greedy: how many slots can take at least min matching unused members."""
    pool = [_norm_kind(k) for k in member_kinds if _norm_kind(k)]
    covered = 0
    for slot in slots:
        allowed = _slot_allowed_kinds(slot)
        need = int(per_slot_min) if per_slot_min is not None else int(slot.get("cardinality_min") or 1)
        need = max(1, need)
        got = 0
        for _ in range(need):
            idx = next((i for i, k in enumerate(pool) if k in allowed), None)
            if idx is None:
                break
            pool.pop(idx)
            got += 1
        if got >= need:
            covered += 1
    return covered


def unit_eligible_for_recipe(recipe: dict[str, Any], member_kinds: list[str]) -> bool:
    """Candidate units: cover all required slots, or ≥2 optional slots on multi-input types."""
    if not recipe_uses_source_units(recipe):
        return False
    req = required_slots(recipe)
    slots = recipe_slots(recipe)
    if len(req) >= 2:
        return _cover_slots(member_kinds, req) >= len(req)
    return _cover_slots(member_kinds, slots, per_slot_min=1) >= 2


def assert_run_unit(
    recipe: dict[str, Any],
    *,
    unit_id: str | None,
    assignments: list[dict[str, Any]] | None,
    resolved_ids: list[str],
    members_by_unit,
) -> None:
    """members_by_unit(unit_id) -> set[str] of member source_ids, or empty if missing."""
    if not assignments_need_unit(recipe, assignments):
        return
    uid = str(unit_id or "").strip()
    if not uid:
        raise SourceUnitError("请先选择数据单元", code="SOURCE_UNIT_REQUIRED")
    members = set(members_by_unit(uid) or [])
    if not members:
        raise SourceUnitError("数据单元不存在或没有成员", code="SOURCE_UNIT_REQUIRED")
    for sid in resolved_ids:
        if sid not in members:
            raise SourceUnitError("所选文件必须属于同一数据单元", code="SOURCE_UNIT_MISMATCH")
