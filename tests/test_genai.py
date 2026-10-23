"""Unit tests for GenAI schemas and structured protocol models."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.genai.schemas import ClinicalSummaryOut


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
