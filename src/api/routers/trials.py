"""Silver Layer Clinical Trials search and exploration endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.schemas import PaginatedResponse, TrialDetailOut, TrialSummaryOut
from src.api.service import DataService
from src.utils.config import settings

router = APIRouter(prefix="/api/v1/trials", tags=["Clinical Trials (Silver)"])


def get_data_service() -> DataService:
    return DataService(config=settings)


@router.get(
    "",
    response_model=PaginatedResponse[TrialSummaryOut],
    summary="Search Cleaned Clinical Trials",
)
def get_trials(
    limit: int = Query(default=20, ge=1, le=100, description="Max trials to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    search: str | None = Query(default=None, description="Search term for title or NCT ID"),
    phase: str | None = Query(default=None, description="Trial phase (PHASE1, PHASE2, PHASE3, etc.)"),
    status: str | None = Query(default=None, description="Status (COMPLETED, RECRUITING, etc.)"),
    service: DataService = Depends(get_data_service),
) -> PaginatedResponse[TrialSummaryOut]:
    """Search and filter cleaned clinical studies from the Silver layer."""
    items, total = service.get_trials(
        limit=limit,
        offset=offset,
        search=search,
        phase=phase,
        status=status,
    )
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{nct_id}",
    response_model=TrialDetailOut,
    summary="Get Detailed Clinical Trial Protocol",
)
def get_trial_detail(
    nct_id: str,
    service: DataService = Depends(get_data_service),
) -> TrialDetailOut:
    """Retrieve full trial profile with associated conditions and interventions."""
    trial = service.get_trial_detail(nct_id)
    if not trial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clinical trial '{nct_id}' not found in Silver repository",
        )
    return TrialDetailOut(**trial)
