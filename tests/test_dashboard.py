"""Unit and integration tests for PharmaInsight Visual Analytics Dashboard layer."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.dashboard.api_client import ApiClientError, PharmaApiClient
from src.dashboard.visuals import (
    plot_drug_landscape,
    plot_phase_distribution,
    plot_timeline_dynamics,
    plot_top_sponsors_breakdown,
)


@pytest.fixture
def api_client() -> PharmaApiClient:
    return PharmaApiClient(base_url="http://testserver:8000")


# --- API CLIENT TESTS ---


def test_api_client_is_alive_success(api_client: PharmaApiClient) -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        assert api_client.is_alive() is True


def test_api_client_is_alive_failure(api_client: PharmaApiClient) -> None:
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("Failed")):
        assert api_client.is_alive() is False


def test_api_client_get_health(api_client: PharmaApiClient) -> None:
    expected_data = {"status": "healthy", "version": "1.0.0"}
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = expected_data

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        health = api_client.get_health()
        assert health == expected_data


def test_api_client_get_quality_status(api_client: PharmaApiClient) -> None:
    expected_data = {"status": "PASSED", "silver_gate": {"passed": True}}
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = expected_data

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        status = api_client.get_quality_status()
        assert status["status"] == "PASSED"


def test_api_client_get_sponsors_params(api_client: PharmaApiClient) -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"total": 1, "items": [{"lead_sponsor_name": "Roche"}]}

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = api_client.get_sponsors(limit=10, offset=5, min_trials=2, sponsor_class="INDUSTRY")
        assert len(res["items"]) == 1
        mock_get.assert_called_once_with(
            "/api/v1/marts/sponsors",
            params={"limit": 10, "offset": 5, "min_trials": 2, "sponsor_class": "INDUSTRY"},
        )


def test_api_client_get_drugs_params(api_client: PharmaApiClient) -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"total": 1, "items": [{"intervention_name": "Trastuzumab"}]}

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = api_client.get_drugs(limit=15, offset=0, intervention_type="BIOLOGICAL")
        assert len(res["items"]) == 1
        mock_get.assert_called_once_with(
            "/api/v1/marts/drugs",
            params={"limit": 15, "offset": 0, "intervention_type": "BIOLOGICAL"},
        )


def test_api_client_get_timeline_params(api_client: PharmaApiClient) -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"start_year": 2024, "trials_started_count": 10}]

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = api_client.get_timeline(start_year=2020, study_type="INTERVENTIONAL")
        assert len(res) == 1
        mock_get.assert_called_once_with(
            "/api/v1/marts/timeline",
            params={"start_year": 2020, "study_type": "INTERVENTIONAL"},
        )


def test_api_client_get_trials_and_detail(api_client: PharmaApiClient) -> None:
    mock_resp_list = MagicMock(spec=httpx.Response)
    mock_resp_list.status_code = 200
    mock_resp_list.json.return_value = {"total": 1, "items": [{"nct_id": "NCT00567554"}]}

    mock_resp_detail = MagicMock(spec=httpx.Response)
    mock_resp_detail.status_code = 200
    mock_resp_detail.json.return_value = {"nct_id": "NCT00567554", "brief_title": "Test Trial"}

    mock_resp_404 = MagicMock(spec=httpx.Response)
    mock_resp_404.status_code = 404

    with patch.object(httpx.Client, "get") as mock_get:
        mock_get.return_value = mock_resp_list
        trials = api_client.get_trials(search="pembro", phase="PHASE3", status="RECRUITING")
        assert trials["total"] == 1

        mock_get.return_value = mock_resp_detail
        detail = api_client.get_trial_detail("NCT00567554")
        assert detail is not None
        assert detail["nct_id"] == "NCT00567554"

        mock_get.return_value = mock_resp_404
        detail_missing = api_client.get_trial_detail("NCT99999999")
        assert detail_missing is None


def test_api_client_summarize_trial_success(api_client: PharmaApiClient) -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "nct_id": "NCT00567554",
        "mechanism_of_action": "Monoclonal antibody",
        "primary_endpoints": ["PFS"],
    }

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        res = api_client.summarize_trial("NCT00567554")
        assert res["nct_id"] == "NCT00567554"
        assert res["mechanism_of_action"] == "Monoclonal antibody"


def test_api_client_summarize_trial_error(api_client: PharmaApiClient) -> None:
    mock_req = MagicMock(spec=httpx.Request)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 404
    mock_resp.text = "Trial not found"

    err = httpx.HTTPStatusError("404 error", request=mock_req, response=mock_resp)

    with patch.object(httpx.Client, "post", side_effect=err):
        with pytest.raises(ApiClientError, match="not found in database"):
            api_client.summarize_trial("NCT99999999")


# --- VISUAL CHART TESTS ---


def test_plot_top_sponsors_breakdown() -> None:
    empty_fig = plot_top_sponsors_breakdown([])
    assert empty_fig is not None

    sample_sponsors: list[dict[str, Any]] = [
        {
            "lead_sponsor_name": "AstraZeneca",
            "lead_sponsor_class": "INDUSTRY",
            "total_trials": 25,
            "active_trials": 10,
            "phase_3_trials": 5,
            "total_enrolled_patients": 5000,
        },
        {
            "lead_sponsor_name": "Pfizer",
            "lead_sponsor_class": "INDUSTRY",
            "total_trials": 35,
            "active_trials": 12,
            "phase_3_trials": 8,
            "total_enrolled_patients": 8000,
        },
    ]
    fig = plot_top_sponsors_breakdown(sample_sponsors, top_n=10)
    assert fig is not None
    assert len(fig.data) == 3  # 3 traces: total, active, phase 3


def test_plot_drug_landscape() -> None:
    empty_fig = plot_drug_landscape([])
    assert empty_fig is not None

    sample_drugs: list[dict[str, Any]] = [
        {
            "intervention_name": "Trastuzumab",
            "intervention_type": "BIOLOGICAL",
            "total_trials_count": 20,
            "total_patient_reach": 12000,
        },
        {
            "intervention_name": "Paclitaxel",
            "intervention_type": "DRUG",
            "total_trials_count": 30,
            "total_patient_reach": 15000,
        },
    ]
    fig = plot_drug_landscape(sample_drugs, top_n=10)
    assert fig is not None
    assert len(fig.data) == 1


def test_plot_timeline_dynamics() -> None:
    empty_fig = plot_timeline_dynamics([])
    assert empty_fig is not None

    sample_timeline: list[dict[str, Any]] = [
        {
            "start_year": 2021,
            "trials_started_count": 15,
            "completed_count": 8,
            "avg_trial_duration_days": 420.5,
        },
        {
            "start_year": 2022,
            "trials_started_count": 22,
            "completed_count": 12,
            "avg_trial_duration_days": 395.0,
        },
    ]
    fig = plot_timeline_dynamics(sample_timeline)
    assert fig is not None
    assert len(fig.data) == 3  # 2 bar traces + 1 line trace


def test_plot_phase_distribution() -> None:
    empty_fig = plot_phase_distribution([])
    assert empty_fig is not None

    sample_trials: list[dict[str, Any]] = [
        {"phase": "PHASE1"},
        {"phase": "PHASE2"},
        {"phase": "PHASE2"},
        {"phase": "PHASE3"},
    ]
    fig = plot_phase_distribution(sample_trials)
    assert fig is not None
    assert len(fig.data) == 1
