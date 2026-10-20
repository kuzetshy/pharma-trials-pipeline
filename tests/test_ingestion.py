"""Unit tests for Bronze layer ingestion module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.ingestion.fetch_trials import (
    ClinicalTrialsAPIError,
    ClinicalTrialsClient,
    run_ingestion,
    save_bronze_batch,
)
from src.utils.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Fixture providing isolated temporary settings for testing."""
    return Settings(
        api_base_url="https://clinicaltrials.gov/api/v2/studies",
        search_condition="Breast Cancer",
        page_size=10,
        max_batches=2,
        request_timeout_seconds=5.0,
        max_retries=2,
        backoff_factor=0.01,
        rate_limit_delay=0.0,
        data_dir=tmp_path / "data",
        bronze_dir=tmp_path / "data" / "bronze",
        silver_dir=tmp_path / "data" / "silver",
        gold_dir=tmp_path / "data" / "gold",
    )


def test_save_bronze_batch(tmp_path: Path) -> None:
    """Verify batch JSON file structure and naming convention."""
    output_dir = tmp_path / "bronze"
    mock_studies = [
        {"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}},
        {"protocolSection": {"identificationModule": {"nctId": "NCT00000002"}}},
    ]
    metadata = {"batch_index": 1, "condition": "Breast Cancer"}

    saved_path = save_bronze_batch(
        studies=mock_studies,
        batch_index=1,
        output_dir=output_dir,
        metadata=metadata,
    )

    assert saved_path.exists()
    assert saved_path.name.startswith("trials_")
    assert saved_path.name.endswith("_batch_01.json")

    with open(saved_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["metadata"]["condition"] == "Breast Cancer"
    assert len(data["studies"]) == 2
    assert data["studies"][0]["protocolSection"]["identificationModule"]["nctId"] == "NCT00000001"


def test_client_fetch_page_success(test_settings: Settings) -> None:
    """Verify successful API call and response parsing."""
    client = ClinicalTrialsClient(config=test_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT123"}}}],
        "nextPageToken": "token_page_2",
    }

    with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
        result = client.fetch_page(condition="Breast Cancer", page_size=10, page_token=None)

        mock_get.assert_called_once_with(
            test_settings.api_base_url,
            params={"query.cond": "Breast Cancer", "pageSize": 10},
        )
        assert len(result["studies"]) == 1
        assert result["nextPageToken"] == "token_page_2"

    client.close()


def test_client_fetch_page_with_page_token(test_settings: Settings) -> None:
    """Verify pagination token is properly passed in query params."""
    client = ClinicalTrialsClient(config=test_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"studies": [], "nextPageToken": None}

    with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
        client.fetch_page(condition="Breast Cancer", page_size=10, page_token="abc123token")

        mock_get.assert_called_once_with(
            test_settings.api_base_url,
            params={"query.cond": "Breast Cancer", "pageSize": 10, "pageToken": "abc123token"},
        )

    client.close()


def test_client_retry_on_429(test_settings: Settings) -> None:
    """Verify client retries on HTTP 429 and succeeds when subsequent request passes."""
    client = ClinicalTrialsClient(config=test_settings)

    mock_resp_rate_limit = MagicMock()
    mock_resp_rate_limit.status_code = 429
    mock_resp_rate_limit.headers = {"Retry-After": "0"}

    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.json.return_value = {"studies": [{"id": 1}]}

    with patch.object(
        client.client, "get", side_effect=[mock_resp_rate_limit, mock_resp_ok]
    ) as mock_get:
        result = client.fetch_page(condition="Breast Cancer", page_size=10)
        assert mock_get.call_count == 2
        assert len(result["studies"]) == 1

    client.close()


def test_client_raises_after_retries_exhausted(test_settings: Settings) -> None:
    """Verify ClinicalTrialsAPIError is raised when max retries are exhausted."""
    client = ClinicalTrialsClient(config=test_settings)

    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_resp_503.headers = {}
    mock_resp_503.text = "Service Unavailable"

    with patch.object(client.client, "get", return_value=mock_resp_503):
        with pytest.raises(ClinicalTrialsAPIError):
            client.fetch_page(condition="Breast Cancer", page_size=10)

    client.close()


def test_run_ingestion_multi_batch(test_settings: Settings) -> None:
    """Verify run_ingestion creates multiple batches up to max_batches."""
    batch_1 = {
        "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT1"}}}],
        "nextPageToken": "token2",
    }
    batch_2 = {
        "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT2"}}}],
        "nextPageToken": "token3",
    }

    mock_resp_1 = MagicMock(status_code=200)
    mock_resp_1.json.return_value = batch_1

    mock_resp_2 = MagicMock(status_code=200)
    mock_resp_2.json.return_value = batch_2

    with patch("httpx.Client.get", side_effect=[mock_resp_1, mock_resp_2]):
        files = run_ingestion(
            condition="Breast Cancer",
            page_size=1,
            max_batches=2,
            bronze_dir=test_settings.bronze_dir,
            config=test_settings,
        )

        assert len(files) == 2
        assert all(f.exists() for f in files)
