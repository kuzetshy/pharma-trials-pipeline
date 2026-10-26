"""Unit and integration tests for Data Quality assertions and validation gates."""

from pathlib import Path

import duckdb
import pytest

from src.utils.quality import (
    DataQualityValidator,
    validate_gold_layer,
    validate_silver_layer,
)


@pytest.fixture
def validator() -> DataQualityValidator:
    """Fixture providing an isolated DataQualityValidator instance."""
    v = DataQualityValidator()
    yield v
    v.close()


def test_check_primary_key_duplicates(tmp_path: Path, validator: DataQualityValidator) -> None:
    """Verify primary key assertion detects duplicate keys."""
    table_path = tmp_path / "dup_table.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT 'NCT001' AS nct_id, 'Study 1' AS title
            UNION ALL
            SELECT 'NCT001' AS nct_id, 'Study 1 Duplicate' AS title
        ) TO '{table_path.as_posix()}' (FORMAT PARQUET);
        """
    )
    con.close()

    result = validator.check_primary_key(table_path, "nct_id")
    assert result.passed is False
    assert "duplicates found" in result.details


def test_check_primary_key_nulls(tmp_path: Path, validator: DataQualityValidator) -> None:
    """Verify primary key assertion detects NULL values in PK column."""
    table_path = tmp_path / "null_pk.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT 'NCT001' AS nct_id
            UNION ALL
            SELECT NULL::VARCHAR AS nct_id
        ) TO '{table_path.as_posix()}' (FORMAT PARQUET);
        """
    )
    con.close()

    result = validator.check_primary_key(table_path, "nct_id")
    assert result.passed is False
    assert "nulls" in result.details


def test_check_referential_integrity_orphans(tmp_path: Path, validator: DataQualityValidator) -> None:
    """Verify referential integrity assertion detects orphaned foreign keys."""
    parent_path = tmp_path / "parent.parquet"
    child_path = tmp_path / "child.parquet"
    con = duckdb.connect()

    con.execute(
        f"COPY (SELECT 'NCT001' AS nct_id) TO '{parent_path.as_posix()}' (FORMAT PARQUET);"
    )
    con.execute(
        f"""
        COPY (
            SELECT 'NCT001' AS nct_id, 'Condition A' AS cond
            UNION ALL
            SELECT 'NCT999' AS nct_id, 'Orphaned Condition' AS cond
        ) TO '{child_path.as_posix()}' (FORMAT PARQUET);
        """
    )
    con.close()

    result = validator.check_referential_integrity(child_path, parent_path, "nct_id")
    assert result.passed is False
    assert "orphaned records" in result.details


def test_check_percentage_bounds(tmp_path: Path, validator: DataQualityValidator) -> None:
    """Verify percentage bounds assertion catches numbers outside [0.0, 100.0]."""
    table_path = tmp_path / "percentages.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT 50.0 AS pct
            UNION ALL
            SELECT 105.5 AS pct
        ) TO '{table_path.as_posix()}' (FORMAT PARQUET);
        """
    )
    con.close()

    result = validator.check_percentage_bounds(table_path, "pct")
    assert result.passed is False
    assert "outside [0.0, 100.0]" in result.details


def test_check_non_negative(tmp_path: Path, validator: DataQualityValidator) -> None:
    """Verify non-negative check catches negative numbers."""
    table_path = tmp_path / "metrics.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT 100 AS count_metric, -5 AS bad_metric
        ) TO '{table_path.as_posix()}' (FORMAT PARQUET);
        """
    )
    con.close()

    result = validator.check_non_negative(table_path, ["count_metric", "bad_metric"])
    assert result.passed is False
    assert "Negative values detected" in result.details


def test_validate_silver_and_gold_layers_on_real_data() -> None:
    """Verify that current project Silver and Gold artifacts pass all Quality Gates."""
    silver_dir = Path("data/silver")
    gold_dir = Path("data/gold")

    if (silver_dir / "trials.parquet").exists():
        silver_report = validate_silver_layer(silver_dir, raise_on_error=True)
        assert silver_report.is_success is True
        assert silver_report.failed_checks == 0

    if (gold_dir / "mart_sponsor_benchmarks.parquet").exists():
        gold_report = validate_gold_layer(gold_dir, raise_on_error=True)
        assert gold_report.is_success is True
        assert gold_report.failed_checks == 0
