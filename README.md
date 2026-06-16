# Agentic SOC

An autonomous Security Operations Center agent that connects to a Cortex XSIAM tenant, polls for new cases every 5 minutes, auto-triages and investigates each case using Gemini AI, and writes findings back to XSIAM as case comments and notepad entries.

## Overview

```
Cron (5 min)
    │
    ▼
Poll Agent ── XSIAM REST API (/public_api/v1/case/search)
    │
    ▼
For each new/updated case:
    ├── Triage Agent      → severity, category, false positive likelihood
    └── Investigation Agent → root cause, IoCs, MITRE ATT&CK, timeline
              │
              ├── Issue enrichment ── Cortex MCP Server (read-only)
              │
              ▼
    Writer Agent → XSIAM Case Discussion + Notepad
              │
              ▼
    SQLite state store → Streamlit Dashboard
```

The agent applies **NIST SP 800-53**, **NIST CSF 2.0**, and **ISO/IEC 27001** frameworks in its analysis and maps findings to **MITRE ATT&CK** tactics and techniques.

## Features

- **Server-side filtering** — filter cases by status, severity, domain, assignee (email or display name), and time window directly via the XSIAM REST API
- **Hot-reload config** — edit `.env` and changes are picked up on the next poll cycle without restarting
- **False positive detection** — cases with high FP likelihood are flagged and skipped
- **Adaptive thinking depth** — uncapped Gemini reasoning for CRITICAL/HIGH cases, bounded for lower severity
- **Streamlit dashboard** — live poll status, case table with severity badges, expandable findings
- **Deduplication** — SQLite state store prevents reprocessing cases unless they've been updated

## Requirements

- Python 3.11+
- A Cortex XSIAM tenant with API access (API key with `Responder` role)
- A running **Cortex MCP Server v2.13.1** (see below)
- A Google Gemini API key

## Cortex MCP Server

The agent uses the **Cortex MCP Server v2.13.1** for read-only data enrichment — fetching issues, assets, vulnerabilities, and playbooks linked to each case. Case retrieval and all write operations go directly through the XSIAM REST API; the MCP server handles enrichment only.

### What it's used for

| MCP Tool | Purpose |
|---|---|
| `get_issues` | Fetch alerts/incidents linked to a case |
| `get_assets` / `get_asset_by_id` | Asset context for affected hosts |
| `get_filtered_endpoints` | Endpoint details (OS, status, isolation state) |
| `get_vulnerabilities` | Known CVEs on affected assets |
| `get_correlation_rules` | Detection rule definitions that fired |
| `get_playbook` | Retrieve the playbook associated with a case |

### Transport

The MCP server uses the **Streamable HTTP transport** (MCP protocol `2024-11-05`). Each agent run opens a session via a `POST /initialize` request and receives an `Mcp-Session-Id` header that is passed in all subsequent tool calls.

```
POST http://localhost:8888/api/v1/stream/mcp
Accept: application/json, text/event-stream
```

Responses are Server-Sent Events (SSE) — the agent reads `data:` lines and parses the JSON payload.

### Installation

Download and run the Cortex MCP Server from the Palo Alto Networks marketplace or your XSIAM tenant's integrations page. The default port is `8888`. Once running, set `MCP_SERVER_URL` in your `.env`:

```bash
MCP_SERVER_URL=http://localhost:8888/api/v1/stream/mcp
```

If the MCP server is unavailable at startup, the agent logs a warning and continues — case triage and investigation will proceed without issue enrichment.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure secrets
cp .env.example .env
# Edit .env with your credentials and filters

# Initialize the state database
python -c "from scheduler.state import init_db; init_db()"
```

## Configuration

All configuration is via `.env`:

```bash
GEMINI_API_KEY=<your-key>

CORTEX_URL=https://api-<tenant>.xdr.us.redacted.example.com
CORTEX_API_KEY=<api-key-value>
CORTEX_API_ID=<api-key-id>

GEMINI_MODEL=gemini-2.5-flash

MCP_SERVER_URL=http://localhost:8888/api/v1/stream/mcp
STATE_DB_PATH=./data/processed_cases.db
POLL_INTERVAL_SECONDS=300
MAX_CASES_PER_POLL=50
LOG_LEVEL=INFO

CASE_STATUSES=New,Under Investigation
CASE_SEVERITIES=low, medium, high, critical
CASE_DOMAIN=SECURITY
CASE_LAST_UPDATE_HOURS=24
CASE_ASSIGNEE_EMAIL=analyst@company.com
CASE_ASSIGNEE_NAME=
CASE_LOOKBACK_HOURS=
```

> **Note:** The XSIAM API key must have the `Responder` role to write case comments and notepad entries.

## Usage

```bash
# Continuous polling (every 5 min)
python main.py

# Single poll cycle and exit
python main.py --run-once

# Process a specific case (writes to XSIAM)
python main.py --case-id 88921

# Dry run — prints findings to stdout, no XSIAM write
python main.py --case-id 88921 --dry-run
```

## Dashboard

```bash
python -m streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`. Shows agent status, active filters, per-severity case counts, a case table with colour-coded severity badges, and expandable investigation findings per case. Auto-refreshes every 30 seconds and picks up `.env` filter changes live.

## Architecture

| Component | Technology |
|---|---|
| LLM | Gemini 2.5 Flash (dynamic thinking) |
| Case retrieval | XSIAM REST API `/public_api/v1/case/search` |
| Issue/asset enrichment | Cortex MCP Server v2.13.1 (Streamable HTTP) |
| Write back | XSIAM REST API `/public_api/v1/incidents/update_incident` |
| State store | SQLite |
| Dashboard | Streamlit |

## Output Format

Each processed case receives a structured markdown comment posted to the XSIAM Case Discussion:

- Triage summary (severity, category, false positive assessment)
- Root cause analysis
- Reconstructed timeline
- Extracted IoCs (IPs, domains, hashes, accounts)
- MITRE ATT&CK mapping (tactic + technique)
- Containment, eradication, and recovery recommendations
- ISO 27001 Annex A control references
- NIST CSF function alignment

A condensed version is also written to the Case Notepad for quick reference.

## Security Notes

- Never commit `.env` — it is gitignored
- The agent has read + comment/notepad write access only; it cannot close, reassign, or modify case status
- Raw case data (alerts, logs, IoCs) is only logged at DEBUG level — do not set `LOG_LEVEL=DEBUG` in production
