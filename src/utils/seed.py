"""Data Seeding Utility for Zero-Friction Cold Start and Cloud Deployments.

Ensures analytical Gold marts and cleansed Silver tables are populated when
the application boots on clean cloud environments (Render, Railway, Fly.io)
or fresh clones where Parquet data files were excluded by .gitignore.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.utils.config import Settings

logger = setup_logger("pharma_seed")

REQUIRED_SILVER_FILES = (
    "trials.parquet",
    "trial_conditions.parquet",
    "trial_interventions.parquet",
)

REQUIRED_GOLD_FILES = (
    "mart_sponsor_benchmarks.parquet",
    "mart_drug_landscape.parquet",
    "mart_trials_timeline.parquet",
)


def seed_data_if_empty(config: "Settings") -> dict[str, int]:
    """Copy pre-baked seed Parquet files to silver and gold directories if missing.

    Parameters
    ----------
    config : Settings
        Application configuration providing seeds_dir, silver_dir, and gold_dir.

    Returns
    -------
    dict[str, int]
        Number of seeded files per layer: {'silver': int, 'gold': int}.
    """
    seeds_dir = Path(config.seeds_dir)
    silver_dir = Path(config.silver_dir)
    gold_dir = Path(config.gold_dir)

    silver_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    seeded_counts = {"silver": 0, "gold": 0}

    # 1. Seed Silver Layer if missing
    seed_silver_source = seeds_dir / "silver"
    if seed_silver_source.exists():
        for filename in REQUIRED_SILVER_FILES:
            target_path = silver_dir / filename
            source_path = seed_silver_source / filename
            if not target_path.exists() and source_path.exists():
                shutil.copy2(source_path, target_path)
                seeded_counts["silver"] += 1
                logger.info("Seeded Silver table '%s' -> %s", filename, target_path)

    # 2. Seed Gold Analytical Marts if missing
    seed_gold_source = seeds_dir / "gold"
    if seed_gold_source.exists():
        for filename in REQUIRED_GOLD_FILES:
            target_path = gold_dir / filename
            source_path = seed_gold_source / filename
            if not target_path.exists() and source_path.exists():
                shutil.copy2(source_path, target_path)
                seeded_counts["gold"] += 1
                logger.info("Seeded Gold analytical mart '%s' -> %s", filename, target_path)

    if seeded_counts["silver"] > 0 or seeded_counts["gold"] > 0:
        logger.info(
            "Bootstrap seed completed: %d silver tables, %d gold marts initialized.",
            seeded_counts["silver"],
            seeded_counts["gold"],
        )

    return seeded_counts
