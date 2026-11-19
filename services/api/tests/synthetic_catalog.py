"""Explicit automated-test-only fixtures; never imported by production modules."""

import json
from copy import deepcopy
from pathlib import Path

from app.engines.catalog import catalog_from_resources

SYNTHETIC_RESOURCES = json.loads(
    (Path(__file__).parent / "fixtures/planner_catalog.json").read_text()
)
for row in SYNTHETIC_RESOURCES:
    row["published_at"] = "2000-01-01T00:00:00+00:00"


def get_resources_for_stage(stage_code, conn=None, *, grade=None, track=None):
    return deepcopy(
        [
            row
            for row in SYNTHETIC_RESOURCES
            if row["stage_code"] == stage_code and (grade is None or row["grade"] == grade)
        ]
    )


def get_default_catalog(conn=None):
    return catalog_from_resources(deepcopy(SYNTHETIC_RESOURCES))
