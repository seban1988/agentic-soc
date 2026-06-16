import sqlite3
import os
from datetime import datetime


DB_PATH = os.getenv("STATE_DB_PATH", "./data/processed_cases.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_cases (
                case_id                  TEXT PRIMARY KEY,
                processed_at             TEXT NOT NULL,
                modification_time        INTEGER NOT NULL,
                case_name                TEXT,
                severity                 TEXT,
                category                 TEXT,
                false_positive_likelihood TEXT,
                priority                 TEXT,
                triage_summary           TEXT,
                findings                 TEXT,
                write_comment            INTEGER DEFAULT 0,
                write_notepad            INTEGER DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS poll_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                polled_at         TEXT NOT NULL,
                cases_found       INTEGER NOT NULL DEFAULT 0,
                cases_processed   INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migrate existing DBs that only have the 3 original columns
        existing = {row[1] for row in c.execute("PRAGMA table_info(processed_cases)")}
        for col, definition in [
            ("case_name",                 "TEXT"),
            ("severity",                  "TEXT"),
            ("category",                  "TEXT"),
            ("false_positive_likelihood", "TEXT"),
            ("priority",                  "TEXT"),
            ("triage_summary",            "TEXT"),
            ("findings",                  "TEXT"),
            ("write_comment",             "INTEGER DEFAULT 0"),
            ("write_notepad",             "INTEGER DEFAULT 0"),
        ]:
            if col not in existing:
                c.execute(f"ALTER TABLE processed_cases ADD COLUMN {col} {definition}")


def is_processed(case_id: str, modification_time: int) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT modification_time FROM processed_cases WHERE case_id = ?",
            (str(case_id),)
        ).fetchone()
    if row is None:
        return False
    return row[0] >= modification_time


def mark_processed(case_id: str, modification_time: int) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO processed_cases (case_id, processed_at, modification_time)
            VALUES (?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                processed_at      = excluded.processed_at,
                modification_time = excluded.modification_time
        """, (str(case_id), datetime.utcnow().isoformat(), modification_time))


def save_case_result(
    case: dict,
    triage: dict,
    findings: str,
    write_comment: bool,
    write_notepad: bool,
) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO processed_cases
                (case_id, processed_at, modification_time, case_name, severity, category,
                 false_positive_likelihood, priority, triage_summary, findings,
                 write_comment, write_notepad)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                processed_at              = excluded.processed_at,
                modification_time         = excluded.modification_time,
                case_name                 = excluded.case_name,
                severity                  = excluded.severity,
                category                  = excluded.category,
                false_positive_likelihood = excluded.false_positive_likelihood,
                priority                  = excluded.priority,
                triage_summary            = excluded.triage_summary,
                findings                  = excluded.findings,
                write_comment             = excluded.write_comment,
                write_notepad             = excluded.write_notepad
        """, (
            str(case["case_id"]),
            datetime.utcnow().isoformat(),
            case.get("modification_time", 0),
            case.get("case_name", ""),
            triage.get("severity", ""),
            triage.get("category", ""),
            triage.get("false_positive_likelihood", ""),
            triage.get("priority", ""),
            triage.get("triage_summary", ""),
            findings,
            int(write_comment),
            int(write_notepad),
        ))


def log_poll(cases_found: int, cases_processed: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO poll_log (polled_at, cases_found, cases_processed) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), cases_found, cases_processed),
        )


def get_recent_cases(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM processed_cases ORDER BY processed_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_poll_log(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM poll_log ORDER BY polled_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def filter_new(cases: list[dict]) -> list[dict]:
    return [
        c for c in cases
        if not is_processed(c["case_id"], c.get("modification_time", 0))
    ]
