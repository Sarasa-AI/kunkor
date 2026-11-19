"""Trusted catalog adapter. An empty owner-managed catalog is a valid state.

Educational resources come exclusively from the Content Service. No bundled
educational data or synthetic fallbacks are used at application runtime.
"""

from typing import Any

from app.engines.validator import ResourceMeta
from app.modules.content.service import ContentService

# Kept as empty compatibility exports; production never ships fixture content.
RESOURCE_METADATA_DETAILS: list[dict[str, Any]] = []
DEFAULT_RESOURCE_CATALOG: dict[str, ResourceMeta] = {}


def get_resources_for_stage(
    stage_code: str,
    conn: Any = None,
    *,
    grade: str | None = None,
    track: str | None = None,
) -> list[dict[str, Any]]:
    """Read approved, published, licensed units without filling missing fields."""
    if conn is None:
        return []
    numeric_grade = int(grade[1:]) if grade and grade.startswith("G") else None
    rows = ContentService().get_agent_resources(
        conn, stage_code=stage_code, grade=numeric_grade, track=track
    )
    result = []
    for row in rows:
        for target_grade in [numeric_grade] if numeric_grade else row.get("grades", []):
            if target_grade not in (10, 11, 12):
                continue
            item = dict(row)
            item["status"] = "Published" if row.get("status") == "published" else "Draft"
            item["grade"] = f"G{target_grade:02d}"
            item["stage_code"] = stage_code
            item["prerequisites"] = [str(value) for value in row.get("prerequisites", [])]
            result.append(item)
    return result


def catalog_from_resources(resources: list[dict[str, Any]]) -> dict[str, ResourceMeta]:
    """Build the validator snapshot from the same trusted retrieval as the proposer."""
    return {
        row["resource_id"]: ResourceMeta(
            resource_id=row["resource_id"],
            stage_code=row["stage_code"],
            grade=row.get("grade"),
            subject=row.get("subject"),
            duration_minutes=row.get("duration_minutes"),
            prerequisites=tuple(row.get("prerequisites", [])),
            status=row.get("status", "Draft"),
            license_active=row.get("license_active", False),
            license_expired=row.get("license_expired", False),
        )
        for row in resources
        if type(row.get("duration_minutes")) is int
        and 0 < row["duration_minutes"] <= 600
        and isinstance(row.get("subject"), str)
        and bool(row["subject"])
        and isinstance(row.get("grade"), str)
        and bool(row["grade"])
    }


def get_default_catalog(
    conn: Any = None,
) -> dict[str, ResourceMeta]:
    """Read the current trusted catalog; no content means an empty mapping."""
    if conn is None:
        return {}
    resources = [
        *get_resources_for_stage("upper_secondary", conn),
        *get_resources_for_stage("konkur", conn, grade="G12"),
    ]
    return catalog_from_resources(resources)


def is_plan_trusted(plan: dict[str, Any], resources: list[dict[str, Any]]) -> bool:
    """A saved plan must still match the currently reviewed scheduling metadata."""
    trusted = catalog_from_resources(resources)
    items = plan.get("items", [])
    if not items:
        return False
    for item in items:
        meta = trusted.get(item.get("resource_version_id"))
        if (
            meta is None
            or meta.status != "Published"
            or not meta.license_active
            or meta.license_expired
            or item.get("duration_minutes") != meta.duration_minutes
            or item.get("stage_code") != meta.stage_code
            or set(item.get("prerequisites", [])) != set(meta.prerequisites)
        ):
            return False
    return True
