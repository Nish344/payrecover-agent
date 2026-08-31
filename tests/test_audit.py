from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from payrecover.audit import SqliteAudit, append, ensure_schema, export_text, list_for_case
from payrecover.models import AuditEvent, AuditEventType
from payrecover.store import Store


def _event(case_id: str = "c1") -> AuditEvent:
    return AuditEvent(
        event_id="e1",
        case_id=case_id,
        ts=datetime.now(UTC),
        event_type=AuditEventType.CASE_DETECTED,
        payload={"payment_id": "pay_x"},
    )


def test_append_and_replay(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    audit = SqliteAudit(store.conn)
    audit.append(_event())
    events = list_for_case(store.conn, "c1")
    assert len(events) == 1
    assert events[0].payload["payment_id"] == "pay_x"
    text = export_text(events)
    assert "IST" in text
    assert "case_detected" in text


def test_update_and_delete_are_aborted(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    ensure_schema(store.conn)
    append(store.conn, _event())
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.conn.execute("UPDATE audit_events SET case_id = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.conn.execute("DELETE FROM audit_events")
