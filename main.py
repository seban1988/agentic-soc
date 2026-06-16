"""
Agentic SOC — main entrypoint.

Usage:
  python main.py                        # continuous polling every 5 min
  python main.py --run-once             # single poll + process, then exit
  python main.py --case-id 88921        # process one case by ID
  python main.py --case-id 88921 --dry-run  # dry run: print findings, no XSIAM write
"""

import argparse
import json
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# Configure logging before any local imports
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agentic-soc")

from scheduler.state import init_db, mark_processed, save_case_result, log_poll
from scheduler.poll import poll_new_cases, mcp_init, mcp_call, get_case_by_id_rest
from agent.triage_agent import triage_case
from agent.investigation_agent import investigate_case
from agent.writer_agent import write_findings


POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))


# ---------------------------------------------------------------------------
# Core processing pipeline
# ---------------------------------------------------------------------------

def process_case(case: dict, dry_run: bool = False) -> None:
    case_id = case["case_id"]
    logger.info("=== Processing case %s: %s ===", case_id, case.get("case_name", ""))

    # Step 1: Triage
    try:
        triage = triage_case(case)
    except Exception as exc:
        logger.error("Triage failed for case %s: %s", case_id, exc)
        return

    # Skip confirmed false positives
    if not triage.get("requires_investigation", True):
        logger.info(
            "Case %s skipped — triage classified as high-confidence FP (%s)",
            case_id, triage.get("false_positive_reasoning", "")
        )
        mark_processed(case_id, case.get("modification_time", 0))
        return

    # Step 2: Investigation
    try:
        findings = investigate_case(case, triage)
    except Exception as exc:
        logger.error("Investigation failed for case %s: %s", case_id, exc)
        return

    # Step 3: Write findings
    write_comment, write_notepad = False, False
    if dry_run:
        print(f"\n{'='*70}")
        print(f"DRY RUN — Case {case_id}: {case.get('case_name')}")
        print(f"{'='*70}")
        print(f"TRIAGE: {json.dumps(triage, indent=2)}")
        print(f"\nFINDINGS:\n{findings}")
        print(f"{'='*70}\n")
    else:
        try:
            write_result = write_findings(case, triage, findings)
            write_comment = write_result.get("comment", False)
            write_notepad = write_result.get("notepad", False)
        except Exception as exc:
            logger.error("Write failed for case %s: %s", case_id, exc)
            return

    save_case_result(case, triage, findings, write_comment, write_notepad)
    mark_processed(case_id, case.get("modification_time", 0))
    logger.info("Case %s complete.", case_id)


# ---------------------------------------------------------------------------
# Single-case mode (--case-id)
# ---------------------------------------------------------------------------

def run_single_case(case_id: str, dry_run: bool) -> None:
    logger.info("Single-case mode: fetching case %s", case_id)
    try:
        case = get_case_by_id_rest(case_id)
    except Exception as exc:
        logger.error("Could not fetch case %s: %s", case_id, exc)
        sys.exit(1)

    if not case:
        logger.error("Case %s not found", case_id)
        sys.exit(1)

    # Enrich with issues via MCP
    try:
        session = mcp_init()
        issues = mcp_call(session, "get_issues", {
            "filters": [{"field": "id", "operator": "in", "value": [int(case_id)]}],
            "search_from": 0, "search_to": 100,
        }, req_id=3)
        case["_issues"] = issues.get("reply", {}).get("DATA", [])
    except Exception as exc:
        logger.warning("Could not fetch issues for case %s (continuing): %s", case_id, exc)
        case["_issues"] = []

    process_case(case, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Poll-and-process loop
# ---------------------------------------------------------------------------

def run_poll(dry_run: bool = False) -> None:
    cases = poll_new_cases()
    processed = 0
    for case in cases:
        try:
            process_case(case, dry_run=dry_run)
            processed += 1
        except Exception as exc:
            logger.error("Unexpected error processing case %s: %s", case.get("case_id"), exc)
    log_poll(cases_found=len(cases), cases_processed=processed)
    if not cases:
        logger.info("No new cases this cycle.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic SOC Investigator")
    parser.add_argument("--run-once", action="store_true", help="Poll once and exit")
    parser.add_argument("--case-id", help="Process a single case ID")
    parser.add_argument("--dry-run", action="store_true", help="Print findings, do not write to XSIAM")
    args = parser.parse_args()

    init_db()
    logger.info("Agentic SOC started. Poll interval: %ds", POLL_INTERVAL)

    if args.case_id:
        run_single_case(args.case_id, dry_run=args.dry_run)
        return

    if args.run_once:
        run_poll(dry_run=args.dry_run)
        return

    # Continuous polling loop
    try:
        while True:
            logger.info("--- Poll cycle starting ---")
            try:
                run_poll()
            except Exception as exc:
                logger.error("Poll cycle error: %s", exc)
            logger.info("--- Poll cycle done. Sleeping %ds ---", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
