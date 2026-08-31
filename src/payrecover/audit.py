"""Append-only audit writer. Schema: docs/decisions.md Day 1."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from payrecover.models import AuditEvent, AuditEventType

_IST = ZoneInfo("Asia/Kolkata")

_DDL = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    correlation_id TEXT
);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def reset_table(conn: sqlite3.Connection) -> None:
    """Drop + recreate. Used on seed --force; DROP does not row-delete."""
    conn.execute("DROP TABLE IF EXISTS audit_events")
    conn.commit()
    ensure_schema(conn)


def append(conn: sqlite3.Connection, event: AuditEvent) -> None:
    ts = event.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    conn.execute(
        """
        INSERT INTO audit_events (event_id, case_id, ts, event_type, payload, correlation_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.case_id,
            ts.astimezone(UTC).isoformat(),
            event.event_type.value,
            json.dumps(event.payload, default=str),
            event.correlation_id,
        ),
    )
    conn.commit()


def list_for_case(conn: sqlite3.Connection, case_id: str) -> list[AuditEvent]:
    rows = conn.execute(
        """
        SELECT event_id, case_id, ts, event_type, payload, correlation_id
        FROM audit_events
        WHERE case_id = ?
        ORDER BY ts ASC, event_id ASC
        """,
        (case_id,),
    ).fetchall()
    return [_from_row(row) for row in rows]


def list_all(conn: sqlite3.Connection) -> list[AuditEvent]:
    rows = conn.execute(
        """
        SELECT event_id, case_id, ts, event_type, payload, correlation_id
        FROM audit_events
        ORDER BY ts ASC, event_id ASC
        """
    ).fetchall()
    return [_from_row(row) for row in rows]


def export_text(events: list[AuditEvent]) -> str:
    if not events:
        return "(no audit events)"
    lines: list[str] = []
    for event in events:
        local = event.ts.astimezone(_IST).strftime("%Y-%m-%d %H:%M:%S IST")
        corr = f"  corr={event.correlation_id}" if event.correlation_id else ""
        lines.append(f"{local}  {event.event_type.value}  case={event.case_id}{corr}")
        if event.payload:
            lines.append(f"  {json.dumps(event.payload, default=str)}")
    return "\n".join(lines)


def _from_row(row: sqlite3.Row | tuple[object, ...]) -> AuditEvent:
    mapping = row if isinstance(row, sqlite3.Row) else None
    if mapping is not None:
        event_id = str(mapping["event_id"])
        case_id = str(mapping["case_id"])
        ts_raw = str(mapping["ts"])
        event_type = str(mapping["event_type"])
        payload_raw = str(mapping["payload"])
        correlation_id = mapping["correlation_id"]
    else:
        event_id, case_id, ts_raw, event_type, payload_raw, correlation_id = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            row[5],
        )
    payload = json.loads(payload_raw) if payload_raw else {}
    ts = datetime.fromisoformat(ts_raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return AuditEvent(
        event_id=event_id,
        case_id=case_id,
        ts=ts,
        event_type=AuditEventType(event_type),
        payload=payload,
        correlation_id=None if correlation_id is None else str(correlation_id),
    )


class SqliteAudit:
    def __init__(self, conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        self._conn = conn

    def append(self, event: AuditEvent) -> None:
        append(self._conn, event)

    def list_for_case(self, case_id: str) -> list[AuditEvent]:
        return list_for_case(self._conn, case_id)
