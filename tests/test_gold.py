"""Unit and integration tests for Gold layer transformation module."""

from pathlib import Path

import duckdb
import pytest

from src.transformation.gold import run_gold_transformation
from src.utils.config import Settings


def create_mock_silver_tables(silver_dir: Path) -> None:
    """Helper to generate sample Silver Parquet tables for testing Gold layer."""
    silver_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    # Create mock trials
    con.execute(
        f"""
        COPY (
            SELECT
                'NCT00000001' AS nct_id,
                'Trial 1' AS brief_title,
                'Official 1' AS official_title,
                'COMPLETED' AS overall_status,
                'INTERVENTIONAL' AS study_type,
                'PHASE3' AS phase,
                'Pfizer' AS lead_sponsor_name,
                'INDUSTRY' AS lead_sponsor_class,
                '2020-01-01' AS start_date,
                '2021-12-01' AS primary_completion_date,
                '2022-01-01' AS completion_date,
                '2022-01-02' AS last_update_date,
                100::BIGINT AS enrollment_count,
                'ALL' AS sex,
                '18 Years' AS min_age,
                NULL::VARCHAR AS max_age,
                TRUE AS has_results,
                'Summary 1' AS brief_summary,
                '2026-10-21T00:00:00Z' AS processed_at_utc
            UNION ALL
            SELECT
                'NCT00000002', 'Trial 2', 'Official 2', 'RECRUITING', 'INTERVENTIONAL',
                'PHASE2', 'Pfizer', 'INDUSTRY', '2021-06-01', '2023-01-01',
                '2023-06-01', '2023-06-02', 50::BIGINT, 'FEMALE', '21 Years',
                '65 Years', FALSE, 'Summary 2', '2026-10-21T00:00:00Z'
            UNION ALL
            SELECT
                'NCT00000003', 'Trial 3', 'Official 3', 'TERMINATED', 'OBSERVATIONAL',
                NULL, 'NIH', 'NIH', '2020-05-01', NULL,
                NULL, '2021-01-01', 20::BIGINT, 'ALL', NULL,
                NULL, FALSE, 'Summary 3', '2026-10-21T00:00:00Z'
        ) TO '{(silver_dir / "trials.parquet").as_posix()}' (FORMAT PARQUET);
        """
    )

    # Create mock interventions
    con.execute(
        f"""
        COPY (
            SELECT
                'NCT00000001' AS nct_id,
                'DRUG' AS intervention_type,
                'Trastuzumab' AS intervention_name,
                '6mg/kg IV' AS description
            UNION ALL
            SELECT
                'NCT00000002' AS nct_id,
                'DRUG' AS intervention_type,
                'Trastuzumab' AS intervention_name,
                'Maintenance dose' AS description
            UNION ALL
            SELECT
                'NCT00000003' AS nct_id,
                'OTHER' AS intervention_type,
                'Lifestyle Coaching' AS intervention_name,
                NULL AS description
        ) TO '{(silver_dir / "trial_interventions.parquet").as_posix()}' (FORMAT PARQUET);
        """
    )

    con.close()


def test_gold_transformation_missing_silver(tmp_path: Path) -> None:
    """Verify pipeline handles missing Silver tables gracefully."""
    empty_silver = tmp_path / "empty_silver"
    gold_dir = tmp_path / "gold"

    summary = run_gold_transformation(silver_dir=empty_silver, gold_dir=gold_dir)
    assert summary.sponsors_aggregated == 0
    assert summary.drugs_aggregated == 0
    assert summary.timeline_buckets == 0


def test_gold_transformation_metrics_and_marts(tmp_path: Path) -> None:
    """Verify analytical metrics and accuracy of generated Gold data marts."""
    silver_dir = tmp_path / "silver"
    gold_dir = tmp_path / "gold"

    create_mock_silver_tables(silver_dir)

    test_settings = Settings(silver_dir=silver_dir, gold_dir=gold_dir)
    summary = run_gold_transformation(
        silver_dir=silver_dir,
        gold_dir=gold_dir,
        config=test_settings,
    )

    assert summary.sponsors_aggregated == 2  # Pfizer, NIH
    assert summary.drugs_aggregated == 2     # Trastuzumab, Lifestyle Coaching
    assert summary.timeline_buckets == 3     # (2020 Interventional, 2020 Observational, 2021 Interventional)

    con = duckdb.connect()

    # 1. Test mart_sponsor_benchmarks
    pfizer_metrics = con.execute(
        f"""
        SELECT total_trials, active_trials, completed_trials, terminated_trials,
               phase_3_trials, total_enrolled_patients, results_reporting_rate_pct
        FROM '{(gold_dir / "mart_sponsor_benchmarks.parquet").as_posix()}'
        WHERE lead_sponsor_name = 'Pfizer'
        """
    ).fetchone()

    assert pfizer_metrics is not None
    assert pfizer_metrics[0] == 2      # total_trials
    assert pfizer_metrics[1] == 1      # active_trials
    assert pfizer_metrics[2] == 1      # completed_trials
    assert pfizer_metrics[3] == 0      # terminated_trials
    assert pfizer_metrics[4] == 1      # phase_3_trials
    assert pfizer_metrics[5] == 150    # total_enrolled_patients (100 + 50)
    assert pfizer_metrics[6] == 50.0   # results_reporting_rate_pct (1 with results out of 2)

    # 2. Test mart_drug_landscape
    trastuzumab_metrics = con.execute(
        f"""
        SELECT total_trials_count, distinct_sponsors_count, active_trials_count,
               completed_trials_count, phase_3_trials_count, total_patient_reach
        FROM '{(gold_dir / "mart_drug_landscape.parquet").as_posix()}'
        WHERE intervention_name = 'Trastuzumab'
        """
    ).fetchone()

    assert trastuzumab_metrics is not None
    assert trastuzumab_metrics[0] == 2     # total_trials_count
    assert trastuzumab_metrics[1] == 1     # distinct_sponsors_count (Pfizer)
    assert trastuzumab_metrics[2] == 1     # active_trials_count
    assert trastuzumab_metrics[3] == 1     # completed_trials_count
    assert trastuzumab_metrics[4] == 1     # phase_3_trials_count
    assert trastuzumab_metrics[5] == 150   # total_patient_reach

    # 3. Test mart_trials_timeline
    timeline_2020_interv = con.execute(
        f"""
        SELECT trials_started_count, total_planned_enrollment, avg_trial_duration_days
        FROM '{(gold_dir / "mart_trials_timeline.parquet").as_posix()}'
        WHERE start_year = 2020 AND study_type = 'INTERVENTIONAL'
        """
    ).fetchone()

    assert timeline_2020_interv is not None
    assert timeline_2020_interv[0] == 1      # 1 interventional trial started in 2020
    assert timeline_2020_interv[1] == 100    # 100 enrolled
    assert timeline_2020_interv[2] == 731.0  # Duration: 2020-01-01 to 2022-01-01 (leap year 2020: 366+365=731)

    con.close()
