"""Analytical Data Marts REST endpoints (Gold Layer)."""

from fastapi import APIRouter, Depends, Query

from src.api.schemas import (
    DrugLandscapeOut,
    PaginatedResponse,
    SponsorBenchmarkOut,
    TimelineBucketOut,
)
from src.api.service import DataService
from src.utils.config import settings

router = APIRouter(prefix="/api/v1/marts", tags=["Analytical Marts (Gold)"])


def get_data_service() -> DataService:
    return DataService(config=settings)


@router.get(
    "/sponsors",
    response_model=PaginatedResponse[SponsorBenchmarkOut],
    summary="Sponsor Benchmarks & Competitive Intelligence",
)
def get_sponsors(
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    min_trials: int = Query(default=1, ge=1, description="Filter sponsors with at least N trials"),
    sponsor_class: str | None = Query(default=None, description="INDUSTRY, OTHER, NIH, etc."),
    service: DataService = Depends(get_data_service),
) -> PaginatedResponse[SponsorBenchmarkOut]:
    """Retrieve benchmarked metrics for pharma and academic sponsors."""
    items, total = service.get_sponsor_benchmarks(
        limit=limit,
        offset=offset,
        min_trials=min_trials,
        sponsor_class=sponsor_class,
    )
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/drugs",
    response_model=PaginatedResponse[DrugLandscapeOut],
    summary="Drug and Intervention Landscape",
)
def get_drugs(
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    intervention_type: str | None = Query(default=None, description="DRUG, BIOLOGICAL, RADIATION, etc."),
    service: DataService = Depends(get_data_service),
) -> PaginatedResponse[DrugLandscapeOut]:
    """Retrieve adoption, sponsor counts, and patient reach by intervention/molecule."""
    items, total = service.get_drug_landscape(
        limit=limit,
        offset=offset,
        intervention_type=intervention_type,
    )
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/timeline",
    response_model=list[TimelineBucketOut],
    summary="Historical Trial Launches and Duration Dynamics",
)
def get_timeline(
    start_year: int | None = Query(default=None, ge=1970, le=2050, description="Minimum launch year"),
    study_type: str | None = Query(default=None, description="INTERVENTIONAL, OBSERVATIONAL"),
    service: DataService = Depends(get_data_service),
) -> list[TimelineBucketOut]:
    """Retrieve timeline distribution and average trial duration in days."""
    return service.get_timeline(start_year=start_year, study_type=study_type)
