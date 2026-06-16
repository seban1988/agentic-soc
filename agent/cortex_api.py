"""
Direct Cortex REST API client — write operations only.
Reads are handled by the MCP server (scheduler/poll.py).

Confirmed working endpoints:
  POST /public_api/v1/incidents/update_incident
    - Case Discussion: update_data.comment = {"comment_action": "add", "value": "..."}
    - Case Notepad:    update_data.notes = "..."
"""

import http.client
import json
import logging
import os

logger = logging.getLogger(__name__)

_CORTEX_FQDN = os.getenv("CORTEX_URL", "").removeprefix("https://").removeprefix("http://")
_API_KEY = os.getenv("CORTEX_API_KEY", "")
_API_KEY_ID = os.getenv("CORTEX_API_ID", "")


def _headers() -> dict:
    return {
        "Authorization": _API_KEY,
        "x-xdr-auth-id": _API_KEY_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _post(path: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    conn = http.client.HTTPSConnection(_CORTEX_FQDN, timeout=30)
    try:
        conn.request("POST", path, payload, _headers())
        res = conn.getresponse()
        data = res.read().decode()
        if res.status not in (200, 201):
            raise RuntimeError(f"Cortex API {path} returned {res.status}: {data[:300]}")
        return json.loads(data)
    finally:
        conn.close()


def add_case_comment(incident_id: str, comment: str) -> bool:
    """
    Add a comment to the Case Discussion thread.
    Maps to update_data.comment = {comment_action: "add", value: ...}
    """
    try:
        _post("/public_api/v1/incidents/update_incident", {
            "request_data": {
                "incident_id": str(incident_id),
                "update_data": {
                    "comment": {"comment_action": "add", "value": comment}
                },
            }
        })
        logger.info("Posted discussion comment to incident %s", incident_id)
        return True
    except Exception as exc:
        logger.error("Failed to post comment to incident %s: %s", incident_id, exc)
        return False


def update_case_notepad(incident_id: str, notes: str) -> bool:
    """
    Overwrite the Case Notepad field.
    Maps to update_data.notes = "..."
    """
    try:
        _post("/public_api/v1/incidents/update_incident", {
            "request_data": {
                "incident_id": str(incident_id),
                "update_data": {"notes": notes},
            }
        })
        logger.info("Updated notepad for incident %s", incident_id)
        return True
    except Exception as exc:
        logger.error("Failed to update notepad for incident %s: %s", incident_id, exc)
        return False
