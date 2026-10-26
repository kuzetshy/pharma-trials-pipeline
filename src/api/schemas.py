"""Pydantic schemas (DTOs) for FastAPI endpoints."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic wrapper for paginated result sets."""

    total: int = Field(description="Total count of available matching records")
    limit: int = Field(description="Max items requested per page")
    offset: int = Field(description="Number of skipped items")
    items: list[T] = Field(description="List of items for current page")


class SponsorBenchmarkOut(BaseModel):
    """Competitive intelligence benchmark metrics for a trial sponsor."""

    model_config = ConfigDict(from_attributes=True)

    lead_sponsor_name: str | None = Field(default=None, description="Primary organization")
    lead_sponsor_class: str | None = Field(default=None, description="Category (INDUSTRY, NIH, etc.)")
    total_trials: int = Field(description="Total studies sponsored")
    active_trials: int = Field(description="Currently recruiting or ongoing studies")
    completed_trials: int = Field(description="Completed studies")
    terminated_trials: int = Field(description="Withdrawn or terminated studies")
    phase_1_trials: int = Field(description="Number of Phase 1 trials")
    phase_2_trials: int = Field(description="Number of Phase 2 trials")
    phase_3_trials: int = Field(description="Number of Phase 3 trials")
    phase_4_trials: int = Field(description="Number of Phase 4 trials")
    total_enrolled_patients: float | None = Field(default=None, description="Cumulative patient reach")
    avg_enrollment_per_trial: float | None = Field(default=None, description="Mean study size")
    results_reporting_rate_pct: float | None = Field(default=None, description="Percent of studies with posted results")


class DrugLandscapeOut(BaseModel):
    """Analytical metrics for drugs, biologics, and clinical interventions."""

    model_config = ConfigDict(from_attributes=True)

    intervention_name: str = Field(description="Standardized name of the drug/intervention")
    intervention_type: str | None = Field(default=None, description="Modality (DRUG, BIOLOGICAL, etc.)")
    total_trials_count: int = Field(description="Total trials utilizing this intervention")
    distinct_sponsors_count: int = Field(description="Number of distinct organizations researching this drug")
    active_trials_count: int = Field(description="Number of active clinical trials")
    completed_trials_count: int = Field(description="Number of completed clinical trials")
    phase_3_trials_count: int = Field(description="Count of late-stage pivotal Phase 3 trials")
    total_patient_reach: float | None = Field(default=None, description="Sum of patient enrollments across trials")


class TimelineBucketOut(BaseModel):
    """Historical clinical trial launch and duration metrics by year and study type."""

    model_config = ConfigDict(from_attributes=True)

    start_year: int | None = Field(default=None, description="Year trial initiated")
    study_type: str | None = Field(default=None, description="Interventional or Observational")
    trials_started_count: int = Field(description="Total trials launched in this year bucket")
    completed_count: int = Field(description="Completed trials")
    terminated_count: int = Field(description="Terminated or suspended trials")
    total_planned_enrollment: float | None = Field(default=None, description="Aggregate planned patients")
    avg_trial_duration_days: float | None = Field(default=None, description="Mean duration from start to completion")


class TrialInterventionOut(BaseModel):
    """Intervention entity associated with a trial."""

    intervention_type: str | None = None
    intervention_name: str
    description: str | None = None


class TrialSummaryOut(BaseModel):
    """Compact summary of a clinical trial for list views."""

    model_config = ConfigDict(from_attributes=True)

    nct_id: str
    brief_title: str
    overall_status: str
    phase: str | None = None
    lead_sponsor_name: str | None = None
    start_date: str | None = None
    enrollment_count: int | None = None


class TrialDetailOut(BaseModel):
    """Comprehensive study details from Silver layer with joined conditions and interventions."""

    model_config = ConfigDict(from_attributes=True)

    nct_id: str
    brief_title: str
    official_title: str | None = None
    overall_status: str
    study_type: str | None = None
    phase: str | None = None
    lead_sponsor_name: str | None = None
    lead_sponsor_class: str | None = None
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_date: str | None = None
    enrollment_count: int | None = None
    sex: str | None = None
    min_age: str | None = None
    max_age: str | None = None
    has_results: bool = False
    brief_summary: str | None = None
    processed_at_utc: str
    conditions: list[str] = Field(default_factory=list, description="Medical conditions addressed")
    interventions: list[TrialInterventionOut] = Field(
        default_factory=list, description="Drugs and interventions tested"
    )


class HealthCheckOut(BaseModel):
    """Health check diagnostic response."""

    status: str
    version: str
    marts_available: dict[str, bool]
    bronze_files_count: int
    silver_trials_count: int


class QualityGateStatusOut(BaseModel):
    """Current Data Quality status response."""

    status: str
    silver_gate: dict[str, Any]
    gold_gate: dict[str, Any]
