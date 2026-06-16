"""
Agentic SOC — Dashboard
Run with: streamlit run dashboard/app.py
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scheduler.state import get_recent_cases, get_poll_log

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Agentic SOC",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Auto-refresh every 30 seconds
st.markdown(
    '<meta http-equiv="refresh" content="30">',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SEVERITY_COLOR = {
    "CRITICAL": "#d32f2f",
    "HIGH":     "#f57c00",
    "MEDIUM":   "#f9a825",
    "LOW":      "#388e3c",
    "UNKNOWN":  "#757575",
}
FP_COLOR = {"LOW": "#388e3c", "MEDIUM": "#f9a825", "HIGH": "#d32f2f"}

def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.78em;font-weight:600">{text}</span>'
    )

def _sev_badge(sev: str) -> str:
    sev = (sev or "UNKNOWN").upper()
    return _badge(sev, SEVERITY_COLOR.get(sev, "#757575"))

def _fp_badge(fp: str) -> str:
    fp = (fp or "").upper()
    return _badge(fp, FP_COLOR.get(fp, "#757575"))

def _fmt_ts(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso

def _time_ago(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        return f"{s // 3600}h {(s % 3600) // 60}m ago"
    except Exception:
        return iso

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
cases = get_recent_cases(limit=200)
poll_log = get_poll_log(limit=50)

last_poll = poll_log[0] if poll_log else None
poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🛡️ Agentic SOC")

# Status bar
col_status, col_last, col_next, col_interval = st.columns([1, 2, 2, 1])
with col_status:
    if last_poll:
        try:
            last_dt = datetime.fromisoformat(last_poll["polled_at"]).replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - last_dt).total_seconds()
            alive = age_s < poll_interval * 2
        except Exception:
            alive = False
    else:
        alive = False
    status_html = _badge("● RUNNING", "#2e7d32") if alive else _badge("● IDLE", "#757575")
    st.markdown(f"**Agent**  {status_html}", unsafe_allow_html=True)

with col_last:
    st.markdown(f"**Last poll**  {_time_ago(last_poll['polled_at']) if last_poll else '—'}")

with col_next:
    if last_poll:
        try:
            last_dt = datetime.fromisoformat(last_poll["polled_at"]).replace(tzinfo=timezone.utc)
            next_dt = last_dt + timedelta(seconds=poll_interval)
            diff = int((next_dt - datetime.now(timezone.utc)).total_seconds())
            next_str = f"in {diff}s" if diff > 0 else "now"
        except Exception:
            next_str = "—"
    else:
        next_str = "—"
    st.markdown(f"**Next poll**  {next_str}")

with col_interval:
    st.markdown(f"**Interval**  {poll_interval}s")

st.divider()

# ---------------------------------------------------------------------------
# Active filters
# ---------------------------------------------------------------------------
with st.expander("Active Filters", expanded=False):
    f1, f2, f3, f4, f5 = st.columns(5)
    f1.metric("Assignee", os.getenv("CASE_ASSIGNEE_EMAIL", "all") or "all")
    f2.metric("Domain", os.getenv("CASE_DOMAIN", "all") or "all")
    f3.metric("Statuses", os.getenv("CASE_STATUSES", "all") or "all")
    f4.metric("Severities", os.getenv("CASE_SEVERITIES", "all") or "all")
    upd = os.getenv("CASE_LAST_UPDATE_HOURS", "")
    cre = os.getenv("CASE_LOOKBACK_HOURS", "")
    window = f"last {upd}h (updated)" if upd else (f"last {cre}h (created)" if cre else "all time")
    f5.metric("Time Window", window)

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
total = len(cases)
by_sev = {}
for c in cases:
    s = (c.get("severity") or "UNKNOWN").upper()
    by_sev[s] = by_sev.get(s, 0) + 1

m0, m1, m2, m3, m4, m5 = st.columns(6)
m0.metric("Total Processed", total)
m1.metric("🔴 Critical", by_sev.get("CRITICAL", 0))
m2.metric("🟠 High",     by_sev.get("HIGH", 0))
m3.metric("🟡 Medium",   by_sev.get("MEDIUM", 0))
m4.metric("🟢 Low",      by_sev.get("LOW", 0))
polls_today = sum(
    1 for p in poll_log
    if p.get("polled_at", "")[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
)
m5.metric("Polls Today", polls_today)

st.divider()

# ---------------------------------------------------------------------------
# Cases table + detail expanders
# ---------------------------------------------------------------------------
if not cases:
    st.info("No cases processed yet. The agent will populate this list after the first poll cycle.")
else:
    st.subheader(f"Processed Cases ({total})")

    # Column headers
    hc = st.columns([1, 4, 1.2, 1.5, 1, 1, 2, 1])
    for col, label in zip(hc, ["ID", "Case Name", "Severity", "Category", "FP Risk", "Priority", "Processed At", "Writes"]):
        col.markdown(f"**{label}**")

    st.markdown('<hr style="margin:4px 0">', unsafe_allow_html=True)

    for case in cases:
        case_id   = case.get("case_id", "")
        name      = case.get("case_name") or "—"
        sev       = (case.get("severity") or "UNKNOWN").upper()
        category  = case.get("category") or "—"
        fp        = (case.get("false_positive_likelihood") or "—").upper()
        priority  = case.get("priority") or "—"
        proc_at   = _fmt_ts(case.get("processed_at", ""))
        wc        = "✅" if case.get("write_comment") else "—"
        wn        = "✅" if case.get("write_notepad") else "—"
        findings  = case.get("findings") or ""
        triage_s  = case.get("triage_summary") or ""

        rc = st.columns([1, 4, 1.2, 1.5, 1, 1, 2, 1])
        rc[0].markdown(f"`{case_id}`")
        rc[1].markdown(name[:60] + ("…" if len(name) > 60 else ""))
        rc[2].markdown(_sev_badge(sev), unsafe_allow_html=True)
        rc[3].markdown(category)
        rc[4].markdown(_fp_badge(fp) if fp != "—" else "—", unsafe_allow_html=True)
        rc[5].markdown(priority)
        rc[6].markdown(proc_at)
        rc[7].markdown(f"💬{wc} 📋{wn}")

        if findings or triage_s:
            with st.expander(f"▶ Case {case_id} — {name[:50]}"):
                if triage_s:
                    st.markdown(f"**Triage Summary:** {triage_s}")
                if findings:
                    st.markdown(findings)

        st.markdown('<hr style="margin:2px 0;opacity:0.2">', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Poll history
# ---------------------------------------------------------------------------
if poll_log:
    st.divider()
    st.subheader("Poll History")
    ph_cols = st.columns([3, 1, 1])
    ph_cols[0].markdown("**Time**")
    ph_cols[1].markdown("**Cases Found**")
    ph_cols[2].markdown("**Processed**")
    for p in poll_log[:10]:
        pc = st.columns([3, 1, 1])
        pc[0].markdown(_fmt_ts(p.get("polled_at", "")))
        pc[1].markdown(str(p.get("cases_found", 0)))
        pc[2].markdown(str(p.get("cases_processed", 0)))
