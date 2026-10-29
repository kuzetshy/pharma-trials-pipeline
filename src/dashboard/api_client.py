"""HTTP Client for communicating with PharmaInsight FastAPI Data-as-a-Service."""

import os
from typing import Any

import httpx


class ApiClientError(Exception):
    """Exception raised for API communication failures."""


def normalize_api_url(url: str | None) -> str:
    """Ensure API URL has a valid protocol and scheme for httpx communication."""
    if not url:
        return "http://localhost:8000"
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        if "onrender.com" in url:
            url = f"https://{url}"
        elif ":" in url or url in ("localhost", "127.0.0.1"):
            url = f"http://{url}"
        else:
            url = f"https://{url}.onrender.com"
    return url


class PharmaApiClient:
    """Synchronous HTTP client for PharmaInsight REST API."""

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 20.0) -> None:
        raw_url = base_url or os.getenv("API_URL", "http://localhost:8000")
        self.base_url = normalize_api_url(raw_url)
        self.timeout_seconds = timeout_seconds

    def _get_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)

    def is_alive(self) -> bool:
        """Check if FastAPI service is responding."""
        try:
            with self._get_client() as client:
                res = client.get("/health")
                return res.status_code == 200
        except Exception:
            return False

    def get_health(self) -> dict[str, Any]:
        """Fetch system and data lake health status."""
        try:
            with self._get_client() as client:
                res = client.get("/health")
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch health check: {exc}") from exc

    def get_quality_status(self) -> dict[str, Any]:
        """Fetch live Data Quality Gate assertion results."""
        try:
            with self._get_client() as client:
                res = client.get("/api/v1/quality/status")
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch quality status: {exc}") from exc

    def get_sponsors(
        self,
        limit: int = 50,
        offset: int = 0,
        min_trials: int = 1,
        sponsor_class: str | None = None,
    ) -> dict[str, Any]:
        """Fetch sponsor benchmarking metrics from Gold mart."""
        params: dict[str, Any] = {"limit": limit, "offset": offset, "min_trials": min_trials}
        if sponsor_class and sponsor_class != "ALL":
            params["sponsor_class"] = sponsor_class

        try:
            with self._get_client() as client:
                res = client.get("/api/v1/marts/sponsors", params=params)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch sponsors mart: {exc}") from exc

    def get_drugs(
        self,
        limit: int = 50,
        offset: int = 0,
        intervention_type: str | None = None,
    ) -> dict[str, Any]:
        """Fetch drug landscape analytics from Gold mart."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if intervention_type and intervention_type != "ALL":
            params["intervention_type"] = intervention_type

        try:
            with self._get_client() as client:
                res = client.get("/api/v1/marts/drugs", params=params)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch drug landscape: {exc}") from exc

    def get_timeline(
        self,
        start_year: int | None = None,
        study_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch clinical trial historical launch timeline."""
        params: dict[str, Any] = {}
        if start_year:
            params["start_year"] = start_year
        if study_type and study_type != "ALL":
            params["study_type"] = study_type

        try:
            with self._get_client() as client:
                res = client.get("/api/v1/marts/timeline", params=params)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch timeline mart: {exc}") from exc

    def get_trials(
        self,
        limit: int = 25,
        offset: int = 0,
        search: str | None = None,
        phase: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Search and filter normalized clinical trials from Silver repository."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search and search.strip():
            params["search"] = search.strip()
        if phase and phase != "ALL":
            params["phase"] = phase
        if status and status != "ALL":
            params["status"] = status

        try:
            with self._get_client() as client:
                res = client.get("/api/v1/trials", params=params)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to search trials: {exc}") from exc

    def get_trial_detail(self, nct_id: str) -> dict[str, Any] | None:
        """Fetch complete trial record including conditions and interventions."""
        try:
            with self._get_client() as client:
                res = client.get(f"/api/v1/trials/{nct_id.strip().upper()}")
                if res.status_code == 404:
                    return None
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Failed to fetch trial '{nct_id}': {exc}") from exc

    def summarize_trial(self, nct_id: str) -> dict[str, Any]:
        """Trigger GenAI clinical protocol summarization for a study."""
        try:
            with self._get_client() as client:
                res = client.post(f"/api/v1/trials/{nct_id.strip().upper()}/summarize")
                res.raise_for_status()
                return res.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ApiClientError(f"Trial '{nct_id}' not found in database.") from exc
            if exc.response.status_code == 502:
                raise ApiClientError(f"GenAI summarization service error: {exc.response.text}") from exc
            raise ApiClientError(f"API returned HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Network error while summarizing '{nct_id}': {exc}") from exc
