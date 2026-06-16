"""
MCP client + polling logic.

Case retrieval uses the XSIAM REST API (/public_api/v1/case/search) directly —
it exposes far more server-side filter fields than the MCP tool.
Issue/asset enrichment still goes through the MCP server.

Filter behaviour is controlled entirely via environment variables:
  CASE_STATUSES           comma-separated status_progress values   (default: New,Under Investigation)
  CASE_SEVERITIES         comma-separated severity values          (default: all)
  CASE_DOMAIN             single case_domain value                 (default: all)
  CASE_LOOKBACK_HOURS     only cases created in the last N hours   (default: all)
  CASE_ASSIGNEE_EMAIL     only cases assigned to this email        (default: all)
  CASE_ASSIGNEE_NAME      only cases assigned to this display name (default: all)
"""

import http.client
import json
import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

from scheduler.state import filter_new

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8888/api/v1/stream/mcp")
MAX_CASES = int(os.getenv("MAX_CASES_PER_POLL", "50"))

_CORTEX_FQDN = os.getenv("CORTEX_URL", "").removeprefix("https://").removeprefix("http://")
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _cortex_headers() -> dict:
    return {
        "Authorization": os.getenv("CORTEX_API_KEY", ""),
        "x-xdr-auth-id": os.getenv("CORTEX_API_ID", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Filter builder — all pushed to the server via REST API
# ---------------------------------------------------------------------------

def _build_case_filters() -> list[dict]:
    filters = []

    raw_statuses = os.getenv("CASE_STATUSES", "New,Under Investigation")
    statuses = [s.strip() for s in raw_statuses.split(",") if s.strip()]
    if statuses:
        filters.append({"field": "status_progress", "operator": "in", "value": statuses})

    raw_severities = os.getenv("CASE_SEVERITIES", "")
    severities = [s.strip().lower() for s in raw_severities.split(",") if s.strip()]
    if severities:
        filters.append({"field": "severity", "operator": "in", "value": severities})

    domain = os.getenv("CASE_DOMAIN", "").strip()
    if domain:
        filters.append({"field": "case_domain", "operator": "in", "value": [domain]})

    lookback = os.getenv("CASE_LOOKBACK_HOURS", "").strip()
    if lookback:
        cutoff_ms = int((time.time() - float(lookback) * 3600) * 1000)
        filters.append({"field": "creation_time", "operator": "gte", "value": cutoff_ms})

    last_update = os.getenv("CASE_LAST_UPDATE_HOURS", "").strip()
    if last_update:
        cutoff_ms = int((time.time() - float(last_update) * 3600) * 1000)
        filters.append({"field": "last_update_time", "operator": "gte", "value": cutoff_ms})

    # Server-side assignee filters (confirmed working via /public_api/v1/case/search)
    assignee_email = os.getenv("CASE_ASSIGNEE_EMAIL", "").strip()
    if assignee_email:
        filters.append({"field": "assigned_user", "operator": "in", "value": [assignee_email]})

    assignee_name = os.getenv("CASE_ASSIGNEE_NAME", "").strip()
    if assignee_name:
        filters.append({"field": "assigned_user_pretty", "operator": "in", "value": [assignee_name]})

    return filters


# ---------------------------------------------------------------------------
# Case retrieval via XSIAM REST API
# ---------------------------------------------------------------------------

def get_case_by_id_rest(case_id: int | str) -> dict | None:
    """Fetch a single case by ID via REST API. Returns None if not found."""
    body = json.dumps({
        "request_data": {
            "filters": [{"field": "case_id", "operator": "in", "value": [int(case_id)]}],
            "search_from": 0,
            "search_to": 1,
        }
    }).encode()

    conn = http.client.HTTPSConnection(_CORTEX_FQDN, timeout=30)
    try:
        conn.request("POST", "/public_api/v1/case/search", body, _cortex_headers())
        res = conn.getresponse()
        data = json.loads(res.read().decode())
        if res.status != 200:
            raise RuntimeError(f"case/search returned {res.status}: {data}")
        cases = data.get("reply", {}).get("DATA", [])
        return cases[0] if cases else None
    finally:
        conn.close()


def get_cases_rest(search_from: int = 0) -> list[dict]:
    """
    Fetch cases using the XSIAM REST API /public_api/v1/case/search.
    Supports full server-side filtering including assigned_user.
    """
    filters = _build_case_filters()
    logger.debug("Case filters: %s", filters)

    body = json.dumps({
        "request_data": {
            "filters": filters,
            "search_from": search_from,
            "search_to": min(search_from + MAX_CASES, 100),
            "sort": {"field": "creation_time", "keyword": "desc"},
        }
    }).encode()

    conn = http.client.HTTPSConnection(_CORTEX_FQDN, timeout=30)
    try:
        conn.request("POST", "/public_api/v1/case/search", body, _cortex_headers())
        res = conn.getresponse()
        data = json.loads(res.read().decode())
        if res.status != 200:
            raise RuntimeError(f"case/search returned {res.status}: {data}")
        return data.get("reply", {}).get("DATA", [])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP helpers — used for issue/asset enrichment only
# ---------------------------------------------------------------------------

def _mcp_post(payload: dict, session_id: str | None = None) -> dict:
    headers = dict(_MCP_HEADERS)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    resp = requests.post(MCP_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise ValueError(f"No SSE data frame in MCP response: {resp.text[:200]}")


def mcp_init() -> str:
    resp = requests.post(
        MCP_URL,
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentic-soc", "version": "0.1.0"},
            },
        },
        headers=_MCP_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        raise RuntimeError("MCP server did not return a session ID")
    logger.debug("MCP session: %s", session_id)
    return session_id


def mcp_call(session_id: str, tool: str, arguments: dict, req_id: int = 2) -> Any:
    result = _mcp_post(
        {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}},
        session_id=session_id,
    )
    if "error" in result:
        raise RuntimeError(f"MCP tool error ({tool}): {result['error']}")
    content = result.get("result", {}).get("content", [])
    for block in content:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError:
                return block["text"]
    return result


def get_issues_for_case(session_id: str, case_id: int) -> list[dict]:
    result = mcp_call(session_id, "get_issues", {
        "filters": [{"field": "id", "operator": "in", "value": [case_id]}],
        "search_from": 0,
        "search_to": 100,
        "sort": {"field": "observation_time", "keyword": "desc"},
    }, req_id=3)
    return result.get("reply", {}).get("DATA", [])


def get_asset(session_id: str, asset_id: str) -> dict:
    result = mcp_call(session_id, "get_asset_by_id", {"asset_id": asset_id}, req_id=4)
    return result.get("reply", {})


# ---------------------------------------------------------------------------
# Main poll entry point
# ---------------------------------------------------------------------------

def poll_new_cases() -> list[dict]:
    """
    Fetch cases via XSIAM REST API, enrich with issues via MCP,
    and return only cases not yet processed.
    Reloads .env on every call so filter changes take effect without a restart.
    """
    load_dotenv(override=True)
    try:
        cases = get_cases_rest()
    except Exception as exc:
        logger.error("get_cases_rest failed: %s", exc)
        return []

    logger.info("Fetched %d cases from REST API", len(cases))
    unprocessed = filter_new(cases)
    logger.info("%d cases are new/updated and will be processed", len(unprocessed))

    if not unprocessed:
        return []

    try:
        session_id = mcp_init()
    except Exception as exc:
        logger.error("MCP init failed (issue enrichment will be skipped): %s", exc)
        for case in unprocessed:
            case["_issues"] = []
        return unprocessed

    enriched = []
    for case in unprocessed:
        try:
            case["_issues"] = get_issues_for_case(session_id, case["case_id"])
            logger.debug("Case %s: %d issues", case["case_id"], len(case["_issues"]))
        except Exception as exc:
            logger.warning("Could not fetch issues for case %s: %s", case["case_id"], exc)
            case["_issues"] = []
        enriched.append(case)

    return enriched
