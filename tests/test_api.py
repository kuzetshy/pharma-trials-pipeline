"""Unit and integration tests for FastAPI REST service."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a test client instance with app lifespan context."""
    with TestClient(app) as test_client:
        yield test_client


def test_root_redirect_to_docs(client: TestClient) -> None:
    """Root URL should redirect to /docs."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] == "/docs"


def test_health_check_endpoint(client: TestClient) -> None:
    """Health check should return status and layer artifact diagnostics."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "marts_available" in data
    assert "bronze_files_count" in data
    assert "silver_trials_count" in data


def test_quality_gate_status_endpoint(client: TestClient) -> None:
    """Quality status endpoint should return full audit results."""
    response = client.get("/api/v1/quality/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("PASSED", "FAILED")
    assert "silver_gate" in data
    assert "gold_gate" in data
    assert data["silver_gate"]["total_checks"] > 0
    assert data["gold_gate"]["total_checks"] > 0


def test_get_sponsors_mart(client: TestClient) -> None:
    """Sponsors mart endpoint should return paginated benchmark records."""
    response = client.get("/api/v1/marts/sponsors?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert len(data["items"]) <= 5
    if data["items"]:
        first = data["items"][0]
        assert "lead_sponsor_name" in first
        assert "total_trials" in first
        assert "active_trials" in first


def test_get_drugs_mart(client: TestClient) -> None:
    """Drugs mart endpoint should return paginated drug landscape records."""
    response = client.get("/api/v1/marts/drugs?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert len(data["items"]) <= 5
    if data["items"]:
        first = data["items"][0]
        assert "intervention_name" in first
        assert "total_trials_count" in first


def test_get_timeline_mart(client: TestClient) -> None:
    """Timeline mart endpoint should return historical buckets."""
    response = client.get("/api/v1/marts/timeline")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "start_year" in data[0]
        assert "trials_started_count" in data[0]


def test_get_trials_list(client: TestClient) -> None:
    """Trials search endpoint should return paginated study summaries."""
    response = client.get("/api/v1/trials?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert len(data["items"]) <= 10
    if data["items"]:
        first = data["items"][0]
        assert "nct_id" in first
        assert "brief_title" in first


def test_get_trial_detail_success_and_not_found(client: TestClient) -> None:
    """Trial detail endpoint should return full record or 404 for unknown ID."""
    # First get a valid NCT ID from trials list
    list_resp = client.get("/api/v1/trials?limit=1")
    trials = list_resp.json().get("items", [])

    if trials:
        nct_id = trials[0]["nct_id"]
        detail_resp = client.get(f"/api/v1/trials/{nct_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["nct_id"] == nct_id
        assert "conditions" in detail
        assert "interventions" in detail
        assert isinstance(detail["conditions"], list)
        assert isinstance(detail["interventions"], list)

    # 404 test
    missing_resp = client.get("/api/v1/trials/NCT99999999")
    assert missing_resp.status_code == 404
    assert "not found" in missing_resp.json()["detail"].lower()


def test_summarize_trial_endpoint_success_and_not_found(client: TestClient) -> None:
    """GenAI summarize endpoint should return structured protocol summary or 404."""
    # Retrieve an existing trial ID
    list_resp = client.get("/api/v1/trials?limit=1")
    trials = list_resp.json().get("items", [])

    if trials:
        nct_id = trials[0]["nct_id"]
        resp = client.post(f"/api/v1/trials/{nct_id}/summarize")
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["nct_id"] == nct_id
        assert "mechanism_of_action" in summary
        assert "target_population" in summary
        assert isinstance(summary["primary_endpoints"], list)
        assert isinstance(summary["key_risks"], list)
        assert "model_name" in summary

    # Non-existent trial should return 404
    missing_resp = client.post("/api/v1/trials/NCT99999999/summarize")
    assert missing_resp.status_code == 404
    assert "not found in silver repository" in missing_resp.json()["detail"].lower()


def test_summarize_trial_endpoint_service_error(client: TestClient) -> None:
    """GenAI summarize endpoint should return 502 if upstream summarizer fails."""
    from unittest.mock import MagicMock

    from src.api.routers.trials import get_summarizer_service
    from src.genai.summarizer import ClinicalProtocolSummarizer, GenAIServiceError

    list_resp = client.get("/api/v1/trials?limit=1")
    trials = list_resp.json().get("items", [])

    if trials:
        nct_id = trials[0]["nct_id"]

        mock_summarizer = MagicMock(spec=ClinicalProtocolSummarizer)
        mock_summarizer.summarize_trial.side_effect = GenAIServiceError("Simulated LLM API quota exhaustion")

        app.dependency_overrides[get_summarizer_service] = lambda: mock_summarizer
        try:
            resp = client.post(f"/api/v1/trials/{nct_id}/summarize")
            assert resp.status_code == 502
            assert "GenAI summarization service failed" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_summarizer_service, None)

