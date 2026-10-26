"""System diagnostics, health checks, and Data Quality gate endpoints."""

from fastapi import APIRouter, Depends

from src.api.schemas import HealthCheckOut, QualityGateStatusOut
from src.api.service import DataService
from src.utils.config import settings
from src.utils.quality import validate_gold_layer, validate_silver_layer

router = APIRouter(tags=["System & Quality"])


def get_data_service() -> DataService:
    return DataService(config=settings)


@router.get("/health", response_model=HealthCheckOut, summary="Service and Data Lake Health")
def get_health(service: DataService = Depends(get_data_service)) -> HealthCheckOut:
    """Check connectivity and existence of Bronze, Silver, and Gold Parquet layers."""
    health_info = service.get_system_health()
    return HealthCheckOut(**health_info)


@router.get(
    "/api/v1/quality/status",
    response_model=QualityGateStatusOut,
    summary="Data Quality Gate Audit",
)
def get_quality_status() -> QualityGateStatusOut:
    """Execute live Data Quality assertions against Silver & Gold Parquet tables."""
    silver_report = validate_silver_layer(silver_dir=settings.silver_dir, raise_on_error=False)
    gold_report = validate_gold_layer(gold_dir=settings.gold_dir, raise_on_error=False)

    overall_passed = silver_report.is_success and gold_report.is_success

    return QualityGateStatusOut(
        status="PASSED" if overall_passed else "FAILED",
        silver_gate={
            "suite": silver_report.suite_name,
            "passed": silver_report.is_success,
            "total_checks": silver_report.total_checks,
            "passed_checks": silver_report.passed_checks,
            "failed_checks": silver_report.failed_checks,
            "results": [
                {
                    "check": r.check_name,
                    "target": r.target_artifact,
                    "passed": r.passed,
                    "details": r.details,
                }
                for r in silver_report.results
            ],
        },
        gold_gate={
            "suite": gold_report.suite_name,
            "passed": gold_report.is_success,
            "total_checks": gold_report.total_checks,
            "passed_checks": gold_report.passed_checks,
            "failed_checks": gold_report.failed_checks,
            "results": [
                {
                    "check": r.check_name,
                    "target": r.target_artifact,
                    "passed": r.passed,
                    "details": r.details,
                }
                for r in gold_report.results
            ],
        },
    )
