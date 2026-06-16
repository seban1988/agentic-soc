"""
Triage Agent — fast severity/category/FP classification for a single case.
Uses Gemini 2.5 Flash with dynamic thinking.
"""

import json
import logging
import os
from pathlib import Path

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client

_TRIAGE_PROMPT = (Path(__file__).parent / "prompts" / "triage.md").read_text(encoding="utf-8")
_SOC_PROMPT = (Path(__file__).parent / "prompts" / "soc_investigator.md").read_text(encoding="utf-8")

_SYSTEM = f"{_SOC_PROMPT}\n\n---\n\n{_TRIAGE_PROMPT}"


def triage_case(case: dict) -> dict:
    """
    Run triage on a case dict (including _issues list).
    Returns a triage result dict or raises on failure.
    """
    case_summary = {
        "case_id": case.get("case_id"),
        "case_name": case.get("case_name"),
        "severity": case.get("severity"),
        "status_progress": case.get("status_progress"),
        "description": case.get("description"),
        "creation_time": case.get("creation_time"),
        "issue_count": case.get("issue_count"),
        "mitre_tactics": case.get("mitre_tactics_ids_and_names", []),
        "mitre_techniques": case.get("mitre_techniques_ids_and_names", []),
        "issue_categories": case.get("issue_categories", []),
        "users": case.get("users", []),
        "hosts": case.get("hosts", []),
        "tags": case.get("tags", []),
        "issues": case.get("_issues", [])[:20],
    }

    severity = (case.get("severity") or "low").upper()
    # Higher thinking budget for complex/high-severity cases
    thinking_budget = -1 if severity in ("CRITICAL", "HIGH") else 1024

    logger.info("Triaging case %s (severity=%s)", case["case_id"], severity)

    response = _get_client().models.generate_content(
        model=_MODEL,
        contents=(
            "Triage this Cortex XSIAM case. "
            "Respond with ONLY the JSON object specified in your instructions.\n\n"
            f"```json\n{json.dumps(case_summary, indent=2)}\n```"
        ),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
            response_mime_type="application/json",
            temperature=0,
        ),
    )

    text = response.text.strip()

    # Strip accidental markdown fences if model adds them despite JSON mode
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Triage response not valid JSON: %s\nRaw: %s", exc, text[:500])
        raise

    logger.info(
        "Case %s triage: severity=%s category=%s fp=%s",
        case["case_id"], result.get("severity"), result.get("category"),
        result.get("false_positive_likelihood"),
    )
    return result
