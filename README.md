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
    ├── Triage Agent   → severity, category, false positive likelihood
    └── Investigation Agent → root cause, IoCs, MITRE ATT&CK, timeline
              │
              ▼
    Writer Agent → XSIAM Case Discussion + Notepad
              │
              ▼
    SQLite state store → Dashboard (Streamlit)
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
- A running [Cortex MCP Server](https://docs.redacted.example.com) (v2.13.1) at `http://localhost:8888/api/v1/stream/mcp`
- A Cortex XSIAM tenant with API access
- A Google Gemini API key

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
# Google Gemini
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-2.5-flash

# Cortex XSIAM — use the api-* subdomain
CORTEX_URL=https://api-<tenant>.xdr.us.redacted.example.com
CORTEX_API_KEY=<api-key-value>
CORTEX_API_ID=<api-key-id>

# MCP server
MCP_SERVER_URL=http://localhost:8888/api/v1/stream/mcp

# Agent behavior
POLL_INTERVAL_SECONDS=300
MAX_CASES_PER_POLL=50

# Case filters (all optional)
CASE_STATUSES=New,Under Investigation
CASE_SEVERITIES=high,critical
CASE_DOMAIN=SECURITY
CASE_ASSIGNEE_EMAIL=analyst@company.com   # server-side filter by email
CASE_ASSIGNEE_NAME=Jane Smith             # server-side filter by display name
CASE_LAST_UPDATE_HOURS=24                 # cases modified in last N hours
CASE_LOOKBACK_HOURS=48                    # cases created in last N hours
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

# Dry run — prints findings, no XSIAM write
python main.py --case-id 88921 --dry-run
```

## Dashboard

```bash
python -m streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`. Shows agent status, active filters, per-severity case counts, a sortable case table, and expandable investigation findings. Auto-refreshes every 30 seconds.

![Dashboard](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)

## Architecture

| Component | Technology |
|---|---|
| LLM | Gemini 2.5 Flash (dynamic thinking) |
| Case retrieval | XSIAM REST API `/public_api/v1/case/search` |
| Issue enrichment | Cortex MCP Server v2.13.1 (12 read-only tools) |
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

A condensed version is also written to the Case Notepad for quick reference.

## Security Notes

- Never commit `.env` — it is gitignored
- The agent has read + comment/notepad write access only; it cannot close, reassign, or modify case status
- Raw case data (alerts, logs, IoCs) is only logged at DEBUG level
