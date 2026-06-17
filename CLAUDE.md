# Agentic SOC â€” Autonomous Security Operations Center Investigator

## Project Overview

An autonomous SOC (Security Operations Center) agent that connects to a Cortex XSIAM tenant via the XSIAM Public API and an MCP server, polls for new/unprocessed cases every 5 minutes, auto-triages and auto-investigates each case, and writes findings back to XSIAM Case Comments and Notepad sections.

The agent acts as an expert SOC analyst with deep knowledge of:
- **NIST SP 800-53** â€” Security and Privacy Controls for Information Systems
- **NIST CSF 2.0** â€” Cybersecurity Framework (Identify, Protect, Detect, Respond, Recover)
- **ISO/IEC 27001** â€” Information Security Management Systems

---

## Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Cron Scheduler (every 5 min)                              â”‚
â”‚         â”‚                                                  â”‚
â”‚         â–¼                                                  â”‚
â”‚  Poll Agent (fetch new/unprocessed cases from XSIAM)       â”‚
â”‚         â”‚                                                  â”‚
â”‚         â–¼                                                  â”‚
â”‚  For each unprocessed case:                                â”‚
â”‚    â”œâ”€â”€ Triage Agent   (severity, category, priority)       â”‚
â”‚    â””â”€â”€ Investigation Agent (root cause, IoCs, timeline)    â”‚
â”‚              â”‚                                             â”‚
â”‚              â–¼                                             â”‚
â”‚  Write findings â†’ XSIAM Case Comments + Notepad            â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚                    â”‚
         â–¼                    â–¼
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

# Cortex XSIAM tenant â€” used by agent/cortex_api.py for direct REST writes
# (CORTEX_URL must be the api-* subdomain, e.g. https://<your-xsiam-api-url>)
CORTEX_URL=https://<your-xsiam-api-url>
CORTEX_API_KEY=<api-key-value>
CORTEX_API_ID=<api-key-id-integer>

# MCP server â€” Cortex MCP Server v2.13.1, already running, provides 12 read-only tools
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
â”œâ”€â”€ CLAUDE.md                    # this file
â”œâ”€â”€ .env                         # secrets (gitignored)
â”œâ”€â”€ .env.example                 # template
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ pyproject.toml
â”‚
â”œâ”€â”€ mcp_server/                  # XSIAM MCP server
â”‚   â”œâ”€â”€ server.py                # MCP server entrypoint
â”‚   â”œâ”€â”€ tools/                   # MCP tool implementations
â”‚   â”‚   â”œâ”€â”€ cases.py             # get_cases, get_case_details
â”‚   â”‚   â”œâ”€â”€ alerts.py            # get_alerts, get_alert_details
â”‚   â”‚   â”œâ”€â”€ incidents.py         # get_incidents
â”‚   â”‚   â””â”€â”€ comments.py          # post_case_comment, update_notepad
â”‚   â””â”€â”€ xsiam_client.py          # XSIAM REST API wrapper
â”‚
â”œâ”€â”€ agent/                       # Gemini agent logic
â”‚   â”œâ”€â”€ prompts/                 # System prompts
â”‚   â”‚   â”œâ”€â”€ soc_investigator.md  # Master SOC analyst persona
â”‚   â”‚   â”œâ”€â”€ triage.md            # Triage agent instructions
â”‚   â”‚   â””â”€â”€ investigation.md     # Investigation agent instructions
â”‚   â”œâ”€â”€ cortex_api.py            # REST write client (comment + notepad)
â”‚   â”œâ”€â”€ triage_agent.py          # Triage workflow
â”‚   â”œâ”€â”€ investigation_agent.py   # Investigation workflow
â”‚   â””â”€â”€ writer_agent.py          # Write findings to XSIAM
â”‚
â”œâ”€â”€ scheduler/
â”‚   â”œâ”€â”€ poll.py                  # Poll loop & case deduplication
â”‚   â””â”€â”€ state.py                 # Processed-case state store
â”‚
â”œâ”€â”€ knowledge/                   # Security framework reference docs
â”‚   â”œâ”€â”€ nist_800_53.md
â”‚   â”œâ”€â”€ nist_csf_2.md
â”‚   â””â”€â”€ iso_27001.md
â”‚
â”œâ”€â”€ data/                        # Runtime state (gitignored)
â”‚   â””â”€â”€ processed_cases.db
â”‚
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ test_mcp_server.py
â”‚   â”œâ”€â”€ test_triage.py
â”‚   â””â”€â”€ test_investigation.py
â”‚
â””â”€â”€ main.py                      # Entrypoint
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
| `get_script` | Retrieve and parse a Cortex script (ZIP â†’ YAML/JSON) |
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

# Triage â€” JSON mode, bounded thinking
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

# Investigation â€” streaming, dynamic thinking
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
1. **Identify** â€” What asset/system is affected? What data is at risk?
2. **Detect** â€” What indicators triggered the alert? True positive vs false positive assessment.
3. **Severity scoring** â€” Map to CVSS / XSIAM severity using available data.
4. **Priority assignment** â€” Based on asset criticality, exposure, and threat context.

### Investigation Framework
1. **Timeline reconstruction** â€” Sequence of events from raw logs.
2. **Root cause analysis** â€” Initial access vector, lateral movement, persistence.
3. **IoC extraction** â€” IPs, domains, hashes, usernames, processes.
4. **MITRE ATT&CK mapping** â€” Tactics, techniques, procedures.
5. **Blast radius** â€” Affected systems, users, data.
6. **Recommended response** â€” Containment, eradication, recovery steps (NIST CSF Respond/Recover).

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
2. Run Triage Agent â†’ produce: severity, category, priority, false_positive_likelihood
3. If false_positive_likelihood > 0.85 â†’ mark and skip investigation
4. Run Investigation Agent â†’ produce: root_cause, iocs, mitre_mapping, timeline, recommendations
5. Run Writer Agent â†’ post comment + update notepad in XSIAM
6. Mark case as processed in state store
```

---

## Output Format â€” Case Comment

```markdown
## ðŸ¤– Automated SOC Analysis

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
- NIST CSF Functions: Detect â†’ Respond â†’ Recover
```

---

## Error Handling

- **XSIAM API errors**: Retry with exponential backoff (3 attempts max). Log failures, skip to next case.
- **Gemini API rate limits**: The `google-genai` SDK raises `google.genai.errors.APIError` on quota exhaustion â€” catch and back off before retrying.
- **MCP connection failures**: Circuit breaker pattern â€” pause polling, alert operator.
- **State store failures**: Log and continue (idempotency: reprocessing a case is acceptable but should be avoided).

---

## Development Guidelines

- **Never hardcode secrets** â€” use environment variables only.
- **No mock LLM responses in tests** â€” use real API calls on a small fixture case. Integration tests matter.
- **Log case IDs and processing timestamps** at INFO level for every case handled.
- **Log full Gemini responses** at DEBUG level only.
- **System prompts live in `.md` files** in `agent/prompts/` â€” not inlined in code.
- **MCP tool schemas** must include `description` fields with explicit trigger conditions (e.g., "Call this tool to retrieve full alert details including raw log data â€” always call this before beginning investigation").
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
- Case data (alerts, logs, IoCs) may contain sensitive PII or confidential data. Do not log raw case content at INFO level â€” DEBUG only, and disable DEBUG in production.
- Validate all XSIAM API responses before passing to Gemini. Strip or redact any fields that are not needed for analysis to minimize context size and exposure.
