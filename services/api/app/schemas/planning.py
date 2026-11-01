"""Planning and Intake schemas for Kunkor Stage 0.5."""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StageCode = Literal[
    "primary_low",
    "primary_high",
    "lower_secondary",
    "upper_secondary",
    "konkur",
]

GradeCode = Literal[
    "G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09", "G10", "G11", "G12", "POSTK"
]

TrackCode = Literal["general", "mathematics", "experimental", "humanities"]

PlanStatus = Literal["draft", "active", "superseded"]

STAGE_CAPACITY_LIMITS: dict[StageCode, int] = {
    "primary_low": 30,
    "primary_high": 60,
    "lower_secondary": 180,
    "upper_secondary": 360,
    "konkur": 600,
}

STAGE_GRADE_MAP: dict[StageCode, set[GradeCode]] = {
    "primary_low": {"G01", "G02", "G03"},
    "primary_high": {"G04", "G05", "G06"},
    "lower_secondary": {"G07", "G08", "G09"},
    "upper_secondary": {"G10", "G11"},
    "konkur": {"G12", "POSTK"},
}


class IntakeSlots(BaseModel):
    """
    Intake slots contract.
    Strictly typed, forbids extra untrusted properties to prevent prompt injection payload leakage.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_code: StageCode
    grade: GradeCode
    track: TrackCode = "general"
    daily_study_capacity_minutes: int = Field(gt=0)
    weak_subjects: list[str] = Field(default_factory=list)
    target_exam: Optional[str] = None
    guardian_consent: Optional[bool] = None

    @field_validator("daily_study_capacity_minutes")
    @classmethod
    def validate_capacity_bounds(cls, v: int) -> int:
        if v > 600:
            raise ValueError(
                f"Daily study capacity {v} exceeds physiological ceiling (600 minutes)"
            )
        return v

    @model_validator(mode="after")
    def validate_grade_and_consent(self) -> "IntakeSlots":
        # Validate grade belongs to stage
        valid_grades = STAGE_GRADE_MAP.get(self.stage_code, set())
        if self.grade not in valid_grades:
            valid_list = sorted(valid_grades)
            raise ValueError(
                f"Grade '{self.grade}' invalid for stage '{self.stage_code}'. Valid: {valid_list}"
            )

        # Validate stage ceiling
        ceiling = STAGE_CAPACITY_LIMITS[self.stage_code]
        if self.daily_study_capacity_minutes > ceiling:
            cap = self.daily_study_capacity_minutes
            stg = self.stage_code
            raise ValueError(f"Daily capacity {cap}m exceeds {stg} ceiling ({ceiling}m)")

        # ADR-0003 / D-04: Age < 15 (primary_low, primary_high) requires guardian consent
        if self.stage_code in ("primary_low", "primary_high") and not self.guardian_consent:
            raise ValueError(f"Guardian consent is mandatory for stage '{self.stage_code}'")

        # Track restriction
        if self.stage_code not in ("upper_secondary", "konkur") and self.track != "general":
            raise ValueError(f"Specialized tracks not permitted for stage '{self.stage_code}'")

        return self


class StudyPlanItem(BaseModel):
    """Single study plan unit item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    resource_version_id: str
    stage_code: StageCode
    duration_minutes: int = Field(gt=0)
    prerequisites: list[str] = Field(default_factory=list)


class StudyPlan(BaseModel):
    """
    Revisioned study plan conforming to ADR-0004, ADR-0005, and ADR-0008.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: UUID = Field(default_factory=uuid4)
    student_id: UUID  # Non-nullable per ADR-0008
    revision_no: int = Field(ge=1, default=1)
    engine_version: str = Field(min_length=1, default="0.5.0")
    rule_set_version: str = Field(min_length=1, default="1.0.0")
    status: PlanStatus = "draft"
    items: list[StudyPlanItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("revision_no")
    @classmethod
    def validate_revision_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("revision_no must be >= 1")
        return v
