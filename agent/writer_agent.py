"""
Writer Agent — formats and posts findings to Cortex XSIAM.

Writes to two surfaces:
  1. Case Discussion (comment thread) — full analysis markdown
  2. Case Notepad — structured machine-readable summary for future reference
"""

import logging
import os
from datetime import datetime, timezone

from agent.cortex_api import add_case_comment, update_case_notepad

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

logger = logging.getLogger(__name__)


def _build_discussion_comment(case: dict, triage: dict, findings: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    severity = triage.get("severity", "UNKNOWN")
    category = triage.get("category", "UNKNOWN")
    fp = triage.get("false_positive_likelihood", "UNKNOWN")
    priority = triage.get("priority", "UNKNOWN")

    return (
        f"## 🤖 Automated SOC Analysis\n\n"
        f"**Processed:** {ts} UTC  \n"
        f"**Agent Model:** {_MODEL}  \n"
        f"**Severity:** {severity}  \n"
        f"**Category:** {category}  \n"
        f"**Priority:** {priority}  \n"
        f"**False Positive Assessment:** {fp} likelihood\n\n"
        f"---\n\n"
        f"### Triage Summary\n"
        f"{triage.get('triage_summary', 'No triage summary available.')}\n\n"
        f"---\n\n"
        f"{findings}"
    )


def _build_notepad(case: dict, triage: dict) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    return (
        f"AGENTIC-SOC ANALYSIS — {ts} UTC\n"
        f"================================\n"
        f"Case ID:    {case.get('case_id')}\n"
        f"Severity:   {triage.get('severity')}\n"
        f"Category:   {triage.get('category')}\n"
        f"Priority:   {triage.get('priority')}\n"
        f"FP Risk:    {triage.get('false_positive_likelihood')}\n\n"
        f"FP Reasoning:\n{triage.get('false_positive_reasoning', 'N/A')}\n\n"
        f"Triage Summary:\n{triage.get('triage_summary', 'N/A')}\n"
    )


def write_findings(case: dict, triage: dict, findings: str) -> dict[str, bool]:
    """
    Post triage + investigation findings to XSIAM.
    Returns a dict with success flags for each write operation.
    """
    incident_id = str(case["case_id"])
    results = {"comment": False, "notepad": False}

    comment_text = _build_discussion_comment(case, triage, findings)
    results["comment"] = add_case_comment(incident_id, comment_text)

    notepad_text = _build_notepad(case, triage)
    results["notepad"] = update_case_notepad(incident_id, notepad_text)

    if all(results.values()):
        logger.info("Case %s: findings written successfully", incident_id)
    else:
        logger.warning("Case %s: partial write failure — %s", incident_id, results)

    return results
