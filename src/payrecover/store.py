from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from payrecover.models import Case, CaseStatus, GroundTruth, PaymentFailure

_CASES_DDL = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    payment_id TEXT,
    order_id TEXT,
    amount_paise INTEGER NOT NULL,
    currency TEXT NOT NULL,
    method TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    error_description TEXT,
    error_reason TEXT,
    error_source TEXT,
    error_step TEXT,
    international INTEGER,
    link_count INTEGER NOT NULL DEFAULT 0,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    opted_out INTEGER NOT NULL DEFAULT 0,
    wait_until TEXT,
    wait_completed INTEGER NOT NULL DEFAULT 0,
    active_payment_link_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_truth (
    case_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    pay_on_reminder INTEGER,
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    seed INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_CASES_DDL)
        from payrecover.audit import ensure_schema

        ensure_schema(self.conn)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def batch_for_seed(self, seed: int) -> str | None:
        row = self.conn.execute("SELECT batch_id FROM batches WHERE seed = ?", (seed,)).fetchone()
        return None if row is None else str(row["batch_id"])

    def record_batch(self, batch_id: str, seed: int) -> None:
        self.conn.execute(
            "INSERT INTO batches (batch_id, seed, created_at) VALUES (?, ?, ?)",
            (batch_id, seed, _iso(datetime.now(UTC))),
        )
        self.conn.commit()

    def case_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()
        return int(row["n"])

    def wipe(self) -> None:
        from payrecover.audit import reset_table

        reset_table(self.conn)
        self.conn.execute("DELETE FROM ground_truth")
        self.conn.execute("DELETE FROM cases")
        self.conn.execute("DELETE FROM batches")
        self.conn.commit()

    def upsert_case(self, case: Case) -> None:
        payload = (
            case.case_id,
            case.failure.payment_id,
            case.failure.order_id,
            case.failure.amount_paise,
            case.failure.currency,
            case.failure.method,
            case.status.value,
            case.failure.error_code,
            case.failure.error_description,
            case.failure.error_reason,
            case.failure.error_source,
            case.failure.error_step,
            None if case.failure.international is None else int(case.failure.international),
            case.link_count,
            case.reminder_count,
            int(case.opted_out),
            None if case.wait_until is None else _iso(case.wait_until),
            int(case.wait_completed),
            case.active_payment_link_id,
            _iso(case.created_at),
        )
        self.conn.execute(
            """
            INSERT INTO cases (
                case_id, payment_id, order_id, amount_paise, currency, method, status,
                error_code, error_description, error_reason, error_source, error_step,
                international, link_count, reminder_count, opted_out, wait_until,
                wait_completed, active_payment_link_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                payment_id = excluded.payment_id,
                order_id = excluded.order_id,
                amount_paise = excluded.amount_paise,
                currency = excluded.currency,
                method = excluded.method,
                status = excluded.status,
                error_code = excluded.error_code,
                error_description = excluded.error_description,
                error_reason = excluded.error_reason,
                error_source = excluded.error_source,
                error_step = excluded.error_step,
                international = excluded.international,
                link_count = excluded.link_count,
                reminder_count = excluded.reminder_count,
                opted_out = excluded.opted_out,
                wait_until = excluded.wait_until,
                wait_completed = excluded.wait_completed,
                active_payment_link_id = excluded.active_payment_link_id
            """,
            payload,
        )
        self.conn.commit()

    def get_case(self, case_id: str) -> Case | None:
        row = self.conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return None if row is None else _case_from_row(row)

    def list_cases(self) -> list[Case]:
        rows = self.conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()
        return [_case_from_row(row) for row in rows]

    def save_ground_truth(self, truth: GroundTruth) -> None:
        self.conn.execute(
            """
            INSERT INTO ground_truth (case_id, profile, pay_on_reminder)
            VALUES (?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                profile = excluded.profile,
                pay_on_reminder = excluded.pay_on_reminder
            """,
            (truth.case_id, truth.profile, truth.pay_on_reminder),
        )
        self.conn.commit()

    def get_ground_truth(self, case_id: str) -> GroundTruth | None:
        row = self.conn.execute(
            "SELECT * FROM ground_truth WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None
        return GroundTruth(
            case_id=str(row["case_id"]),
            profile=str(row["profile"]),
            pay_on_reminder=row["pay_on_reminder"],
        )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _case_from_row(row: sqlite3.Row) -> Case:
    international = row["international"]
    wait_until = row["wait_until"]
    return Case(
        case_id=str(row["case_id"]),
        failure=PaymentFailure(
            payment_id=row["payment_id"],
            order_id=row["order_id"],
            amount_paise=int(row["amount_paise"]),
            currency=row["currency"],
            method=row["method"],
            status="failed",
            error_code=row["error_code"],
            error_description=row["error_description"],
            error_reason=row["error_reason"],
            error_source=row["error_source"],
            error_step=row["error_step"],
            international=None if international is None else bool(international),
        ),
        status=CaseStatus(str(row["status"])),
        link_count=int(row["link_count"]),
        reminder_count=int(row["reminder_count"]),
        opted_out=bool(row["opted_out"]),
        wait_until=None if wait_until is None else _parse_dt(str(wait_until)),
        wait_completed=bool(row["wait_completed"]),
        active_payment_link_id=row["active_payment_link_id"],
        created_at=_parse_dt(str(row["created_at"])),
    )
