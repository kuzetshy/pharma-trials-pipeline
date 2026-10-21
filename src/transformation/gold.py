"""Gold Layer Transformation Pipeline.

Aggregates cleaned analytical Parquet tables from Silver layer into dimensional
business marts for competitive intelligence, drug landscape exploration, and timeline trends:
1. mart_sponsor_benchmarks.parquet
2. mart_drug_landscape.parquet
3. mart_trials_timeline.parquet
"""

import argparse
from pathlib import Path

import duckdb

from src.utils.config import Settings, settings
from src.utils.logger import setup_logger

logger = setup_logger("pharma_gold")


class GoldTransformationSummary:
    """Statistics summary for a Gold transformation run."""

    def __init__(
        self,
        sponsors_aggregated: int,
        drugs_aggregated: int,
        timeline_buckets: int,
        output_files: dict[str, Path],
    ) -> None:
        self.sponsors_aggregated = sponsors_aggregated
        self.drugs_aggregated = drugs_aggregated
        self.timeline_buckets = timeline_buckets
        self.output_files = output_files

    def log_summary(self) -> None:
        """Output formatted run statistics to logger."""
        logger.info("=" * 70)
        logger.info("Gold Transformation Summary (Analytical Marts):")
        logger.info("  Sponsors Benchmarked:       %d", self.sponsors_aggregated)
        logger.info("  Drugs & Interventions:      %d", self.drugs_aggregated)
        logger.info("  Timeline Trend Buckets:     %d", self.timeline_buckets)
        for name, path in self.output_files.items():
            logger.info("  Mart Artifact [%s]: %s", name, path)
        logger.info("=" * 70)


def run_gold_transformation(
    silver_dir: Path | None = None,
    gold_dir: Path | None = None,
    config: Settings = settings,
) -> GoldTransformationSummary:
    """Execute Gold layer analytical aggregation using DuckDB OLAP queries.

    Reads Silver Parquet tables (`trials.parquet`, `trial_interventions.parquet`),
    computes business KPIs and metrics, and writes analytical marts to `data/gold/`.

    Args:
        silver_dir: Source Silver directory (defaults to config.silver_dir).
        gold_dir: Destination Gold directory (defaults to config.gold_dir).
        config: Application configuration instance.

    Returns:
        GoldTransformationSummary object with run statistics.
    """
    src_silver = silver_dir or config.silver_dir
    target_gold = gold_dir or config.gold_dir
    target_gold.mkdir(parents=True, exist_ok=True)

    trials_parquet = src_silver / "trials.parquet"
    interventions_parquet = src_silver / "trial_interventions.parquet"

    sponsor_mart_file = target_gold / "mart_sponsor_benchmarks.parquet"
    drug_mart_file = target_gold / "mart_drug_landscape.parquet"
    timeline_mart_file = target_gold / "mart_trials_timeline.parquet"

    outputs = {
        "sponsor_benchmarks": sponsor_mart_file,
        "drug_landscape": drug_mart_file,
        "trials_timeline": timeline_mart_file,
    }

    if not trials_parquet.exists():
        logger.warning("Silver trials table %s not found. Skipping Gold layer generation.", trials_parquet)
        return GoldTransformationSummary(
            sponsors_aggregated=0,
            drugs_aggregated=0,
            timeline_buckets=0,
            output_files=outputs,
        )

    logger.info("=" * 70)
    logger.info("Starting Gold Layer Transformation (Silver -> Gold Marts)")
    logger.info("Source Silver: %s", src_silver)
    logger.info("Target Gold:   %s", target_gold)
    logger.info("=" * 70)

    con = duckdb.connect(database=":memory:")

    # Load Silver tables as views
    con.execute(f"CREATE VIEW silver_trials AS SELECT * FROM read_parquet('{trials_parquet.as_posix()}');")

    if interventions_parquet.exists():
        con.execute(
            f"CREATE VIEW silver_interventions AS SELECT * FROM read_parquet('{interventions_parquet.as_posix()}');"
        )
    else:
        con.execute(
            """
            CREATE VIEW silver_interventions AS
            SELECT ''::VARCHAR AS nct_id, ''::VARCHAR AS intervention_type,
                   ''::VARCHAR AS intervention_name, ''::VARCHAR AS description
            WHERE 1 = 0;
            """
        )

    # 1. Sponsor Benchmarks Mart
    logger.info("Building mart_sponsor_benchmarks...")
    con.execute(
        f"""
        CREATE TABLE mart_sponsor_benchmarks AS
        SELECT
            COALESCE(lead_sponsor_name, 'Unknown Sponsor') AS lead_sponsor_name,
            COALESCE(lead_sponsor_class, 'UNKNOWN') AS lead_sponsor_class,
            COUNT(*) AS total_trials,
            COUNT(*) FILTER (WHERE overall_status IN ('RECRUITING', 'ACTIVE_NOT_RECRUITING', 'ENROLLING_BY_INVITATION')) AS active_trials,
            COUNT(*) FILTER (WHERE overall_status = 'COMPLETED') AS completed_trials,
            COUNT(*) FILTER (WHERE overall_status IN ('TERMINATED', 'SUSPENDED', 'WITHDRAWN')) AS terminated_trials,
            COUNT(*) FILTER (WHERE phase ILIKE '%PHASE1%') AS phase_1_trials,
            COUNT(*) FILTER (WHERE phase ILIKE '%PHASE2%') AS phase_2_trials,
            COUNT(*) FILTER (WHERE phase ILIKE '%PHASE3%') AS phase_3_trials,
            COUNT(*) FILTER (WHERE phase ILIKE '%PHASE4%') AS phase_4_trials,
            COALESCE(SUM(enrollment_count), 0) AS total_enrolled_patients,
            ROUND(AVG(enrollment_count), 1) AS avg_enrollment_per_trial,
            ROUND(100.0 * COUNT(*) FILTER (WHERE has_results IS TRUE) / NULLIF(COUNT(*), 0), 2) AS results_reporting_rate_pct
        FROM silver_trials
        GROUP BY 1, 2
        ORDER BY total_trials DESC, total_enrolled_patients DESC;

        COPY mart_sponsor_benchmarks TO '{sponsor_mart_file.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
    )
    sponsors_count: int = con.execute("SELECT COUNT(*) FROM mart_sponsor_benchmarks").fetchone()[0]  # type: ignore[index]

    # 2. Drug & Interventions Landscape Mart
    logger.info("Building mart_drug_landscape...")
    con.execute(
        f"""
        CREATE TABLE mart_drug_landscape AS
        SELECT
            i.intervention_name,
            COALESCE(i.intervention_type, 'OTHER') AS intervention_type,
            COUNT(DISTINCT i.nct_id) AS total_trials_count,
            COUNT(DISTINCT t.lead_sponsor_name) AS distinct_sponsors_count,
            COUNT(DISTINCT i.nct_id) FILTER (WHERE t.overall_status IN ('RECRUITING', 'ACTIVE_NOT_RECRUITING')) AS active_trials_count,
            COUNT(DISTINCT i.nct_id) FILTER (WHERE t.overall_status = 'COMPLETED') AS completed_trials_count,
            COUNT(DISTINCT i.nct_id) FILTER (WHERE t.phase ILIKE '%PHASE3%') AS phase_3_trials_count,
            COALESCE(SUM(t.enrollment_count), 0) AS total_patient_reach
        FROM silver_interventions i
        INNER JOIN silver_trials t ON i.nct_id = t.nct_id
        WHERE i.intervention_name IS NOT NULL AND TRIM(i.intervention_name) != ''
        GROUP BY 1, 2
        ORDER BY total_trials_count DESC, distinct_sponsors_count DESC;

        COPY mart_drug_landscape TO '{drug_mart_file.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
    )
    drugs_count: int = con.execute("SELECT COUNT(*) FROM mart_drug_landscape").fetchone()[0]  # type: ignore[index]

    # 3. Trials Timeline & Duration Mart
    logger.info("Building mart_trials_timeline...")
    con.execute(
        f"""
        CREATE TABLE mart_trials_timeline AS
        SELECT
            TRY_CAST(SUBSTR(start_date, 1, 4) AS INTEGER) AS start_year,
            COALESCE(study_type, 'UNKNOWN') AS study_type,
            COUNT(*) AS trials_started_count,
            COUNT(*) FILTER (WHERE overall_status = 'COMPLETED') AS completed_count,
            COUNT(*) FILTER (WHERE overall_status IN ('TERMINATED', 'SUSPENDED', 'WITHDRAWN')) AS terminated_count,
            COALESCE(SUM(enrollment_count), 0) AS total_planned_enrollment,
            ROUND(AVG(
                CASE
                    WHEN start_date IS NOT NULL
                     AND completion_date IS NOT NULL
                     AND TRY_CAST(start_date AS DATE) IS NOT NULL
                     AND TRY_CAST(completion_date AS DATE) IS NOT NULL
                     AND TRY_CAST(completion_date AS DATE) >= TRY_CAST(start_date AS DATE)
                    THEN DATEDIFF('day', TRY_CAST(start_date AS DATE), TRY_CAST(completion_date AS DATE))
                    ELSE NULL
                END
            ), 1) AS avg_trial_duration_days
        FROM silver_trials
        WHERE start_date IS NOT NULL AND TRY_CAST(SUBSTR(start_date, 1, 4) AS INTEGER) IS NOT NULL
        GROUP BY 1, 2
        ORDER BY start_year ASC, study_type ASC;

        COPY mart_trials_timeline TO '{timeline_mart_file.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
    )
    timeline_count: int = con.execute("SELECT COUNT(*) FROM mart_trials_timeline").fetchone()[0]  # type: ignore[index]

    con.close()

    summary = GoldTransformationSummary(
        sponsors_aggregated=sponsors_count,
        drugs_aggregated=drugs_count,
        timeline_buckets=timeline_count,
        output_files=outputs,
    )
    summary.log_summary()
    return summary


def main() -> None:
    """CLI entrypoint for executing Gold layer transformations."""
    parser = argparse.ArgumentParser(
        description="Aggregate Silver Parquet tables into Gold analytical data marts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--silver-dir",
        type=Path,
        default=settings.silver_dir,
        help="Source directory containing Silver Parquet tables.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=settings.gold_dir,
        help="Destination directory for Gold data marts.",
    )

    args = parser.parse_args()
    run_gold_transformation(silver_dir=args.silver_dir, gold_dir=args.gold_dir)


if __name__ == "__main__":
    main()
