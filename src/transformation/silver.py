"""Silver Layer Transformation Pipeline.

Loads raw JSON batches from Bronze layer, parses and validates them using Pydantic,
executes SQL deduplication and relational normalization via DuckDB, and persists
clean analytical datasets as Parquet files into data/silver/.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import duckdb

from src.transformation.models import parse_raw_study
from src.utils.config import Settings, settings
from src.utils.logger import setup_logger

logger = setup_logger("pharma_silver")

TRIAL_COLUMNS = [
    "nct_id",
    "brief_title",
    "official_title",
    "overall_status",
    "study_type",
    "phase",
    "lead_sponsor_name",
    "lead_sponsor_class",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "last_update_date",
    "enrollment_count",
    "sex",
    "min_age",
    "max_age",
    "has_results",
    "brief_summary",
    "processed_at_utc",
]

CONDITION_COLUMNS = ["nct_id", "condition"]

INTERVENTION_COLUMNS = ["nct_id", "intervention_type", "intervention_name", "description"]


class SilverTransformationSummary:
    """Statistics summary for a Silver transformation run."""

    def __init__(
        self,
        files_scanned: int,
        raw_studies_read: int,
        valid_studies_parsed: int,
        distinct_trials_saved: int,
        conditions_saved: int,
        interventions_saved: int,
        output_files: dict[str, Path],
    ) -> None:
        self.files_scanned = files_scanned
        self.raw_studies_read = raw_studies_read
        self.valid_studies_parsed = valid_studies_parsed
        self.distinct_trials_saved = distinct_trials_saved
        self.conditions_saved = conditions_saved
        self.interventions_saved = interventions_saved
        self.output_files = output_files

    def log_summary(self) -> None:
        """Output formatted run statistics to logger."""
        logger.info("=" * 70)
        logger.info("Silver Transformation Summary:")
        logger.info("  Bronze Files Processed:     %d", self.files_scanned)
        logger.info("  Raw Studies Read:           %d", self.raw_studies_read)
        logger.info("  Valid Studies Parsed:       %d", self.valid_studies_parsed)
        logger.info("  Distinct Trials (Deduped):  %d", self.distinct_trials_saved)
        logger.info("  Conditions Bridge Records:  %d", self.conditions_saved)
        logger.info("  Interventions Records:      %d", self.interventions_saved)
        for name, path in self.output_files.items():
            logger.info("  Artifact [%s]: %s", name, path)
        logger.info("=" * 70)


def load_bronze_records(
    bronze_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    """Scan and parse all Bronze JSON files into structured records for DuckDB.

    Args:
        bronze_dir: Path to directory containing Bronze batch JSON files.

    Returns:
        Tuple of (trials_data, conditions_data, interventions_data, files_count, raw_count).
    """
    if not bronze_dir.exists():
        logger.warning("Bronze directory %s does not exist.", bronze_dir)
        return [], [], [], 0, 0

    json_files = sorted(bronze_dir.glob("trials_*.json"))
    if not json_files:
        logger.warning("No Bronze batch JSON files found in %s", bronze_dir)
        return [], [], [], 0, 0

    trials_records: list[dict[str, Any]] = []
    conditions_records: list[dict[str, Any]] = []
    interventions_records: list[dict[str, Any]] = []

    total_raw = 0
    now_utc = datetime.now(timezone.utc).isoformat()

    for file_path in json_files:
        logger.debug("Reading Bronze batch: %s", file_path.name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            logger.error("Failed to read JSON from %s: %s", file_path, exc)
            continue

        raw_studies = payload.get("studies", [])
        total_raw += len(raw_studies)

        for raw_study in raw_studies:
            parsed = parse_raw_study(raw_study, processed_at=now_utc)
            if not parsed:
                continue

            trials_records.append(parsed.trial.model_dump())
            for cond in parsed.conditions:
                conditions_records.append(cond.model_dump())
            for item in parsed.interventions:
                interventions_records.append(item.model_dump())

    return trials_records, conditions_records, interventions_records, len(json_files), total_raw


def run_silver_transformation(
    bronze_dir: Path | None = None,
    silver_dir: Path | None = None,
    config: Settings = settings,
) -> SilverTransformationSummary:
    """Execute Silver Layer transformation and deduplication using DuckDB.

    Reads Bronze JSON files, applies Pydantic validation, runs SQL deduplication
    by `nct_id` (keeping record with latest update date), and exports three
    optimized Parquet tables:
    1. trials.parquet
    2. trial_conditions.parquet
    3. trial_interventions.parquet

    Args:
        bronze_dir: Source Bronze directory (defaults to config.bronze_dir).
        silver_dir: Destination Silver directory (defaults to config.silver_dir).
        config: Application configuration instance.

    Returns:
        SilverTransformationSummary object with run statistics.
    """
    src_bronze = bronze_dir or config.bronze_dir
    target_silver = silver_dir or config.silver_dir
    target_silver.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("Starting Silver Layer Transformation (Bronze -> Silver Parquet)")
    logger.info("Source Bronze: %s", src_bronze)
    logger.info("Target Silver: %s", target_silver)
    logger.info("=" * 70)

    (
        trials_data,
        conditions_data,
        interventions_data,
        files_count,
        raw_count,
    ) = load_bronze_records(src_bronze)

    trials_parquet = target_silver / "trials.parquet"
    conditions_parquet = target_silver / "trial_conditions.parquet"
    interventions_parquet = target_silver / "trial_interventions.parquet"

    outputs = {
        "trials": trials_parquet,
        "trial_conditions": conditions_parquet,
        "trial_interventions": interventions_parquet,
    }

    if not trials_data:
        logger.warning("No valid studies parsed. Output Parquet files will not be created.")
        return SilverTransformationSummary(
            files_scanned=files_count,
            raw_studies_read=raw_count,
            valid_studies_parsed=0,
            distinct_trials_saved=0,
            conditions_saved=0,
            interventions_saved=0,
            output_files=outputs,
        )

    # Initialize in-memory DuckDB connection
    con = duckdb.connect(database=":memory:")

    # 1. Define explicit schemas and insert validated records
    con.execute(
        """
        CREATE TABLE raw_trials (
            nct_id VARCHAR,
            brief_title VARCHAR,
            official_title VARCHAR,
            overall_status VARCHAR,
            study_type VARCHAR,
            phase VARCHAR,
            lead_sponsor_name VARCHAR,
            lead_sponsor_class VARCHAR,
            start_date VARCHAR,
            primary_completion_date VARCHAR,
            completion_date VARCHAR,
            last_update_date VARCHAR,
            enrollment_count BIGINT,
            sex VARCHAR,
            min_age VARCHAR,
            max_age VARCHAR,
            has_results BOOLEAN,
            brief_summary VARCHAR,
            processed_at_utc VARCHAR
        );
        CREATE TABLE raw_conditions (
            nct_id VARCHAR,
            condition VARCHAR
        );
        CREATE TABLE raw_interventions (
            nct_id VARCHAR,
            intervention_type VARCHAR,
            intervention_name VARCHAR,
            description VARCHAR
        );
        """
    )

    trials_rows = [tuple(r.get(c) for c in TRIAL_COLUMNS) for r in trials_data]
    con.executemany(
        f"INSERT INTO raw_trials VALUES ({', '.join(['?'] * len(TRIAL_COLUMNS))})",
        trials_rows,
    )

    if conditions_data:
        cond_rows = [tuple(r.get(c) for c in CONDITION_COLUMNS) for r in conditions_data]
        con.executemany("INSERT INTO raw_conditions VALUES (?, ?)", cond_rows)

    if interventions_data:
        interv_rows = [tuple(r.get(c) for c in INTERVENTION_COLUMNS) for r in interventions_data]
        con.executemany("INSERT INTO raw_interventions VALUES (?, ?, ?, ?)", interv_rows)

    # 2. Window-function SQL deduplication by nct_id:
    # Latest last_update_date wins; fallback to processed_at_utc
    con.execute(
        """
        CREATE TABLE silver_trials AS
        SELECT * EXCLUDE (row_rank)
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY nct_id
                       ORDER BY COALESCE(last_update_date, '1970-01-01') DESC,
                                processed_at_utc DESC
                   ) AS row_rank
            FROM raw_trials
        )
        WHERE row_rank = 1
        ORDER BY nct_id ASC;
        """
    )

    # 3. Deduplicate conditions and keep only for valid distinct trials
    con.execute(
        """
        CREATE TABLE silver_conditions AS
        SELECT DISTINCT c.nct_id, c.condition
        FROM raw_conditions c
        INNER JOIN silver_trials t ON c.nct_id = t.nct_id
        ORDER BY c.nct_id ASC, c.condition ASC;
        """
    )

    # 4. Deduplicate interventions and keep only for valid distinct trials
    con.execute(
        """
        CREATE TABLE silver_interventions AS
        SELECT DISTINCT i.nct_id, i.intervention_type, i.intervention_name, i.description
        FROM raw_interventions i
        INNER JOIN silver_trials t ON i.nct_id = t.nct_id
        ORDER BY i.nct_id ASC, i.intervention_name ASC;
        """
    )

    # Export to Parquet with ZSTD compression
    con.execute(f"COPY silver_trials TO '{trials_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);")
    con.execute(f"COPY silver_conditions TO '{conditions_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);")
    con.execute(f"COPY silver_interventions TO '{interventions_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);")

    # Extract counts
    distinct_trials_count: int = con.execute("SELECT COUNT(*) FROM silver_trials").fetchone()[0]  # type: ignore[index]
    conditions_count: int = con.execute("SELECT COUNT(*) FROM silver_conditions").fetchone()[0]  # type: ignore[index]
    interventions_count: int = con.execute("SELECT COUNT(*) FROM silver_interventions").fetchone()[0]  # type: ignore[index]

    con.close()

    summary = SilverTransformationSummary(
        files_scanned=files_count,
        raw_studies_read=raw_count,
        valid_studies_parsed=len(trials_data),
        distinct_trials_saved=distinct_trials_count,
        conditions_saved=conditions_count,
        interventions_saved=interventions_count,
        output_files=outputs,
    )
    summary.log_summary()
    return summary


def main() -> None:
    """CLI entrypoint for executing Silver layer transformation."""
    parser = argparse.ArgumentParser(
        description="Transform Bronze raw ClinicalTrials JSON files into cleaned Parquet Silver tables.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--bronze-dir",
        type=Path,
        default=settings.bronze_dir,
        help="Source directory containing Bronze batch JSON files.",
    )
    parser.add_argument(
        "--silver-dir",
        type=Path,
        default=settings.silver_dir,
        help="Destination directory for Silver Parquet tables.",
    )

    args = parser.parse_args()
    run_silver_transformation(bronze_dir=args.bronze_dir, silver_dir=args.silver_dir)


if __name__ == "__main__":
    main()
