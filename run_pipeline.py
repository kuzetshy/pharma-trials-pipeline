"""Central Pipeline Orchestrator.

Orchestrates end-to-end Medallion execution:
Bronze Ingestion -> Silver Transformation -> Silver Quality Gate ->
Gold Aggregation -> Gold Quality Gate.

Usage:
  # Run entire end-to-end pipeline
  python run_pipeline.py

  # Run pipeline using existing Bronze files (skip network API calls)
  python run_pipeline.py --skip-bronze

  # Run for a specific disease condition and limit batches
  python run_pipeline.py --condition "Lung Cancer" --max-batches 2

  # Run only quality gates
  python run_pipeline.py --stage quality
"""

import argparse
import sys
import time
from typing import Any

from src.ingestion.fetch_trials import run_ingestion
from src.transformation.gold import run_gold_transformation
from src.transformation.silver import run_silver_transformation
from src.utils.config import Settings, settings
from src.utils.logger import setup_logger
from src.utils.quality import validate_gold_layer, validate_silver_layer

logger = setup_logger("pharma_orchestrator")


def run_full_pipeline(
    condition: str | None = None,
    max_batches: int | None = None,
    page_size: int | None = None,
    stage: str = "all",
    skip_bronze: bool = False,
    skip_quality: bool = False,
    config: Settings = settings,
) -> bool:
    """Execute pipeline stages according to requested configuration.

    Args:
        condition: Therapeutic condition to ingest.
        max_batches: Number of API batch pages to fetch.
        page_size: Records per page.
        stage: Specific stage to run ('all', 'bronze', 'silver', 'gold', 'quality').
        skip_bronze: Skip Bronze API ingestion and use existing disk files.
        skip_quality: Skip data quality assertions.
        config: Central settings instance.

    Returns:
        True if all executed stages passed without error, False otherwise.
    """
    config.ensure_directories()
    pipeline_start_time = time.time()

    logger.info("=" * 75)
    logger.info(">>> PharmaInsight ELT & Analytics Pipeline Orchestrator <<<")
    logger.info("Stage Target:   %s", stage.upper())
    logger.info("Search Query:   '%s'", condition or config.search_condition)
    logger.info("Bronze Dir:     %s", config.bronze_dir)
    logger.info("Silver Dir:     %s", config.silver_dir)
    logger.info("Gold Dir:       %s", config.gold_dir)
    logger.info("=" * 75)

    stats: dict[str, Any] = {}

    try:
        # --- STAGE 1: BRONZE INGESTION ---
        if stage in ("all", "bronze") and not skip_bronze:
            t0 = time.time()
            logger.info("\n[STAGE 1/3] Ingesting Bronze Layer (API -> JSON)...")
            bronze_files = run_ingestion(
                condition=condition,
                page_size=page_size,
                max_batches=max_batches,
                bronze_dir=config.bronze_dir,
                config=config,
            )
            stats["bronze_time"] = time.time() - t0
            stats["bronze_files"] = len(bronze_files)
            logger.info("Stage 1 Completed: %d batches saved in %.2fs", len(bronze_files), stats["bronze_time"])
        elif skip_bronze:
            logger.info("\n[STAGE 1/3] Bronze Layer: SKIPPED (--skip-bronze requested)")

        # --- STAGE 2: SILVER TRANSFORMATION ---
        if stage in ("all", "silver"):
            t0 = time.time()
            logger.info("\n[STAGE 2/3] Transforming Silver Layer (Pydantic + DuckDB -> Parquet)...")
            silver_summary = run_silver_transformation(
                bronze_dir=config.bronze_dir,
                silver_dir=config.silver_dir,
                config=config,
            )
            stats["silver_time"] = time.time() - t0
            stats["silver_trials"] = silver_summary.distinct_trials_saved
            logger.info(
                "Stage 2 Completed: %d distinct trials saved in %.2fs",
                silver_summary.distinct_trials_saved,
                stats["silver_time"],
            )

            # Silver Quality Gate
            if not skip_quality:
                logger.info("\n[QUALITY GATE 1/2] Validating Silver Layer integrity...")
                tq = time.time()
                silver_report = validate_silver_layer(config.silver_dir, raise_on_error=True)
                stats["silver_quality_time"] = time.time() - tq
                logger.info(
                    "Silver Quality Gate Passed: %d/%d checks passed in %.2fs",
                    silver_report.passed_checks,
                    silver_report.total_checks,
                    stats["silver_quality_time"],
                )

        # --- STAGE 3: GOLD AGGREGATION ---
        if stage in ("all", "gold"):
            t0 = time.time()
            logger.info("\n[STAGE 3/3] Aggregating Gold Layer (DuckDB Marts -> Parquet)...")
            gold_summary = run_gold_transformation(
                silver_dir=config.silver_dir,
                gold_dir=config.gold_dir,
                config=config,
            )
            stats["gold_time"] = time.time() - t0
            stats["gold_sponsors"] = gold_summary.sponsors_aggregated
            stats["gold_drugs"] = gold_summary.drugs_aggregated
            logger.info(
                "Stage 3 Completed: %d sponsors, %d drugs aggregated in %.2fs",
                gold_summary.sponsors_aggregated,
                gold_summary.drugs_aggregated,
                stats["gold_time"],
            )

            # Gold Quality Gate
            if not skip_quality:
                logger.info("\n[QUALITY GATE 2/2] Validating Gold Layer integrity...")
                tq = time.time()
                gold_report = validate_gold_layer(config.gold_dir, raise_on_error=True)
                stats["gold_quality_time"] = time.time() - tq
                logger.info(
                    "Gold Quality Gate Passed: %d/%d checks passed in %.2fs",
                    gold_report.passed_checks,
                    gold_report.total_checks,
                    stats["gold_quality_time"],
                )

        # Standalone Quality Stage
        if stage == "quality":
            logger.info("\n[STANDALONE QUALITY AUDIT]")
            validate_silver_layer(config.silver_dir, raise_on_error=True)
            validate_gold_layer(config.gold_dir, raise_on_error=True)

        total_elapsed = time.time() - pipeline_start_time
        logger.info("\n" + "=" * 75)
        logger.info(">>> SUCCESS: Pipeline Execution Completed in %.2f seconds <<<", total_elapsed)
        if "silver_trials" in stats:
            logger.info("  Total Cleaned Studies:   %d", stats["silver_trials"])
        if "gold_sponsors" in stats:
            logger.info("  Benchmarked Sponsors:    %d", stats["gold_sponsors"])
        if "gold_drugs" in stats:
            logger.info("  Interventions Analyzed:  %d", stats["gold_drugs"])
        logger.info("=" * 75)
        return True

    except Exception as exc:
        total_elapsed = time.time() - pipeline_start_time
        logger.error("\n" + "!" * 75)
        logger.error(">>> PIPELINE FAILED after %.2fs with error: %s <<<", total_elapsed, exc)
        logger.error("!" * 75)
        return False


def main() -> None:
    """CLI entrypoint for running the pipeline orchestrator."""
    parser = argparse.ArgumentParser(
        description="PharmaInsight Clinical Trials End-to-End ELT Pipeline Orchestrator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--condition",
        type=str,
        default=settings.search_condition,
        help="Medical condition or therapeutic area query.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=settings.max_batches,
        help="Maximum API batch pages to ingest (omit or 0 for unlimited).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=settings.page_size,
        help="Records per API page (max 1000).",
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["all", "bronze", "silver", "gold", "quality"],
        default="all",
        help="Target stage of the pipeline to run.",
    )
    parser.add_argument(
        "--skip-bronze",
        action="store_true",
        help="Skip Bronze API ingestion and use existing Bronze batch files on disk.",
    )
    parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="Bypass Data Quality validation gates.",
    )

    args = parser.parse_args()
    max_b = None if args.max_batches == 0 else args.max_batches

    success = run_full_pipeline(
        condition=args.condition,
        max_batches=max_b,
        page_size=args.page_size,
        stage=args.stage,
        skip_bronze=args.skip_bronze,
        skip_quality=args.skip_quality,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
