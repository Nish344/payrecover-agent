"""Append-only audit writer — implement from docs/decisions.md (Day 1, Audit schema).

Table audit_events, INSERT only, BEFORE UPDATE/DELETE triggers, UTC timestamps.
"""

from __future__ import annotations

import sqlite3

from payrecover.models import AuditEvent


def ensure_schema(conn: sqlite3.Connection) -> None:
    raise NotImplementedError(
        "Create audit_events plus abort triggers. See docs/decisions.md Day 1."
    )


def append(conn: sqlite3.Connection, event: AuditEvent) -> None:
    raise NotImplementedError("INSERT one audit_events row. Never UPDATE or DELETE.")


def list_for_case(conn: sqlite3.Connection, case_id: str) -> list[AuditEvent]:
    raise NotImplementedError("SELECT * FROM audit_events WHERE case_id = ? ORDER BY ts, event_id.")


def export_text(events: list[AuditEvent]) -> str:
    raise NotImplementedError("Human-readable IST export for the demo.")
