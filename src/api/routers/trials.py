"""Silver Layer Clinical Trials search and exploration endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.schemas import PaginatedResponse, TrialDetailOut, TrialSummaryOut
from src.api.service import DataService
from src.genai.schemas import ClinicalSummaryOut
from src.genai.summarizer import ClinicalProtocolSummarizer, GenAIServiceError, get_summarizer
from src.utils.config import settings

router = APIRouter(prefix="/api/v1/trials", tags=["Clinical Trials (Silver)"])


def get_data_service() -> DataService:
    return DataService(config=settings)


def get_summarizer_service() -> ClinicalProtocolSummarizer:
    return get_summarizer(settings)


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


@router.post(
    "/{nct_id}/summarize",
    response_model=ClinicalSummaryOut,
    summary="Generate Structured Clinical Protocol Summary via GenAI",
    status_code=status.HTTP_200_OK,
)
def summarize_trial_protocol(
    nct_id: str,
    data_service: DataService = Depends(get_data_service),
    summarizer: ClinicalProtocolSummarizer = Depends(get_summarizer_service),
) -> ClinicalSummaryOut:
    """Extract and synthesize mechanism of action, target population, and endpoints using GenAI."""
    trial = data_service.get_trial_detail(nct_id)
    if not trial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clinical trial '{nct_id}' not found in Silver repository to summarize",
        )
    try:
        return summarizer.summarize_trial(trial)
    except GenAIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GenAI summarization service failed: {exc}",
        ) from exc

