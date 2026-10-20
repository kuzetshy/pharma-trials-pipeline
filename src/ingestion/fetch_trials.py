"""Bronze Layer Ingestion: ClinicalTrials.gov API v2 client.

Fetches raw clinical trials data with pagination, exponential backoff retries,
rate limiting, and stores raw JSON batches in data/bronze/.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import httpx

from src.utils.config import Settings, settings
from src.utils.logger import setup_logger

logger = setup_logger("pharma_ingestion")


class ClinicalTrialsAPIError(Exception):
    """Raised when ClinicalTrials API fails after retries or encounters non-retryable errors."""


class ClinicalTrialsClient:
    """HTTP client for ClinicalTrials.gov API v2 with retry and rate-limiting support."""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.client = httpx.Client(
            timeout=config.request_timeout_seconds,
            headers={
                "Accept": "application/json",
                "User-Agent": "PharmaInsight-ELT-Pipeline/1.0",
            },
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self.client.close()

    def __enter__(self) -> "ClinicalTrialsClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def fetch_page(
        self,
        condition: str,
        page_size: int,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a single page of clinical trials with exponential backoff retry.

        Args:
            condition: Disease or therapeutic condition query (e.g., 'Breast Cancer').
            page_size: Number of records per page (up to 1000).
            page_token: Pagination token for the next page if available.

        Returns:
            Dictionary containing the raw API response (including 'studies' and 'nextPageToken').

        Raises:
            ClinicalTrialsAPIError: If all retry attempts fail or a fatal HTTP error occurs.
        """
        params: dict[str, Any] = {
            "query.cond": condition,
            "pageSize": page_size,
        }
        if page_token:
            params["pageToken"] = page_token

        attempts = 0
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                logger.debug(
                    "Requesting %s (attempt %d/%d, page_token=%s)",
                    self.config.api_base_url,
                    attempts,
                    self.config.max_retries + 1,
                    page_token,
                )

                response = self.client.get(self.config.api_base_url, params=params)

                # Check for rate limiting or server errors that warrant a retry
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_seconds = float(retry_after)
                    else:
                        sleep_seconds = self.config.backoff_factor * (2 ** (attempts - 1))

                    if attempts <= self.config.max_retries:
                        logger.warning(
                            "Received status %d from API. Retrying in %.2f seconds (attempt %d/%d)...",
                            response.status_code,
                            sleep_seconds,
                            attempts,
                            self.config.max_retries,
                        )
                        time.sleep(sleep_seconds)
                        continue
                    else:
                        raise ClinicalTrialsAPIError(
                            f"API failed with status {response.status_code} after {attempts} attempts. "
                            f"Response: {response.text[:200]}"
                        )

                # Non-retryable client errors (400, 401, 403, 404, etc.)
                response.raise_for_status()

                # Polite rate-limiting delay between successful calls
                if self.config.rate_limit_delay > 0:
                    time.sleep(self.config.rate_limit_delay)

                return response.json()

            except (httpx.TransportError, httpx.TimeoutException) as exc:
                sleep_seconds = self.config.backoff_factor * (2 ** (attempts - 1))
                if attempts <= self.config.max_retries:
                    logger.warning(
                        "Network/timeout error (%s: %s). Retrying in %.2f seconds (attempt %d/%d)...",
                        type(exc).__name__,
                        str(exc),
                        sleep_seconds,
                        attempts,
                        self.config.max_retries,
                    )
                    time.sleep(sleep_seconds)
                else:
                    raise ClinicalTrialsAPIError(
                        f"Network error after {attempts} attempts: {exc}"
                    ) from exc

        raise ClinicalTrialsAPIError(f"Failed to fetch data after {self.config.max_retries + 1} attempts")


def save_bronze_batch(
    studies: list[dict[str, Any]],
    batch_index: int,
    output_dir: Path,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Save a single raw batch of studies to the Bronze storage layer as JSON.

    File naming format: trials_YYYYMMDD_batch_XX.json

    Args:
        studies: List of raw study dictionaries from API.
        batch_index: 1-based sequential batch number.
        output_dir: Directory to save the bronze file.
        metadata: Optional ingestion metadata (timestamp, query condition, tokens).

    Returns:
        Path to the saved JSON batch file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"trials_{date_str}_batch_{batch_index:02d}.json"
    target_path = output_dir / filename

    payload = {
        "metadata": metadata or {},
        "studies": studies,
    }

    # Write to temp file first, then atomically rename to prevent partial writes
    temp_path = target_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    temp_path.replace(target_path)

    logger.info(
        "Saved batch %02d with %d studies to %s",
        batch_index,
        len(studies),
        target_path,
    )
    return target_path


def run_ingestion(
    condition: str | None = None,
    page_size: int | None = None,
    max_batches: int | None = None,
    bronze_dir: Path | None = None,
    config: Settings = settings,
) -> list[Path]:
    """Execute the Bronze layer ingestion pipeline.

    Paginates through ClinicalTrials.gov API v2, fetches study records,
    and writes raw batches to disk.

    Args:
        condition: Therapeutic condition query (defaults to config.search_condition).
        page_size: Records per page (defaults to config.page_size).
        max_batches: Max batches to fetch (defaults to config.max_batches).
        bronze_dir: Target Bronze directory (defaults to config.bronze_dir).
        config: Application settings instance.

    Returns:
        List of paths to generated bronze JSON files.
    """
    target_condition = condition or config.search_condition
    target_page_size = page_size or config.page_size
    target_max_batches = max_batches if max_batches is not None else config.max_batches
    target_bronze_dir = bronze_dir or config.bronze_dir

    logger.info("=" * 70)
    logger.info("Starting Bronze Layer Ingestion (ClinicalTrials.gov API v2)")
    logger.info("Condition: '%s'", target_condition)
    logger.info("Page Size: %d", target_page_size)
    logger.info(
        "Max Batches: %s",
        target_max_batches if target_max_batches is not None else "Unlimited",
    )
    logger.info("Destination: %s", target_bronze_dir)
    logger.info("=" * 70)

    start_time = time.time()
    next_page_token: str | None = None
    batch_index = 0
    total_studies_collected = 0
    saved_files: list[Path] = []

    with ClinicalTrialsClient(config=config) as client:
        while True:
            batch_index += 1
            if target_max_batches is not None and batch_index > target_max_batches:
                logger.info("Reached maximum requested batches limit (%d). Stopping.", target_max_batches)
                break

            logger.info("Fetching batch %02d...", batch_index)
            data = client.fetch_page(
                condition=target_condition,
                page_size=target_page_size,
                page_token=next_page_token,
            )

            studies = data.get("studies", [])
            current_token = next_page_token
            next_page_token = data.get("nextPageToken")

            if not studies:
                logger.info("No more studies returned by API. Ingestion complete.")
                break

            total_studies_collected += len(studies)

            metadata = {
                "batch_index": batch_index,
                "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
                "search_condition": target_condition,
                "page_size": target_page_size,
                "studies_in_batch": len(studies),
                "request_token": current_token,
                "next_page_token": next_page_token,
            }

            saved_path = save_bronze_batch(
                studies=studies,
                batch_index=batch_index,
                output_dir=target_bronze_dir,
                metadata=metadata,
            )
            saved_files.append(saved_path)

            if not next_page_token:
                logger.info("Reached end of available records (no nextPageToken).")
                break

    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info(
        "Bronze Ingestion Finished: %d batches, %d total studies saved in %.2f seconds.",
        len(saved_files),
        total_studies_collected,
        elapsed,
    )
    logger.info("=" * 70)

    return saved_files


def main() -> None:
    """CLI entrypoint for running ingestion directly."""
    parser = argparse.ArgumentParser(
        description="Ingest clinical trials data from ClinicalTrials.gov API v2 to Bronze layer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--condition",
        type=str,
        default=settings.search_condition,
        help="Medical condition or disease to query.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=settings.page_size,
        help="Number of records per page (max 1000).",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=settings.max_batches,
        help="Maximum number of batches to ingest (omit or pass 0 for unlimited).",
    )
    parser.add_argument(
        "--bronze-dir",
        type=Path,
        default=settings.bronze_dir,
        help="Target folder for raw JSON batch files.",
    )

    args = parser.parse_args()
    max_b = None if args.max_batches == 0 else args.max_batches

    run_ingestion(
        condition=args.condition,
        page_size=args.page_size,
        max_batches=max_b,
        bronze_dir=args.bronze_dir,
    )


if __name__ == "__main__":
    main()
