"""Pydantic data models and schemas for Silver layer normalization.

Defines schemas for:
- CleanTrial (main study entity)
- TrialCondition (1-to-many relationship: study to conditions)
- TrialIntervention (1-to-many relationship: study to drugs/interventions)
- ParsedStudy (aggregated container of validated study records)
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_clinical_date(val: Any) -> str | None:
    """Normalize inconsistent ClinicalTrials date formats into ISO standard YYYY-MM-DD.

    Handles:
    - '2024-04-21' -> '2024-04-21'
    - '2024-04' -> '2024-04-01'
    - '2024' -> '2024-01-01'
    - 'April 2024' -> '2024-04-01'
    - 'April 21, 2024' -> '2024-04-21'

    Returns:
        Standardized ISO date string (YYYY-MM-DD) or None if absent/invalid.
    """
    if not val or not isinstance(val, str):
        return None

    cleaned = val.strip()
    if not cleaned:
        return None

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    # YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", cleaned):
        return f"{cleaned}-01"

    # YYYY
    if re.match(r"^\d{4}$", cleaned):
        return f"{cleaned}-01-01"

    # Human-readable formats (e.g. 'April 2024', 'April 21, 2024')
    for fmt, fallback_day in (("%B %d, %Y", False), ("%B %Y", True)):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fallback_day:
                return dt.strftime("%Y-%m-01")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


class CleanTrial(BaseModel):
    """Normalized and validated single clinical study record."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    nct_id: str = Field(description="Unique National Clinical Trial identifier (e.g. NCT00567554)")
    brief_title: str = Field(description="Short human-readable study title")
    official_title: str | None = Field(default=None, description="Full scientific study title")
    overall_status: str = Field(default="UNKNOWN", description="Recruitment/operational status")
    study_type: str | None = Field(default=None, description="Interventional, Observational, etc.")
    phase: str | None = Field(default=None, description="Clinical trial phase (e.g., PHASE1, PHASE2/PHASE3)")
    lead_sponsor_name: str | None = Field(default=None, description="Primary organization conducting the study")
    lead_sponsor_class: str | None = Field(default=None, description="Category of sponsor (INDUSTRY, OTHER, NIH, etc.)")
    start_date: str | None = Field(default=None, description="Study start date (ISO YYYY-MM-DD)")
    primary_completion_date: str | None = Field(default=None, description="Primary outcome completion date (ISO YYYY-MM-DD)")
    completion_date: str | None = Field(default=None, description="Overall completion date (ISO YYYY-MM-DD)")
    last_update_date: str | None = Field(default=None, description="Latest update date posted to ClinicalTrials.gov")
    enrollment_count: int | None = Field(default=None, ge=0, description="Target or actual number of participants")
    sex: str | None = Field(default=None, description="Eligible sex (ALL, FEMALE, MALE)")
    min_age: str | None = Field(default=None, description="Minimum eligibility age")
    max_age: str | None = Field(default=None, description="Maximum eligibility age")
    has_results: bool = Field(default=False, description="Whether study has posted results on ClinicalTrials.gov")
    brief_summary: str | None = Field(default=None, description="Executive summary of the trial protocol")
    processed_at_utc: str = Field(description="Timestamp in UTC when record was transformed into Silver layer")

    @field_validator("nct_id")
    @classmethod
    def validate_nct_id(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if not re.match(r"^NCT\d{8}$", v_upper):
            raise ValueError(f"Invalid NCT identifier format: '{v}' (expected 'NCT' followed by 8 digits)")
        return v_upper


class TrialCondition(BaseModel):
    """Condition/disease entity associated with a study (1-to-many)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    nct_id: str
    condition: str


class TrialIntervention(BaseModel):
    """Intervention/drug/device entity tested in a study (1-to-many)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    nct_id: str
    intervention_type: str | None = Field(default=None, description="DRUG, BIOLOGICAL, PROCEDURE, DEVICE, etc.")
    intervention_name: str
    description: str | None = None


class ParsedStudy(BaseModel):
    """Aggregate containing the cleaned trial record and its relational bridge entities."""

    trial: CleanTrial
    conditions: list[TrialCondition] = Field(default_factory=list)
    interventions: list[TrialIntervention] = Field(default_factory=list)


def parse_raw_study(raw_study: dict[str, Any], processed_at: str | None = None) -> ParsedStudy | None:
    """Parse a single raw study JSON object from Bronze into normalized Silver domain models.

    Args:
        raw_study: Raw study dictionary matching ClinicalTrials.gov v2 response structure.
        processed_at: Optional UTC timestamp ISO string. Defaults to current UTC time.

    Returns:
        ParsedStudy aggregate instance, or None if raw record is fundamentally malformed.
    """
    if not isinstance(raw_study, dict):
        return None

    protocol = raw_study.get("protocolSection")
    if not isinstance(protocol, dict):
        return None

    # 1. Identification
    ident = protocol.get("identificationModule", {})
    nct_id = ident.get("nctId")
    if not nct_id or not isinstance(nct_id, str):
        return None

    brief_title = ident.get("briefTitle") or "Untitled Study"
    official_title = ident.get("officialTitle")

    # 2. Status & Dates
    status_mod = protocol.get("statusModule", {})
    overall_status = status_mod.get("overallStatus") or "UNKNOWN"

    start_date = normalize_clinical_date(status_mod.get("startDateStruct", {}).get("date"))
    primary_completion_date = normalize_clinical_date(
        status_mod.get("primaryCompletionDateStruct", {}).get("date")
    )
    completion_date = normalize_clinical_date(status_mod.get("completionDateStruct", {}).get("date"))

    last_update_date = (
        normalize_clinical_date(status_mod.get("lastUpdatePostDateStruct", {}).get("date"))
        or normalize_clinical_date(status_mod.get("lastUpdateSubmitDate"))
        or normalize_clinical_date(status_mod.get("studyFirstSubmitDate"))
    )

    # 3. Sponsor
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
    lead_sponsor = sponsor_mod.get("leadSponsor", {})
    lead_sponsor_name = lead_sponsor.get("name")
    lead_sponsor_class = lead_sponsor.get("class")

    # 4. Design & Phases
    design_mod = protocol.get("designModule", {})
    study_type = design_mod.get("studyType")
    raw_phases = design_mod.get("phases")
    if isinstance(raw_phases, list) and raw_phases:
        phase = "/".join(str(p) for p in raw_phases if p)
    else:
        phase = None

    enrollment_info = design_mod.get("enrollmentInfo", {})
    enrollment_count = enrollment_info.get("count")
    if enrollment_count is not None:
        try:
            enrollment_count = int(enrollment_count)
            if enrollment_count < 0:
                enrollment_count = None
        except (ValueError, TypeError):
            enrollment_count = None

    # 5. Eligibility
    eligibility_mod = protocol.get("eligibilityModule", {})
    sex = eligibility_mod.get("sex")
    min_age = eligibility_mod.get("minimumAge")
    max_age = eligibility_mod.get("maximumAge")

    # 6. Description
    desc_mod = protocol.get("descriptionModule", {})
    brief_summary = desc_mod.get("briefSummary")

    # 7. Results Flag
    has_results = bool(raw_study.get("hasResults", False))

    now_utc = processed_at or datetime.now(UTC).isoformat()

    try:
        trial = CleanTrial(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=official_title,
            overall_status=overall_status,
            study_type=study_type,
            phase=phase,
            lead_sponsor_name=lead_sponsor_name,
            lead_sponsor_class=lead_sponsor_class,
            start_date=start_date,
            primary_completion_date=primary_completion_date,
            completion_date=completion_date,
            last_update_date=last_update_date,
            enrollment_count=enrollment_count,
            sex=sex,
            min_age=min_age,
            max_age=max_age,
            has_results=has_results,
            brief_summary=brief_summary,
            processed_at_utc=now_utc,
        )
    except Exception:
        return None

    # 8. Relational entities: Conditions
    conditions_mod = protocol.get("conditionsModule", {})
    raw_conditions = conditions_mod.get("conditions", [])
    conditions: list[TrialCondition] = []
    if isinstance(raw_conditions, list):
        for cond in raw_conditions:
            if isinstance(cond, str) and cond.strip():
                conditions.append(TrialCondition(nct_id=trial.nct_id, condition=cond.strip()))

    # 9. Relational entities: Interventions
    interventions_mod = protocol.get("armsInterventionsModule", {})
    raw_interventions = interventions_mod.get("interventions", [])
    interventions: list[TrialIntervention] = []
    if isinstance(raw_interventions, list):
        for item in raw_interventions:
            if isinstance(item, dict):
                iname = item.get("name")
                if iname and isinstance(iname, str) and iname.strip():
                    interventions.append(
                        TrialIntervention(
                            nct_id=trial.nct_id,
                            intervention_type=item.get("type"),
                            intervention_name=iname.strip(),
                            description=item.get("description"),
                        )
                    )

    return ParsedStudy(trial=trial, conditions=conditions, interventions=interventions)
