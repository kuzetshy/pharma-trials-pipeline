"""Data access layer for querying Silver and Gold Parquet layers via DuckDB."""

from typing import Any

import duckdb

from src.utils.config import Settings, settings


class DataService:
    """Service for querying Parquet files via DuckDB OLAP engine."""

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    def _get_con(self) -> duckdb.DuckDBPyConnection:
        """Create an ephemeral in-memory DuckDB connection."""
        return duckdb.connect(database=":memory:")

    def _fetch_dicts(self, con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
        """Execute query and convert results to dictionaries without pandas/numpy dependency."""
        cursor = con.execute(sql)
        if not cursor.description:
            return []
        cols = [col[0] for col in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # --- GOLD MARTS ---

    def get_sponsor_benchmarks(
        self,
        limit: int = 50,
        offset: int = 0,
        min_trials: int = 1,
        sponsor_class: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query mart_sponsor_benchmarks.parquet with filtering and pagination."""
        mart_path = self.config.gold_dir / "mart_sponsor_benchmarks.parquet"
        if not mart_path.exists():
            return [], 0

        con = self._get_con()
        clauses = [f"total_trials >= {int(min_trials)}"]
        if sponsor_class:
            clean_class = sponsor_class.replace("'", "''")
            clauses.append(f"lead_sponsor_class = '{clean_class}'")
        where_clause = f"WHERE {' AND '.join(clauses)}"

        total_sql = f"SELECT COUNT(*) FROM '{mart_path.as_posix()}' {where_clause}"
        total = con.execute(total_sql).fetchone()[0]  # type: ignore[index]

        data_sql = f"""
        SELECT *
        FROM '{mart_path.as_posix()}'
        {where_clause}
        ORDER BY total_trials DESC, total_enrolled_patients DESC NULLS LAST
        LIMIT {int(limit)} OFFSET {int(offset)}
        """
        rows = self._fetch_dicts(con, data_sql)
        return rows, total

    def get_drug_landscape(
        self,
        limit: int = 50,
        offset: int = 0,
        intervention_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query mart_drug_landscape.parquet with filtering and pagination."""
        mart_path = self.config.gold_dir / "mart_drug_landscape.parquet"
        if not mart_path.exists():
            return [], 0

        con = self._get_con()
        clauses = []
        if intervention_type:
            clean_type = intervention_type.replace("'", "''")
            clauses.append(f"intervention_type = '{clean_type}'")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total_sql = f"SELECT COUNT(*) FROM '{mart_path.as_posix()}' {where_clause}"
        total = con.execute(total_sql).fetchone()[0]  # type: ignore[index]

        data_sql = f"""
        SELECT *
        FROM '{mart_path.as_posix()}'
        {where_clause}
        ORDER BY total_trials_count DESC, total_patient_reach DESC NULLS LAST
        LIMIT {int(limit)} OFFSET {int(offset)}
        """
        rows = self._fetch_dicts(con, data_sql)
        return rows, total

    def get_timeline(
        self,
        start_year: int | None = None,
        study_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query mart_trials_timeline.parquet ordered by start_year."""
        mart_path = self.config.gold_dir / "mart_trials_timeline.parquet"
        if not mart_path.exists():
            return []

        con = self._get_con()
        clauses = []
        if start_year is not None:
            clauses.append(f"start_year >= {int(start_year)}")
        if study_type:
            clean_type = study_type.replace("'", "''")
            clauses.append(f"study_type = '{clean_type}'")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        data_sql = f"""
        SELECT *
        FROM '{mart_path.as_posix()}'
        {where_clause}
        ORDER BY start_year ASC NULLS LAST
        """
        return self._fetch_dicts(con, data_sql)

    # --- SILVER ENTITIES ---

    def get_trials(
        self,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        phase: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query cleaned trials from Silver layer with search and filters."""
        trials_path = self.config.silver_dir / "trials.parquet"
        if not trials_path.exists():
            return [], 0

        con = self._get_con()
        clauses = []
        if search:
            escaped = search.replace("'", "''")
            clauses.append(
                f"(lower(brief_title) LIKE lower('%{escaped}%') OR lower(nct_id) LIKE lower('%{escaped}%'))"
            )
        if phase:
            clean_phase = phase.replace("'", "''")
            clauses.append(f"phase = '{clean_phase}'")
        if status:
            clean_status = status.replace("'", "''")
            clauses.append(f"overall_status = '{clean_status}'")

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total_sql = f"SELECT COUNT(*) FROM '{trials_path.as_posix()}' {where_clause}"
        total = con.execute(total_sql).fetchone()[0]  # type: ignore[index]

        data_sql = f"""
        SELECT
            nct_id,
            brief_title,
            overall_status,
            phase,
            lead_sponsor_name,
            start_date,
            enrollment_count
        FROM '{trials_path.as_posix()}'
        {where_clause}
        ORDER BY start_date DESC NULLS LAST, nct_id ASC
        LIMIT {int(limit)} OFFSET {int(offset)}
        """
        rows = self._fetch_dicts(con, data_sql)
        return rows, total

    def get_trial_detail(self, nct_id: str) -> dict[str, Any] | None:
        """Fetch complete trial record including conditions and interventions."""
        trials_path = self.config.silver_dir / "trials.parquet"
        conditions_path = self.config.silver_dir / "trial_conditions.parquet"
        interventions_path = self.config.silver_dir / "trial_interventions.parquet"

        if not trials_path.exists():
            return None

        con = self._get_con()
        clean_id = nct_id.strip().upper().replace("'", "''")

        trial_sql = f"SELECT * FROM '{trials_path.as_posix()}' WHERE nct_id = '{clean_id}' LIMIT 1"
        trial_records = self._fetch_dicts(con, trial_sql)
        if not trial_records:
            return None

        trial_dict = trial_records[0]

        # Fetch conditions
        conditions: list[str] = []
        if conditions_path.exists():
            cond_sql = f"SELECT condition FROM '{conditions_path.as_posix()}' WHERE nct_id = '{clean_id}'"
            cond_records = self._fetch_dicts(con, cond_sql)
            conditions = [r["condition"] for r in cond_records if "condition" in r]

        # Fetch interventions
        interventions: list[dict[str, Any]] = []
        if interventions_path.exists():
            int_sql = f"""
            SELECT intervention_type, intervention_name, description
            FROM '{interventions_path.as_posix()}'
            WHERE nct_id = '{clean_id}'
            """
            interventions = self._fetch_dicts(con, int_sql)

        trial_dict["conditions"] = conditions
        trial_dict["interventions"] = interventions
        return trial_dict

    def get_system_health(self) -> dict[str, Any]:
        """Check availability of data artifacts across layers."""
        bronze_count = len(list(self.config.bronze_dir.glob("trials_*.json")))
        silver_trials_count = 0
        trials_parquet = self.config.silver_dir / "trials.parquet"
        if trials_parquet.exists():
            con = self._get_con()
            silver_trials_count = con.execute(f"SELECT COUNT(*) FROM '{trials_parquet.as_posix()}'").fetchone()[0]  # type: ignore[index]

        marts = {
            "sponsor_benchmarks": (self.config.gold_dir / "mart_sponsor_benchmarks.parquet").exists(),
            "drug_landscape": (self.config.gold_dir / "mart_drug_landscape.parquet").exists(),
            "trials_timeline": (self.config.gold_dir / "mart_trials_timeline.parquet").exists(),
        }

        return {
            "status": "healthy" if all(marts.values()) else "degraded",
            "version": "1.0.0",
            "marts_available": marts,
            "bronze_files_count": bronze_count,
            "silver_trials_count": int(silver_trials_count),
        }
