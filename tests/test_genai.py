"""Unit tests for GenAI schemas, providers, and protocol summarizer service."""

import json
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from src.genai.schemas import ClinicalSummaryOut
from src.genai.summarizer import (
    ClinicalProtocolSummarizer,
    GeminiLLMProvider,
    GenAIServiceError,
    MockLLMProvider,
    get_summarizer,
)
from src.utils.config import Settings


def test_clinical_summary_out_valid_creation():
    """Verify that ClinicalSummaryOut parses valid data and applies default values."""
    payload = {
        "nct_id": "NCT04280705",
        "study_title": "Adaptive COVID-19 Treatment Trial",
        "mechanism_of_action": "RdRp inhibitor blocking viral RNA synthesis",
        "target_population": "Adults with confirmed COVID-19 and low SpO2",
        "primary_endpoints": ["Time to recovery"],
        "key_risks": ["Elevated ALT", "Renal impairment"],
        "design_summary": "Phase 3 randomized trial",
        "model_name": "gemini-1.5-pro",
    }
    summary = ClinicalSummaryOut(**payload)

    assert summary.nct_id == "NCT04280705"
    assert summary.study_title == "Adaptive COVID-19 Treatment Trial"
    assert summary.mechanism_of_action == payload["mechanism_of_action"]
    assert summary.target_population == payload["target_population"]
    assert summary.primary_endpoints == ["Time to recovery"]
    assert summary.key_risks == ["Elevated ALT", "Renal impairment"]
    assert summary.design_summary == "Phase 3 randomized trial"
    assert summary.model_name == "gemini-1.5-pro"
    assert isinstance(summary.generated_at, datetime)
    assert summary.generated_at.tzinfo is not None


def test_clinical_summary_nct_id_normalization():
    """Verify that nct_id is cleaned (stripped, uppercased)."""
    summary = ClinicalSummaryOut(
        nct_id="  nct01234567  ",
        mechanism_of_action="Monoclonal antibody targeting PD-L1",
        target_population="Metastatic NSCLC",
    )
    assert summary.nct_id == "NCT01234567"
    assert summary.primary_endpoints == []
    assert summary.key_risks == []
    assert summary.model_name == "mock-clinical-v1"


@pytest.mark.parametrize("invalid_id", [
    "NCT123",          # Too short
    "NCT123456789",    # Too long
    "NCTABCDEFGH",     # Non-numeric
    "STUDY0001",       # Wrong prefix
    "",                # Empty
])
def test_clinical_summary_nct_id_invalid(invalid_id: str):
    """Verify that malformed NCT IDs are rejected by the validator."""
    with pytest.raises(ValidationError) as exc_info:
        ClinicalSummaryOut(
            nct_id=invalid_id,
            mechanism_of_action="Kinase inhibitor",
            target_population="CML patients",
        )
    assert "Invalid NCT ID format" in str(exc_info.value)


def test_clinical_summary_missing_required_fields():
    """Verify validation error when required fields are missing."""
    with pytest.raises(ValidationError) as exc_info:
        ClinicalSummaryOut(nct_id="NCT01234567")

    errors = exc_info.value.errors()
    missing_fields = {err["loc"][0] for err in errors if err["type"] == "missing"}
    assert "mechanism_of_action" in missing_fields
    assert "target_population" in missing_fields


def test_clinical_summary_json_schema_export():
    """Verify that model_json_schema() exports structured descriptions for LLM function calling."""
    schema = ClinicalSummaryOut.model_json_schema()

    assert "properties" in schema
    assert "mechanism_of_action" in schema["properties"]
    assert "description" in schema["properties"]["mechanism_of_action"]
    assert "target_population" in schema["properties"]
    assert "primary_endpoints" in schema["properties"]
    assert "key_risks" in schema["properties"]
    assert set(schema["required"]) >= {"nct_id", "mechanism_of_action", "target_population"}


def test_clinical_summary_json_roundtrip():
    """Verify serialization to JSON string and parsing back."""
    original = ClinicalSummaryOut(
        nct_id="NCT99998888",
        mechanism_of_action="CAR-T cell therapy targeting CD19",
        target_population="Relapsed/refractory DLBCL",
        primary_endpoints=["Complete response rate at 3 months"],
        key_risks=["Cytokine release syndrome (CRS)", "ICANS neurotoxicity"],
    )

    json_str = original.model_dump_json()
    reconstructed = ClinicalSummaryOut.model_validate_json(json_str)

    assert reconstructed.nct_id == original.nct_id
    assert reconstructed.mechanism_of_action == original.mechanism_of_action
    assert reconstructed.primary_endpoints == original.primary_endpoints
    assert reconstructed.key_risks == original.key_risks


# ==============================================================================
# Service & Provider Tests
# ==============================================================================


def test_mock_llm_provider_antibody_synthesis():
    """Verify MockLLMProvider detects antibody interventions and tailors the summary."""
    provider = MockLLMProvider()
    result = provider.generate_summary(
        nct_id="NCT01234567",
        study_title="Trastuzumab trial in HER2+ Breast Cancer",
        brief_summary="Evaluating trastuzumab in combination with pertuzumab.",
        detailed_description="Full protocol details...",
        conditions=["Breast Neoplasms", "HER2-Positive"],
        interventions=[{"intervention_name": "Trastuzumab", "intervention_type": "DRUG"}],
    )

    assert result.nct_id == "NCT01234567"
    assert "monoclonal antibody" in result.mechanism_of_action.lower()
    assert "Breast Neoplasms" in result.target_population
    assert len(result.primary_endpoints) >= 1
    assert len(result.key_risks) >= 1
    assert result.model_name == "mock-clinical-v1"


def test_mock_llm_provider_inhibitor_synthesis():
    """Verify MockLLMProvider detects small-molecule kinase inhibitors."""
    provider = MockLLMProvider()
    result = provider.generate_summary(
        nct_id="NCT05555555",
        study_title="Olaparib in BRCA Mutated Ovarian Cancer",
        brief_summary="PARP inhibitor study.",
        detailed_description=None,
        conditions=["Ovarian Cancer"],
        interventions=[{"intervention_name": "Olaparib inhibitor", "intervention_type": "DRUG"}],
    )

    assert result.nct_id == "NCT05555555"
    assert "kinase" in result.mechanism_of_action.lower() or "inhibitor" in result.mechanism_of_action.lower()
    assert "Ovarian Cancer" in result.target_population


def test_summarizer_service_flow():
    """Verify ClinicalProtocolSummarizer unpacks trial dict and calls provider."""
    provider = MockLLMProvider()
    summarizer = ClinicalProtocolSummarizer(provider=provider)

    trial_data = {
        "nct_id": "NCT08888888",
        "official_title": "Phase 3 Study of Pembrolizumab",
        "brief_summary": "Immunotherapy for melanoma",
        "detailed_description": "Extended protocol...",
        "conditions": ["Melanoma"],
        "interventions": [{"intervention_name": "Pembrolizumab"}],
    }

    summary = summarizer.summarize_trial(trial_data)
    assert summary.nct_id == "NCT08888888"
    assert summary.study_title == "Phase 3 Study of Pembrolizumab"
    assert "Melanoma" in summary.target_population


def test_summarizer_service_missing_nct_id():
    """Verify that summarizing a trial record without nct_id raises GenAIServiceError."""
    summarizer = ClinicalProtocolSummarizer(provider=MockLLMProvider())
    with pytest.raises(GenAIServiceError) as exc_info:
        summarizer.summarize_trial({"brief_title": "Trial without ID"})
    assert "missing required 'nct_id'" in str(exc_info.value)


def test_gemini_provider_requires_api_key():
    """Verify that initializing GeminiLLMProvider without key raises GenAIServiceError."""
    with pytest.raises(GenAIServiceError):
        GeminiLLMProvider(api_key="")


def test_gemini_provider_successful_mocked_http():
    """Verify GeminiLLMProvider parses valid Gemini API JSON response."""
    mock_http_client = MagicMock(spec=httpx.Client)

    # Fake Gemini API response structure
    gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "nct_id": "NCT01234567",
                                "study_title": "Gemini Trial",
                                "mechanism_of_action": "CDK4/6 inhibitor blocking cell cycle progression",
                                "target_population": "Postmenopausal women with HR+/HER2- breast cancer",
                                "primary_endpoints": ["Progression-free survival"],
                                "key_risks": ["Neutropenia", "Infections"],
                                "design_summary": "Phase 3 double-blind randomized",
                                "model_name": "gemini-1.5-flash",
                                "generated_at": "2026-10-23T12:00:00Z"
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = gemini_payload
    mock_http_client.post.return_value = mock_response

    provider = GeminiLLMProvider(
        api_key="test-api-key-12345",
        model_name="gemini-1.5-flash",
        http_client=mock_http_client,
    )

    result = provider.generate_summary(
        nct_id="NCT01234567",
        study_title="Gemini Trial",
        brief_summary="Summary",
        detailed_description="Details",
    )

    assert result.nct_id == "NCT01234567"
    assert "CDK4/6" in result.mechanism_of_action
    assert mock_http_client.post.called


def test_gemini_provider_http_error():
    """Verify GeminiLLMProvider handles HTTP error codes gracefully."""
    mock_http_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = "Quota exceeded"
    mock_http_client.post.return_value = mock_response

    provider = GeminiLLMProvider(api_key="valid-key", http_client=mock_http_client)

    with pytest.raises(GenAIServiceError) as exc_info:
        provider.generate_summary(nct_id="NCT01234567", study_title="Test", brief_summary=None, detailed_description=None)
    assert "error 429" in str(exc_info.value)


def test_get_summarizer_factory():
    """Verify factory returns appropriate provider based on settings."""
    # 1. Default settings -> Mock provider
    cfg_mock = Settings(llm_provider="mock")
    summarizer_mock = get_summarizer(cfg_mock)
    assert isinstance(summarizer_mock.provider, MockLLMProvider)

    # 2. Gemini setting with empty key -> Fallback to Mock provider
    cfg_fallback = Settings(llm_provider="gemini", llm_api_key=None)
    summarizer_fallback = get_summarizer(cfg_fallback)
    assert isinstance(summarizer_fallback.provider, MockLLMProvider)

    # 3. Gemini setting with key -> GeminiLLMProvider
    cfg_gemini = Settings(llm_provider="gemini", llm_api_key="fake-key")
    summarizer_gemini = get_summarizer(cfg_gemini)
    assert isinstance(summarizer_gemini.provider, GeminiLLMProvider)
