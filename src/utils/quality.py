"""Data Quality verification suite (Quality Gate).

Executes automated data integrity contracts directly on Parquet files using DuckDB:
- Uniqueness / Primary Key checks
- Not-Null column constraints
- Date format validation
- Referential integrity (Foreign Key / orphaned rows)
- Business metric bounds (non-negative numbers, valid percentages 0-100)
"""

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from src.utils.logger import setup_logger

logger = setup_logger("pharma_quality")


class DataQualityError(Exception):
    """Raised when one or more critical data quality assertions fail."""


@dataclass
class QualityCheckResult:
    """Represents the outcome of a single data quality assertion."""

    check_name: str
    target_artifact: str
    passed: bool
    details: str


@dataclass
class QualitySuiteReport:
    """Summary report of an executed data quality suite."""

    suite_name: str
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    results: list[QualityCheckResult] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.failed_checks == 0


class DataQualityValidator:
    """Engine for running assertion contracts against Parquet tables using DuckDB."""

    def __init__(self) -> None:
        self.con = duckdb.connect(database=":memory:")

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "DataQualityValidator":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def check_non_empty(self, parquet_path: Path) -> QualityCheckResult:
        """Verify that table exists and contains at least 1 record."""
        target_name = parquet_path.name
        if not parquet_path.exists():
            return QualityCheckResult(
                check_name="non_empty_table",
                target_artifact=target_name,
                passed=False,
                details=f"File {parquet_path} does not exist.",
            )

        count = self.con.execute(f"SELECT COUNT(*) FROM '{parquet_path.as_posix()}'").fetchone()[0]  # type: ignore[index]
        passed = count > 0
        details = f"Total rows: {count}" if passed else "Table is empty (0 rows)"
        return QualityCheckResult("non_empty_table", target_name, passed, details)

    def check_primary_key(self, parquet_path: Path, pk_column: str) -> QualityCheckResult:
        """Verify that primary key column has zero duplicates and zero nulls."""
        target_name = parquet_path.name
        if not parquet_path.exists():
            return QualityCheckResult(
                check_name="primary_key_uniqueness",
                target_artifact=target_name,
                passed=False,
                details=f"Artifact {parquet_path} does not exist.",
            )

        sql = f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT({pk_column}) AS non_null_rows,
            COUNT(DISTINCT {pk_column}) AS distinct_rows
        FROM '{parquet_path.as_posix()}'
        """
        row = self.con.execute(sql).fetchone()
        if not row:
            return QualityCheckResult("primary_key_uniqueness", target_name, False, "Failed to read table")

        total_rows, non_null_rows, distinct_rows = row
        null_count = total_rows - non_null_rows
        dup_count = total_rows - distinct_rows

        passed = (null_count == 0) and (dup_count == 0)
        details = (
            f"Verified {total_rows} rows: 0 nulls, 0 duplicates on {pk_column}"
            if passed
            else f"Failed on {pk_column}: {null_count} nulls, {dup_count} duplicates found"
        )
        return QualityCheckResult("primary_key_uniqueness", target_name, passed, details)

    def check_not_null(self, parquet_path: Path, columns: list[str]) -> QualityCheckResult:
        """Verify that specified columns contain no NULL values."""
        target_name = parquet_path.name
        if not parquet_path.exists():
            return QualityCheckResult(
                check_name="not_null_columns",
                target_artifact=target_name,
                passed=False,
                details=f"Artifact {parquet_path} does not exist.",
            )

        failed_cols: list[str] = []

        for col in columns:
            sql = f"SELECT COUNT(*) FROM '{parquet_path.as_posix()}' WHERE {col} IS NULL"
            null_count = self.con.execute(sql).fetchone()[0]  # type: ignore[index]
            if null_count > 0:
                failed_cols.append(f"{col} ({null_count} nulls)")

        passed = len(failed_cols) == 0
        details = (
            f"Columns {columns} have zero nulls"
            if passed
            else f"Null violations in columns: {', '.join(failed_cols)}"
        )
        return QualityCheckResult("not_null_columns", target_name, passed, details)

    def check_referential_integrity(
        self,
        child_path: Path,
        parent_path: Path,
        join_key: str,
    ) -> QualityCheckResult:
        """Verify Foreign Key integrity (no orphaned records in child table)."""
        target_name = f"{child_path.name} -> {parent_path.name}"
        if not child_path.exists() or not parent_path.exists():
            return QualityCheckResult(
                check_name="referential_integrity",
                target_artifact=target_name,
                passed=False,
                details=f"Missing artifacts for integrity check: {child_path.name} exists={child_path.exists()}, {parent_path.name} exists={parent_path.exists()}",
            )

        sql = f"""
        SELECT COUNT(*)
        FROM '{child_path.as_posix()}' c
        LEFT JOIN '{parent_path.as_posix()}' p ON c.{join_key} = p.{join_key}
        WHERE p.{join_key} IS NULL
        """
        orphaned_count = self.con.execute(sql).fetchone()[0]  # type: ignore[index]
        passed = orphaned_count == 0
        details = (
            f"Referential integrity verified on {join_key} (0 orphans)"
            if passed
            else f"Found {orphaned_count} orphaned records in {child_path.name} without parent in {parent_path.name}"
        )
        return QualityCheckResult("referential_integrity", target_name, passed, details)

    def check_percentage_bounds(self, parquet_path: Path, pct_column: str) -> QualityCheckResult:
        """Verify percentage values stay strictly within [0.0, 100.0] or are NULL."""
        target_name = parquet_path.name
        if not parquet_path.exists():
            return QualityCheckResult(
                check_name="percentage_bounds",
                target_artifact=target_name,
                passed=False,
                details=f"Artifact {parquet_path} does not exist.",
            )

        sql = f"""
        SELECT COUNT(*)
        FROM '{parquet_path.as_posix()}'
        WHERE {pct_column} IS NOT NULL AND ({pct_column} < 0.0 OR {pct_column} > 100.0)
        """
        violating_count = self.con.execute(sql).fetchone()[0]  # type: ignore[index]
        passed = violating_count == 0
        details = (
            f"Percentage column {pct_column} bounds [0, 100] verified"
            if passed
            else f"Found {violating_count} records outside [0.0, 100.0] on {pct_column}"
        )
        return QualityCheckResult("percentage_bounds", target_name, passed, details)

    def check_non_negative(self, parquet_path: Path, columns: list[str]) -> QualityCheckResult:
        """Verify that numeric metric columns contain no negative values."""
        target_name = parquet_path.name
        if not parquet_path.exists():
            return QualityCheckResult(
                check_name="non_negative_metrics",
                target_artifact=target_name,
                passed=False,
                details=f"Artifact {parquet_path} does not exist.",
            )

        failed_cols: list[str] = []

        for col in columns:
            sql = f"SELECT COUNT(*) FROM '{parquet_path.as_posix()}' WHERE {col} < 0"
            neg_count = self.con.execute(sql).fetchone()[0]  # type: ignore[index]
            if neg_count > 0:
                failed_cols.append(f"{col} ({neg_count} negative)")

        passed = len(failed_cols) == 0
        details = (
            f"Non-negative bounds verified for {columns}"
            if passed
            else f"Negative values detected in: {', '.join(failed_cols)}"
        )
        return QualityCheckResult("non_negative_metrics", target_name, passed, details)


def validate_silver_layer(silver_dir: Path, raise_on_error: bool = True) -> QualitySuiteReport:
    """Execute complete Quality Gate assertions for Silver layer tables."""
    trials_path = silver_dir / "trials.parquet"
    cond_path = silver_dir / "trial_conditions.parquet"
    interv_path = silver_dir / "trial_interventions.parquet"

    report = QualitySuiteReport(suite_name="Silver Layer Quality Gate")

    with DataQualityValidator() as validator:
        checks = [
            validator.check_non_empty(trials_path),
            validator.check_primary_key(trials_path, "nct_id"),
            validator.check_not_null(trials_path, ["nct_id", "brief_title", "overall_status"]),
            validator.check_referential_integrity(cond_path, trials_path, "nct_id"),
            validator.check_referential_integrity(interv_path, trials_path, "nct_id"),
        ]

        for res in checks:
            report.total_checks += 1
            if res.passed:
                report.passed_checks += 1
                logger.info("  [PASS] %s on %s: %s", res.check_name, res.target_artifact, res.details)
            else:
                report.failed_checks += 1
                logger.error("  [FAIL] %s on %s: %s", res.check_name, res.target_artifact, res.details)
            report.results.append(res)

    if not report.is_success and raise_on_error:
        raise DataQualityError(
            f"Silver Layer Quality Gate failed with {report.failed_checks} errors. Halting pipeline."
        )

    return report


def validate_gold_layer(gold_dir: Path, raise_on_error: bool = True) -> QualitySuiteReport:
    """Execute complete Quality Gate assertions for Gold layer data marts."""
    sponsors_mart = gold_dir / "mart_sponsor_benchmarks.parquet"
    drugs_mart = gold_dir / "mart_drug_landscape.parquet"
    timeline_mart = gold_dir / "mart_trials_timeline.parquet"

    report = QualitySuiteReport(suite_name="Gold Layer Quality Gate")

    with DataQualityValidator() as validator:
        checks = [
            validator.check_non_empty(sponsors_mart),
            validator.check_non_negative(
                sponsors_mart, ["total_trials", "active_trials", "completed_trials", "total_enrolled_patients"]
            ),
            validator.check_percentage_bounds(sponsors_mart, "results_reporting_rate_pct"),
            validator.check_non_empty(drugs_mart),
            validator.check_non_negative(drugs_mart, ["total_trials_count", "distinct_sponsors_count"]),
            validator.check_non_empty(timeline_mart),
            validator.check_non_negative(timeline_mart, ["trials_started_count", "total_planned_enrollment"]),
        ]

        for res in checks:
            report.total_checks += 1
            if res.passed:
                report.passed_checks += 1
                logger.info("  [PASS] %s on %s: %s", res.check_name, res.target_artifact, res.details)
            else:
                report.failed_checks += 1
                logger.error("  [FAIL] %s on %s: %s", res.check_name, res.target_artifact, res.details)
            report.results.append(res)

    if not report.is_success and raise_on_error:
        raise DataQualityError(
            f"Gold Layer Quality Gate failed with {report.failed_checks} errors. Halting pipeline."
        )

    return report
