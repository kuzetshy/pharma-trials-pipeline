"""Unit and integration tests for Silver layer transformation module."""

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from src.transformation.models import (
    CleanTrial,
    normalize_clinical_date,
    parse_raw_study,
)
from src.transformation.silver import run_silver_transformation
from src.utils.config import Settings


def test_normalize_clinical_date() -> None:
    """Verify normalization of various ClinicalTrials.gov date formats."""
    # Full ISO
    assert normalize_clinical_date("2024-04-21") == "2024-04-21"
    # Year-Month
    assert normalize_clinical_date("2024-04") == "2024-04-01"
    assert normalize_clinical_date(" 2024-12 ") == "2024-12-01"
    # Year-only
    assert normalize_clinical_date("2024") == "2024-01-01"
    # Text format
    assert normalize_clinical_date("April 2024") == "2024-04-01"
    assert normalize_clinical_date("April 21, 2024") == "2024-04-21"
    # Invalid / empty
    assert normalize_clinical_date("") is None
    assert normalize_clinical_date("   ") is None
    assert normalize_clinical_date(None) is None
    assert normalize_clinical_date("not-a-date") is None


def test_clean_trial_validation() -> None:
    """Verify NCT identifier validation logic in CleanTrial."""
    valid = CleanTrial(
        nct_id="NCT12345678",
        brief_title="Test Trial",
        processed_at_utc="2026-10-21T00:00:00Z",
    )
    assert valid.nct_id == "NCT12345678"

    # Lowercase should be auto-converted to uppercase
    lower = CleanTrial(
        nct_id="nct12345678",
        brief_title="Test Trial",
        processed_at_utc="2026-10-21T00:00:00Z",
    )
    assert lower.nct_id == "NCT12345678"

    # Malformed ID should raise validation error
    with pytest.raises(ValueError, match="Invalid NCT identifier"):
        CleanTrial(
            nct_id="INVALID_ID",
            brief_title="Test Trial",
            processed_at_utc="2026-10-21T00:00:00Z",
        )


def test_parse_raw_study_success() -> None:
    """Verify parsing a complete raw study dictionary into domain models."""
    raw_study: dict[str, Any] = {
        "hasResults": True,
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00567554",
                "briefTitle": "Breast Cancer Trial",
                "officialTitle": "Official Long Study Title",
            },
            "statusModule": {
                "overallStatus": "COMPLETED",
                "startDateStruct": {"date": "2020-01-15"},
                "primaryCompletionDateStruct": {"date": "2022-05"},
                "completionDateStruct": {"date": "2023"},
                "lastUpdatePostDateStruct": {"date": "2024-01-10"},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Pharma Corp", "class": "INDUSTRY"}
            },
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": ["PHASE2", "PHASE3"],
                "enrollmentInfo": {"count": 450},
            },
            "eligibilityModule": {
                "sex": "FEMALE",
                "minimumAge": "18 Years",
                "maximumAge": "70 Years",
            },
            "descriptionModule": {
                "briefSummary": "A study evaluating chemotherapy effectiveness."
            },
            "conditionsModule": {
                "conditions": ["Breast Cancer", "Neoplasms"]
            },
            "armsInterventionsModule": {
                "interventions": [
                    {
                        "type": "DRUG",
                        "name": "Trastuzumab",
                        "description": "6mg/kg IV",
                    },
                    {
                        "type": "DRUG",
                        "name": "Paclitaxel",
                        "description": "80mg/m2 IV",
                    },
                ]
            },
        },
    }

    parsed = parse_raw_study(raw_study)
    assert parsed is not None

    trial = parsed.trial
    assert trial.nct_id == "NCT00567554"
    assert trial.brief_title == "Breast Cancer Trial"
    assert trial.official_title == "Official Long Study Title"
    assert trial.overall_status == "COMPLETED"
    assert trial.phase == "PHASE2/PHASE3"
    assert trial.lead_sponsor_name == "Pharma Corp"
    assert trial.lead_sponsor_class == "INDUSTRY"
    assert trial.start_date == "2020-01-15"
    assert trial.primary_completion_date == "2022-05-01"
    assert trial.completion_date == "2023-01-01"
    assert trial.last_update_date == "2024-01-10"
    assert trial.enrollment_count == 450
    assert trial.sex == "FEMALE"
    assert trial.has_results is True
    assert trial.brief_summary == "A study evaluating chemotherapy effectiveness."

    assert len(parsed.conditions) == 2
    assert [c.condition for c in parsed.conditions] == ["Breast Cancer", "Neoplasms"]

    assert len(parsed.interventions) == 2
    assert parsed.interventions[0].intervention_name == "Trastuzumab"
    assert parsed.interventions[0].intervention_type == "DRUG"
    assert parsed.interventions[1].intervention_name == "Paclitaxel"


def test_parse_raw_study_malformed() -> None:
    """Verify malformed records return None instead of crashing."""
    assert parse_raw_study({}) is None
    assert parse_raw_study({"protocolSection": {}}) is None
    assert parse_raw_study({"protocolSection": {"identificationModule": {"nctId": ""}}}) is None
    assert parse_raw_study({"protocolSection": {"identificationModule": {"nctId": "BAD_ID"}}}) is None


def test_run_silver_transformation_deduplication(tmp_path: Path) -> None:
    """Verify DuckDB deduplication: latest version of a study wins across batches."""
    bronze_dir = tmp_path / "bronze"
    silver_dir = tmp_path / "silver"
    bronze_dir.mkdir(parents=True)

    # Batch 1 contains NCT00000001 (old version) and NCT00000002
    batch_1 = {
        "metadata": {"batch_index": 1},
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000001",
                        "briefTitle": "Old Title for Study 1",
                    },
                    "statusModule": {
                        "overallStatus": "RECRUITING",
                        "lastUpdatePostDateStruct": {"date": "2023-01-01"},
                    },
                    "conditionsModule": {"conditions": ["Condition A"]},
                }
            },
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000002",
                        "briefTitle": "Study 2 Unique",
                    },
                    "statusModule": {
                        "overallStatus": "COMPLETED",
                        "lastUpdatePostDateStruct": {"date": "2023-05-01"},
                    },
                    "conditionsModule": {"conditions": ["Condition B"]},
                }
            },
        ],
    }

    # Batch 2 contains updated NCT00000001 (newer date & title) and duplicate NCT00000002
    batch_2 = {
        "metadata": {"batch_index": 2},
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000001",
                        "briefTitle": "Updated New Title for Study 1",
                    },
                    "statusModule": {
                        "overallStatus": "COMPLETED",
                        "lastUpdatePostDateStruct": {"date": "2024-06-15"},
                    },
                    "conditionsModule": {"conditions": ["Condition A", "Condition A Updated"]},
                    "armsInterventionsModule": {
                        "interventions": [{"name": "Drug X", "type": "DRUG"}]
                    },
                }
            },
        ],
    }

    with open(bronze_dir / "trials_20261021_batch_01.json", "w", encoding="utf-8") as f:
        json.dump(batch_1, f)

    with open(bronze_dir / "trials_20261021_batch_02.json", "w", encoding="utf-8") as f:
        json.dump(batch_2, f)

    test_settings = Settings(
        bronze_dir=bronze_dir,
        silver_dir=silver_dir,
    )

    summary = run_silver_transformation(
        bronze_dir=bronze_dir,
        silver_dir=silver_dir,
        config=test_settings,
    )

    assert summary.files_scanned == 2
    assert summary.raw_studies_read == 3
    assert summary.distinct_trials_saved == 2

    # Query generated Parquet files using DuckDB
    con = duckdb.connect()

    trials_df = con.execute(
        f"SELECT nct_id, brief_title, overall_status, last_update_date FROM '{silver_dir}/trials.parquet' ORDER BY nct_id"
    ).fetchall()

    assert len(trials_df) == 2
    # Verify latest record won for NCT00000001
    nct1_record = trials_df[0]
    assert nct1_record[0] == "NCT00000001"
    assert nct1_record[1] == "Updated New Title for Study 1"
    assert nct1_record[2] == "COMPLETED"
    assert nct1_record[3] == "2024-06-15"

    # Verify conditions bridge Parquet
    cond_df = con.execute(
        f"SELECT nct_id, condition FROM '{silver_dir}/trial_conditions.parquet' ORDER BY nct_id, condition"
    ).fetchall()
    assert len(cond_df) == 3

    # Verify interventions bridge Parquet
    interv_df = con.execute(
        f"SELECT nct_id, intervention_name, intervention_type FROM '{silver_dir}/trial_interventions.parquet'"
    ).fetchall()
    assert len(interv_df) == 1
    assert interv_df[0] == ("NCT00000001", "Drug X", "DRUG")

    con.close()


def test_run_silver_transformation_empty_dir(tmp_path: Path) -> None:
    """Verify pipeline runs gracefully when bronze directory has no files."""
    bronze_dir = tmp_path / "empty_bronze"
    silver_dir = tmp_path / "silver"

    summary = run_silver_transformation(bronze_dir=bronze_dir, silver_dir=silver_dir)
    assert summary.files_scanned == 0
    assert summary.distinct_trials_saved == 0
