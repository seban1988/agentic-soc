"""
Investigation Agent — deep root cause analysis, IOC extraction, MITRE mapping.
Uses Gemini 2.5 Flash with dynamic thinking + streaming for long investigations.
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

_INVESTIGATION_PROMPT = (Path(__file__).parent / "prompts" / "investigation.md").read_text(encoding="utf-8")
_SOC_PROMPT = (Path(__file__).parent / "prompts" / "soc_investigator.md").read_text(encoding="utf-8")

_SYSTEM = f"{_SOC_PROMPT}\n\n---\n\n{_INVESTIGATION_PROMPT}"


def _build_case_context(case: dict, triage: dict) -> str:
    issues = case.get("_issues", [])

    MAX_FULL_ISSUES = 50
    if len(issues) > MAX_FULL_ISSUES:
        recent = issues[:MAX_FULL_ISSUES]
        older_count = len(issues) - MAX_FULL_ISSUES
        issues_section = (
            f"[NOTE: {older_count} older issues omitted. "
            f"The {MAX_FULL_ISSUES} most recent are included below.]\n\n"
            + json.dumps(recent, indent=2)
        )
    else:
        issues_section = json.dumps(issues, indent=2)

    case_data = {k: v for k, v in case.items() if not k.startswith("_")}

    return (
        "## Triage Results\n"
        f"```json\n{json.dumps(triage, indent=2)}\n```\n\n"
        "## Case Data\n"
        f"```json\n{json.dumps(case_data, indent=2)}\n```\n\n"
        "## Issues / Alerts\n"
        f"```json\n{issues_section}\n```"
    )


def investigate_case(case: dict, triage: dict) -> str:
    """
    Run deep investigation on a case. Returns full markdown findings string.
    Uses streaming to handle long-running investigations.
    """
    severity = triage.get("severity", "MEDIUM")
    # Full dynamic thinking for high-severity cases; bounded for lower severity
    thinking_budget = -1 if severity in ("CRITICAL", "HIGH") else 4096

    logger.info("Investigating case %s (severity=%s)", case["case_id"], severity)

    context = _build_case_context(case, triage)
    prompt = (
        "Perform a complete investigation of this Cortex XSIAM case. "
        "Follow the output format defined in your system prompt exactly.\n\n"
        + context
    )

    findings = ""
    for chunk in _get_client().models.generate_content_stream(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
            temperature=0,
        ),
    ):
        if chunk.text:
            findings += chunk.text

    logger.info(
        "Case %s investigation complete (%d chars)",
        case["case_id"], len(findings),
    )
    return findings.strip()
