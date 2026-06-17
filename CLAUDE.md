# Agentic SOC — Autonomous Security Operations Center Investigator

## Project Overview

An autonomous SOC (Security Operations Center) agent that connects to a Cortex XSIAM tenant via the XSIAM Public API and an MCP server, polls for new/unprocessed cases every 5 minutes, auto-triages and auto-investigates each case, and writes findings back to XSIAM Case Comments and Notepad sections.

The agent acts as an expert SOC analyst with deep knowledge of:
- **NIST SP 800-53** — Security and Privacy Controls for Information Systems
- **NIST CSF 2.0** — Cybersecurity Framework (Identify, Protect, Detect, Respond, Recover)
- **ISO/IEC 27001** — Information Security Management Systems

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Cron Scheduler (every 5 min)                              │
│         │                                                  │
│         ▼                                                  │
│  Poll Agent (fetch new/unprocessed cases from XSIAM)       │
│         │                                                  │
│         ▼                                                  │
│  For each unprocessed case:                                │
│    ├── Triage Agent   (severity, category, priority)       │
│    └── Investigation Agent (root cause, IoCs, timeline)    │
│              │                                             │
│              ▼                                             │
│  Write findings → XSIAM Case Comments + Notepad            │
└────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   XSIAM Public API     MCP Server
   (REST over HTTPS)    (custom XSIAM MCP)
```

**XSIAM terminology mapping:**
- "Cases" = Cases (investigation containers)
- "Issues" = Incidents + Alerts (underlying events within a case)

---

## Technical Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | Native google-genai SDK, sync + streaming |
| LLM | **gemini-2.5-flash** | Reasoning model with thinking, fast + cost-efficient |
| Thinking | **dynamic** (`thinking_budget=-1`) | Uncapped for CRITICAL/HIGH; bounded for lower severity |
| MCP | Cortex MCP Server v2.13.1 | 12 read-only XSIAM tools |
| Scheduler | **polling loop** (time.sleep) | 5-minute polling interval |
| State store | **SQLite** | Track processed case IDs |

---

## Environment Variables

```bash
# Google Gemini
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-2.5-flash   # model used by triage + investigation agents

# Cortex XSIAM tenant — used by agent/cortex_api.py for direct REST writes
# (CORTEX_URL must be the api-* subdomain, e.g. https://api-<tenant>.xdr.us.redacted.example.com)
CORTEX_URL=https://api-<tenant>.xdr.us.redacted.example.com
CORTEX_API_KEY=<api-key-value>
CORTEX_API_ID=<api-key-id-integer>

# MCP server — Cortex MCP Server v2.13.1, already running, provides 12 read-only tools
MCP_SERVER_URL=http://localhost:8888/api/v1/stream/mcp

# State tracking
STATE_DB_PATH=./data/processed_cases.db

# Agent behavior
POLL_INTERVAL_SECONDS=300   # 5 minutes
MAX_CASES_PER_POLL=50       # throttle per run
LOG_LEVEL=INFO
```

---

## Directory Structure

```
Agentic_SOC/
├── CLAUDE.md                    # this file
├── .env                         # secrets (gitignored)
├── .env.example                 # template
├── requirements.txt
├── pyproject.toml
│
├── mcp_server/                  # XSIAM MCP server
│   ├── server.py                # MCP server entrypoint
│   ├── tools/                   # MCP tool implementations
│   │   ├── cases.py             # get_cases, get_case_details
│   │   ├── alerts.py            # get_alerts, get_alert_details
│   │   ├── incidents.py         # get_incidents
│   │   └── comments.py          # post_case_comment, update_notepad
│   └── xsiam_client.py          # XSIAM REST API wrapper
│
├── agent/                       # Gemini agent logic
│   ├── prompts/                 # System prompts
│   │   ├── soc_investigator.md  # Master SOC analyst persona
│   │   ├── triage.md            # Triage agent instructions
│   │   └── investigation.md     # Investigation agent instructions
│   ├── cortex_api.py            # REST write client (comment + notepad)
│   ├── triage_agent.py          # Triage workflow
│   ├── investigation_agent.py   # Investigation workflow
│   └── writer_agent.py          # Write findings to XSIAM
│
├── scheduler/
│   ├── poll.py                  # Poll loop & case deduplication
│   └── state.py                 # Processed-case state store
│
├── knowledge/                   # Security framework reference docs
│   ├── nist_800_53.md
│   ├── nist_csf_2.md
│   └── iso_27001.md
│
├── data/                        # Runtime state (gitignored)
│   └── processed_cases.db
│
├── tests/
│   ├── test_mcp_server.py
│   ├── test_triage.py
│   └── test_investigation.py
│
└── main.py                      # Entrypoint
```

---

## MCP Server

The MCP server is **Cortex MCP Server v2.13.1**, already running at `http://localhost:8888/api/v1/stream/mcp`. It uses the Streamable HTTP transport (MCP protocol 2024-11-05) and exposes **12 read-only tools**. Write operations (case comments, notepad) go directly via the Cortex REST API in `agent/cortex_api.py`.

### Available MCP Tools (read-only)

| Tool | Purpose |
|---|---|
| `get_cases` | List cases with filters (severity, status, creation_time, case_domain) |
| `get_issues` | List issues/alerts linked to cases |
| `get_assets` | List/filter assets (up to 1000 per request) |
| `get_asset_by_id` | Detailed asset information by asset ID |
| `get_filtered_endpoints` | Filtered endpoint list by ID, status, platform |
| `get_vulnerabilities` | Vulnerability list with filter support |
| `get_correlation_rules` | Detection rule definitions |
| `get_audit_management_log` | Audit log with filtering and pagination |
| `get_tenant_info` | Tenant license and environment info |
| `get_assessment_profile_results` | Assessment profile evaluation results |
| `get_script` | Retrieve and parse a Cortex script (ZIP → YAML/JSON) |
| `get_playbook` | Retrieve and parse a Cortex playbook |

### MCP Session Pattern

Each request to the MCP server requires a session. Initialize once per agent run:

```python
import requests, json

MCP_URL = "http://localhost:8888/api/v1/stream/mcp"

def mcp_init():
    r = requests.post(MCP_URL,
        json={"jsonrpc":"2.0","id":1,"method":"initialize",
              "params":{"protocolVersion":"2024-11-05","capabilities":{},
                        "clientInfo":{"name":"agentic-soc","version":"0.1.0"}}},
        headers={"Accept":"application/json, text/event-stream"})
    return r.headers["Mcp-Session-Id"]

def mcp_call(session_id, tool_name, arguments, req_id=2):
    r = requests.post(MCP_URL,
        json={"jsonrpc":"2.0","id":req_id,"method":"tools/call",
              "params":{"name": tool_name, "arguments": arguments}},
        headers={"Accept":"application/json, text/event-stream",
                 "Mcp-Session-Id": session_id})
    for line in r.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None
```

### get_cases filter fields
`case_id`, `case_domain`, `severity`, `creation_time`, `status_progress`

### get_issues filter fields
`id`, `external_id`, `detection_method`, `issue_domain`, `severity`, `_insert_time`, `status`

---

## Agent Configuration

### Model & Thinking Settings

Always use `gemini-2.5-flash` with dynamic thinking. The `thinking_budget` controls reasoning depth:
- `-1` = uncapped dynamic thinking (used for CRITICAL/HIGH severity cases)
- `4096` = bounded thinking (MEDIUM/LOW)
- `1024` = minimal thinking (triage pass)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Triage — JSON mode, bounded thinking
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        thinking_config=types.ThinkingConfig(thinking_budget=1024),
        response_mime_type="application/json",
        temperature=0,
    ),
)

# Investigation — streaming, dynamic thinking
for chunk in client.models.generate_content_stream(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
        temperature=0,
    ),
):
    if chunk.text:
        findings += chunk.text
```

### System Prompt Design

The SOC Investigator persona + investigation instructions are concatenated and passed as `system_instruction` in `GenerateContentConfig`. Both agents load from `agent/prompts/`.

```python
_SYSTEM = f"{SOC_INVESTIGATOR_PROMPT}\n\n---\n\n{AGENT_SPECIFIC_PROMPT}"
```

---

## SOC Investigator Agent Persona

The master system prompt (`agent/prompts/soc_investigator.md`) must encode:

### Triage Framework (NIST CSF 2.0 / NIST 800-53)
1. **Identify** — What asset/system is affected? What data is at risk?
2. **Detect** — What indicators triggered the alert? True positive vs false positive assessment.
3. **Severity scoring** — Map to CVSS / XSIAM severity using available data.
4. **Priority assignment** — Based on asset criticality, exposure, and threat context.

### Investigation Framework
1. **Timeline reconstruction** — Sequence of events from raw logs.
2. **Root cause analysis** — Initial access vector, lateral movement, persistence.
3. **IoC extraction** — IPs, domains, hashes, usernames, processes.
4. **MITRE ATT&CK mapping** — Tactics, techniques, procedures.
5. **Blast radius** — Affected systems, users, data.
6. **Recommended response** — Containment, eradication, recovery steps (NIST CSF Respond/Recover).

### ISO 27001 Alignment
- Link findings to relevant ISO 27001 controls (Annex A).
- Note any compliance implications (data breach notification windows, etc.).

---

## Polling Workflow

### State Tracking

Cases must only be processed once unless they have new activity. Track processed case IDs with a timestamp:

```python
# schema: processed_cases(case_id TEXT PRIMARY KEY, processed_at DATETIME, version INT)
# A case is "new" if:
#   - case_id not in processed_cases, OR
#   - case has been updated since last processed (version/timestamp changed)
```

### Poll Loop (every 5 minutes)

```python
async def poll_and_process():
    cases = await mcp.call("xsiam_get_open_cases", {"status": "new", "limit": MAX_CASES_PER_POLL})
    unprocessed = state.filter_new(cases)

    for case in unprocessed:
        await process_case(case)
        state.mark_processed(case.id)
```

### Case Processing Pipeline

```
1. Fetch full case details (case + all alerts/incidents via MCP)
2. Run Triage Agent → produce: severity, category, priority, false_positive_likelihood
3. If false_positive_likelihood > 0.85 → mark and skip investigation
4. Run Investigation Agent → produce: root_cause, iocs, mitre_mapping, timeline, recommendations
5. Run Writer Agent → post comment + update notepad in XSIAM
6. Mark case as processed in state store
```

---

## Output Format — Case Comment

```markdown
## 🤖 Automated SOC Analysis

**Processed:** {timestamp} UTC  
**Severity:** {CRITICAL|HIGH|MEDIUM|LOW|INFORMATIONAL}  
**Category:** {Malware|Phishing|Ransomware|Insider Threat|...}  
**False Positive Assessment:** {LOW|MEDIUM|HIGH} confidence

---

### Triage Summary
{2-3 sentence triage assessment}

### Investigation Findings
**Root Cause:** {root cause description}

**Timeline:**
- {timestamp}: {event}
- {timestamp}: {event}

**IoCs Identified:**
- IPs: {list}
- Domains: {list}
- Hashes: {list}
- Accounts: {list}

**MITRE ATT&CK:**
- Tactic: {tactic} | Technique: {technique ID + name}

### Recommended Response Actions
1. **Contain:** {immediate containment steps}
2. **Eradicate:** {removal steps}
3. **Recover:** {recovery steps}

### Compliance Notes
- ISO 27001 Controls: {relevant Annex A controls}
- NIST CSF Functions: Detect → Respond → Recover
```

---

## Error Handling

- **XSIAM API errors**: Retry with exponential backoff (3 attempts max). Log failures, skip to next case.
- **Gemini API rate limits**: The `google-genai` SDK raises `google.genai.errors.APIError` on quota exhaustion — catch and back off before retrying.
- **MCP connection failures**: Circuit breaker pattern — pause polling, alert operator.
- **State store failures**: Log and continue (idempotency: reprocessing a case is acceptable but should be avoided).

---

## Development Guidelines

- **Never hardcode secrets** — use environment variables only.
- **No mock LLM responses in tests** — use real API calls on a small fixture case. Integration tests matter.
- **Log case IDs and processing timestamps** at INFO level for every case handled.
- **Log full Gemini responses** at DEBUG level only.
- **System prompts live in `.md` files** in `agent/prompts/` — not inlined in code.
- **MCP tool schemas** must include `description` fields with explicit trigger conditions (e.g., "Call this tool to retrieve full alert details including raw log data — always call this before beginning investigation").
- **Thinking budget by case severity**: Use `thinking_budget=-1` (uncapped) for CRITICAL/HIGH, `4096` for MEDIUM/LOW triage.
- **Never truncate XSIAM data** before sending to Gemini. If a case has too many alerts to fit in context, summarize the oldest ones and include all recent ones (last 24h).

---

## Running the Project

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in secrets
cp .env.example .env
# edit .env

# Initialize state database
python -c "from scheduler.state import init_db; init_db()"
```

### Start MCP Server

```bash
python mcp_server/server.py
```

### Start Agent (continuous polling)

```bash
python main.py
```

### One-shot test run (process existing cases without waiting for cron)

```bash
python main.py --run-once
```

---

## Testing

```bash
# Integration test against real XSIAM tenant (requires .env)
pytest tests/ -v --integration

# Test a single case ID (outputs to stdout, no XSIAM write)
python main.py --case-id 88921 --dry-run
```

---

## Security Considerations

- XSIAM API keys must be stored in `.env` (gitignored) or a secrets manager, never in code or prompts.
- The agent has **read access + comment/notepad write access** to XSIAM only. It must not have access to modify case status, assign cases, or close cases without explicit human confirmation.
- Case data (alerts, logs, IoCs) may contain sensitive PII or confidential data. Do not log raw case content at INFO level — DEBUG only, and disable DEBUG in production.
- Validate all XSIAM API responses before passing to Gemini. Strip or redact any fields that are not needed for analysis to minimize context size and exposure.
