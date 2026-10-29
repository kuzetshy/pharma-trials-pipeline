"""Unit tests for the bootstrap data seeding utility (Step 9)."""

from pathlib import Path
from unittest.mock import MagicMock

from src.utils.seed import (
    REQUIRED_GOLD_FILES,
    REQUIRED_SILVER_FILES,
    seed_data_if_empty,
)


def test_seed_data_copies_when_target_empty(tmp_path: Path) -> None:
    seeds_dir = tmp_path / "seeds"
    silver_seeds = seeds_dir / "silver"
    gold_seeds = seeds_dir / "gold"
    silver_seeds.mkdir(parents=True)
    gold_seeds.mkdir(parents=True)

    # Create dummy seed files
    for fname in REQUIRED_SILVER_FILES:
        (silver_seeds / fname).write_text(f"dummy content {fname}")
    for fname in REQUIRED_GOLD_FILES:
        (gold_seeds / fname).write_text(f"dummy content {fname}")

    target_silver = tmp_path / "target_silver"
    target_gold = tmp_path / "target_gold"

    mock_config = MagicMock()
    mock_config.seeds_dir = seeds_dir
    mock_config.silver_dir = target_silver
    mock_config.gold_dir = target_gold

    result = seed_data_if_empty(mock_config)

    assert result["silver"] == len(REQUIRED_SILVER_FILES)
    assert result["gold"] == len(REQUIRED_GOLD_FILES)

    # Verify all files exist in target
    for fname in REQUIRED_SILVER_FILES:
        assert (target_silver / fname).exists()
        assert (target_silver / fname).read_text() == f"dummy content {fname}"

    for fname in REQUIRED_GOLD_FILES:
        assert (target_gold / fname).exists()
        assert (target_gold / fname).read_text() == f"dummy content {fname}"


def test_seed_data_does_not_overwrite_existing(tmp_path: Path) -> None:
    seeds_dir = tmp_path / "seeds"
    silver_seeds = seeds_dir / "silver"
    gold_seeds = seeds_dir / "gold"
    silver_seeds.mkdir(parents=True)
    gold_seeds.mkdir(parents=True)

    for fname in REQUIRED_SILVER_FILES:
        (silver_seeds / fname).write_text("seed version")
    for fname in REQUIRED_GOLD_FILES:
        (gold_seeds / fname).write_text("seed version")

    target_silver = tmp_path / "target_silver"
    target_gold = tmp_path / "target_gold"
    target_silver.mkdir()
    target_gold.mkdir()

    # Create pre-existing file in target
    (target_silver / "trials.parquet").write_text("existing custom version")

    mock_config = MagicMock()
    mock_config.seeds_dir = seeds_dir
    mock_config.silver_dir = target_silver
    mock_config.gold_dir = target_gold

    result = seed_data_if_empty(mock_config)

    # Only remaining 2 silver files should be copied
    assert result["silver"] == len(REQUIRED_SILVER_FILES) - 1
    assert result["gold"] == len(REQUIRED_GOLD_FILES)

    # Ensure existing file wasn't overwritten
    assert (target_silver / "trials.parquet").read_text() == "existing custom version"


def test_seed_data_handles_missing_seeds_dir(tmp_path: Path) -> None:
    non_existent_seeds = tmp_path / "does_not_exist"
    target_silver = tmp_path / "target_silver"
    target_gold = tmp_path / "target_gold"

    mock_config = MagicMock()
    mock_config.seeds_dir = non_existent_seeds
    mock_config.silver_dir = target_silver
    mock_config.gold_dir = target_gold

    result = seed_data_if_empty(mock_config)

    assert result["silver"] == 0
    assert result["gold"] == 0
