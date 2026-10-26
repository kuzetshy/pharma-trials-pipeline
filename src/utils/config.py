"""Application configuration management using Pydantic Settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Clinical Trials ELT & GenAI Pipeline."""

    # API Configuration
    api_base_url: str = Field(
        default="https://clinicaltrials.gov/api/v2/studies",
        description="Base URL for ClinicalTrials.gov API v2 studies endpoint",
    )
    search_condition: str = Field(
        default="Breast Cancer",
        description="Target medical condition/therapeutic area for filtering studies",
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of studies per API page request (max 1000)",
    )
    max_batches: int | None = Field(
        default=3,
        description="Maximum number of batches to ingest (None for all available)",
    )

    # HTTP Client & Ingestion Reliability
    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="HTTP request timeout in seconds",
    )
    max_retries: int = Field(
        default=4,
        ge=0,
        description="Maximum retry attempts on retryable HTTP/network errors",
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=0.0,
        description="Exponential backoff factor for retry delays (seconds: factor * 2^(attempt-1))",
    )
    rate_limit_delay: float = Field(
        default=0.5,
        ge=0.0,
        description="Polite delay between consecutive API requests (in seconds)",
    )

    # Storage Paths
    data_dir: Path = Field(
        default=Path("data"),
        description="Root data directory",
    )
    bronze_dir: Path = Field(
        default=Path("data/bronze"),
        description="Bronze layer directory for raw batch JSON files",
    )
    silver_dir: Path = Field(
        default=Path("data/silver"),
        description="Silver layer directory for cleaned Parquet files",
    )
    gold_dir: Path = Field(
        default=Path("data/gold"),
        description="Gold layer directory for dimensional models and marts",
    )

    # GenAI & LLM Configuration
    llm_provider: str = Field(
        default="mock",
        description="LLM provider: 'mock' (offline testing) or 'gemini' (live API)",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="API key for cloud LLM provider",
    )
    llm_model_name: str = Field(
        default="gemini-1.5-flash",
        description="Target LLM model identifier",
    )


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        """Create storage directories if they do not exist."""
        for path in (self.data_dir, self.bronze_dir, self.silver_dir, self.gold_dir):
            path.mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = Settings()
