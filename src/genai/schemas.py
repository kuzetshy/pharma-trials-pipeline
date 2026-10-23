"""Pydantic schemas for GenAI clinical protocol summarization and structured extraction."""

from datetime import datetime, timezone
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClinicalSummaryOut(BaseModel):
    """Structured extraction of a clinical trial protocol produced by LLM."""

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_schema_extra={
            "example": {
                "nct_id": "NCT04280705",
                "study_title": "Adaptive COVID-19 Treatment Trial (ACTT)",
                "mechanism_of_action": "Nucleoside analogue inhibitor of viral RNA-dependent RNA polymerase (RdRp)",
                "target_population": "Hospitalized adults aged >=18 with laboratory-confirmed SARS-CoV-2 and pulmonary involvement",
                "primary_endpoints": [
                    "Time to recovery through day 29",
                    "Incidence of adverse events of grade 3 or higher"
                ],
                "key_risks": [
                    "Elevated transaminases (ALT/AST)",
                    "Renal impairment",
                    "Hypersensitivity reactions"
                ],
                "design_summary": "Phase 3, randomized, double-blind, placebo-controlled adaptive clinical trial",
                "model_name": "mock-clinical-v1",
                "generated_at": "2026-10-23T18:00:00Z"
            }
        }
    )

    nct_id: str = Field(
        ...,
        description="Official ClinicalTrials.gov identifier, strictly matching NCT followed by 8 digits",
        examples=["NCT04280705"]
    )
    study_title: str | None = Field(
        default=None,
        description="Official or brief title of the clinical study"
    )
    mechanism_of_action: str = Field(
        ...,
        description="Biological and pharmacological mechanism of action of the experimental drug/intervention"
    )
    target_population: str = Field(
        ...,
        description="Patient cohort description, including diagnosis, stage, key inclusion/exclusion criteria"
    )
    primary_endpoints: list[str] = Field(
        default_factory=list,
        description="List of primary efficacy and safety endpoints being measured"
    )
    key_risks: list[str] = Field(
        default_factory=list,
        description="Known safety risks, toxicities, contraindications, or dose-limiting adverse events"
    )
    design_summary: str | None = Field(
        default=None,
        description="High-level trial design (e.g., Phase, randomization, control arm, masking)"
    )
    model_name: str = Field(
        default="mock-clinical-v1",
        description="Name and version of the LLM model/engine that generated this extraction"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the structured protocol summary was generated"
    )

    @field_validator("nct_id")
    @classmethod
    def validate_nct_id_format(cls, value: str) -> str:
        """Ensure standard ClinicalTrials.gov NCT identifier format."""
        v = value.strip().upper()
        if not re.match(r"^NCT\d{8}$", v):
            raise ValueError(f"Invalid NCT ID format '{value}'. Expected 'NCT' followed by 8 digits.")
        return v
