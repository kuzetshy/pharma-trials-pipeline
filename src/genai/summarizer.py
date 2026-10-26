"""GenAI clinical trial protocol summarizer service and provider implementations."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from src.genai.schemas import ClinicalSummaryOut
from src.utils.config import Settings, settings

logger = logging.getLogger("pharma_pipeline.genai")


class GenAIServiceError(RuntimeError):
    """Base exception for GenAI extraction and provider communication failures."""


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Contract for LLM clinical summarization providers."""

    def generate_summary(
        self,
        nct_id: str,
        study_title: str | None,
        brief_summary: str | None,
        detailed_description: str | None,
        conditions: list[str] | None = None,
        interventions: list[dict[str, Any]] | None = None,
    ) -> ClinicalSummaryOut:
        """Extract structured clinical protocol summary from trial text components."""
        ...


class MockLLMProvider:
    """Deterministic, zero-network mock provider for testing and offline environments."""

    def __init__(self, model_name: str = "mock-clinical-v1") -> None:
        self.model_name = model_name

    def generate_summary(
        self,
        nct_id: str,
        study_title: str | None,
        brief_summary: str | None,
        detailed_description: str | None,
        conditions: list[str] | None = None,
        interventions: list[dict[str, Any]] | None = None,
    ) -> ClinicalSummaryOut:
        """Produce deterministic, structured clinical synthesis based on trial metadata."""
        cond_str = ", ".join(conditions) if conditions else "Unspecified indication"

        # Extract intervention names
        int_names: list[str] = []
        if interventions:
            for item in interventions:
                name = item.get("intervention_name")
                if name:
                    int_names.append(name)
        int_str = ", ".join(int_names) if int_names else "Investigational regimen"

        # Heuristic synthesis for mechanism of action
        lower_int = int_str.lower()
        if any(term in lower_int for term in ("mab", "antibody", "trastuzumab", "pembrolizumab")):
            mechanism = f"Targeted monoclonal antibody immunotherapy directed against tumor surface antigens ({int_str})."
        elif any(term in lower_int for term in ("nib", "kinase", "inhibitor", "olaparib")):
            mechanism = f"Selective small-molecule enzyme inhibitor interfering with intracellular oncogenic signaling pathways ({int_str})."
        elif any(term in lower_int for term in ("chemo", "taxol", "cisplatin", "paclitaxel")):
            mechanism = f"Cytotoxic antineoplastic agent disrupting mitotic spindle assembly and DNA replication ({int_str})."
        else:
            mechanism = f"Pharmacological modulation of target biological pathways relevant to {cond_str} via {int_str}."

        target_pop = (
            f"Patients diagnosed with {cond_str} meeting protocol-defined inclusion criteria."
        )

        primary_endpoints = [
            "Progression-Free Survival (PFS) evaluated per RECIST v1.1",
            "Objective Response Rate (ORR)",
            "Safety and tolerability incidence of Grade 3-4 adverse events",
        ]

        key_risks = [
            "Hematological toxicities (neutropenia, thrombocytopenia)",
            "Gastrointestinal disorders (nausea, diarrhea, stomatitis)",
            "Immune-related or infusion-related adverse reactions",
        ]

        design = "Phase 2/3 interventional study evaluating therapeutic efficacy, biomarker response, and safety profile."

        return ClinicalSummaryOut(
            nct_id=nct_id,
            study_title=study_title,
            mechanism_of_action=mechanism,
            target_population=target_pop,
            primary_endpoints=primary_endpoints,
            key_risks=key_risks,
            design_summary=design,
            model_name=self.model_name,
        )


class GeminiLLMProvider:
    """Production provider integrating Google Gemini REST API with Structured Outputs."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-flash",
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise GenAIServiceError("GeminiLLMProvider requires a non-empty API key.")
        self.api_key = api_key.strip()
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._client = http_client or httpx.Client(timeout=timeout_seconds)

    def generate_summary(
        self,
        nct_id: str,
        study_title: str | None,
        brief_summary: str | None,
        detailed_description: str | None,
        conditions: list[str] | None = None,
        interventions: list[dict[str, Any]] | None = None,
    ) -> ClinicalSummaryOut:
        """Call Gemini API with structured JSON Schema enforcement."""
        prompt_content = self._build_prompt(
            nct_id=nct_id,
            study_title=study_title,
            brief_summary=brief_summary,
            detailed_description=detailed_description,
            conditions=conditions,
            interventions=interventions,
        )

        url = f"{self.BASE_URL}/{self.model_name}:generateContent?key={self.api_key}"

        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_content}],
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": ClinicalSummaryOut.model_json_schema(),
                "temperature": 0.1,
            },
        }

        try:
            response = self._client.post(url, json=request_body)
            if response.status_code != 200:
                raise GenAIServiceError(
                    f"Gemini API returned error {response.status_code}: {response.text}"
                )

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise GenAIServiceError("Gemini API returned empty response candidates.")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                raise GenAIServiceError("Gemini API returned malformed candidate parts.")

            raw_json = parts[0]["text"]
            parsed_dict = json.loads(raw_json)
            parsed_dict["model_name"] = self.model_name

            return ClinicalSummaryOut.model_validate(parsed_dict)

        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise GenAIServiceError(f"HTTP communication failure with Gemini API: {exc}") from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GenAIServiceError(f"Failed to validate structured LLM output: {exc}") from exc

    def _build_prompt(
        self,
        nct_id: str,
        study_title: str | None,
        brief_summary: str | None,
        detailed_description: str | None,
        conditions: list[str] | None,
        interventions: list[dict[str, Any]] | None,
    ) -> str:
        """Format trial components into a specialized prompt for clinical extraction."""
        return (
            f"You are a Senior Principal Clinical Oncologist and Medical Director.\n"
            f"Extract a structured clinical trial protocol summary for {nct_id}.\n\n"
            f"Title: {study_title or 'N/A'}\n"
            f"Conditions: {', '.join(conditions or ['N/A'])}\n"
            f"Interventions: {json.dumps(interventions or [], ensure_ascii=False)}\n"
            f"Brief Summary: {brief_summary or 'N/A'}\n"
            f"Detailed Description: {detailed_description or 'N/A'}\n\n"
            f"Extract strictly into the requested JSON schema."
        )


class ClinicalProtocolSummarizer:
    """High-level domain service orchestrating clinical protocol summarization."""

    def __init__(self, provider: LLMProviderProtocol) -> None:
        self.provider = provider

    def summarize_trial(self, trial_data: dict[str, Any]) -> ClinicalSummaryOut:
        """Extract structured summary from a trial record dictionary."""
        nct_id = trial_data.get("nct_id")
        if not nct_id:
            raise GenAIServiceError("Cannot summarize trial data missing required 'nct_id'.")

        title = trial_data.get("official_title") or trial_data.get("brief_title")
        brief_summary = trial_data.get("brief_summary")
        detailed_desc = trial_data.get("detailed_description")
        conditions = trial_data.get("conditions", [])
        interventions = trial_data.get("interventions", [])

        return self.provider.generate_summary(
            nct_id=nct_id,
            study_title=title,
            brief_summary=brief_summary,
            detailed_description=detailed_desc,
            conditions=conditions,
            interventions=interventions,
        )


def get_summarizer(cfg: Settings | None = None) -> ClinicalProtocolSummarizer:
    """Factory creating configured ClinicalProtocolSummarizer instance."""
    app_settings = cfg or settings

    provider: LLMProviderProtocol
    if app_settings.llm_provider.lower() == "gemini":
        if not app_settings.llm_api_key:
            logger.warning(
                "LLM provider is set to 'gemini' but LLM_API_KEY is empty. Falling back to MockLLMProvider."
            )
            provider = MockLLMProvider()
        else:
            provider = GeminiLLMProvider(
                api_key=app_settings.llm_api_key,
                model_name=app_settings.llm_model_name,
                timeout_seconds=app_settings.request_timeout_seconds,
            )
    else:
        provider = MockLLMProvider()

    return ClinicalProtocolSummarizer(provider=provider)
