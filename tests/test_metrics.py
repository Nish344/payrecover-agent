from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from payrecover.metrics import build_report
from payrecover.models import (
    AuditEvent,
    AuditEventType,
    Case,
    CaseStatus,
    GroundTruth,
    PaymentFailure,
)


def _case(case_id: str, amount: int, status: CaseStatus) -> Case:
    return Case(
        case_id=case_id,
        failure=PaymentFailure(amount_paise=amount),
        status=status,
        created_at=datetime.now(UTC),
    )


def test_link_sent_is_not_recovered(tmp_path: Path) -> None:
    cases = [_case("c1", 10000, CaseStatus.DIAGNOSED)]
    events = [
        AuditEvent(
            event_id="e1",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.ACTION_RESULT,
            payload={"ok": True, "payment_link_id": "plink_x"},
        )
    ]
    path = build_report(cases, events, output_dir=tmp_path)
    body = (tmp_path / "report.json").read_text()
    assert '"recovered_paise": 0' in body
    assert "link sent is not recovered" in path.read_text() or "simulated" in path.read_text()


def test_paid_counts_once(tmp_path: Path) -> None:
    cases = [
        _case("c1", 10000, CaseStatus.RECOVERED),
        _case("c2", 20000, CaseStatus.ESCALATED),
    ]
    events = [
        AuditEvent(
            event_id="e1",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.CUSTOMER_RESPONSE,
            payload={"kind": "paid", "payment_link_id": "plink_x"},
        )
    ]
    build_report(cases, events, output_dir=tmp_path)
    import json

    data = json.loads((tmp_path / "report.json").read_text())
    assert data["recovered_paise"] == 10000
    assert data["at_risk_paise"] == 30000
    assert data["recovery_rate"] == 0.3333
    assert data["outcomes"]["escalated"] == 1


def test_empty_batch_rate_is_zero(tmp_path: Path) -> None:
    build_report([], [], output_dir=tmp_path)
    import json

    data = json.loads((tmp_path / "report.json").read_text())
    assert data["recovery_rate"] == 0.0
    assert data["at_risk_paise"] == 0


def test_paid_without_link_is_not_recovered(tmp_path: Path) -> None:
    cases = [_case("c1", 10000, CaseStatus.WAITING)]
    events = [
        AuditEvent(
            event_id="e1",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.CUSTOMER_RESPONSE,
            payload={"kind": "paid", "payment_link_id": None},
        )
    ]
    build_report(cases, events, output_dir=tmp_path)
    import json

    data = json.loads((tmp_path / "report.json").read_text())
    assert data["recovered_paise"] == 0


def test_escalations_section(tmp_path: Path) -> None:
    cases = [_case("c1", 750000, CaseStatus.ESCALATED)]
    events = [
        AuditEvent(
            event_id="e1",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.DIAGNOSIS_COMPLETED,
            payload={"cause": "insufficient_funds"},
        ),
        AuditEvent(
            event_id="e2",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.POLICY_VERDICT,
            payload={"action_type": "escalate", "rationale": "high_amount"},
        ),
    ]
    path = build_report(cases, events, output_dir=tmp_path)
    import json

    data = json.loads((tmp_path / "report.json").read_text())
    assert data["escalations"][0]["rationale"] == "high_amount"
    assert "Escalations (needs human)" in path.read_text()


def test_capture_rate_is_evaluator_only(tmp_path: Path) -> None:
    cases = [
        _case("c1", 10000, CaseStatus.RECOVERED),
        _case("c2", 20000, CaseStatus.WAITING),
        _case("c3", 30000, CaseStatus.STOPPED),
    ]
    events = [
        AuditEvent(
            event_id="e1",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type=AuditEventType.CUSTOMER_RESPONSE,
            payload={"kind": "paid", "payment_link_id": "plink_x"},
        )
    ]
    truths = {
        "c1": GroundTruth(case_id="c1", profile="pays_on_first_link"),
        "c2": GroundTruth(case_id="c2", profile="pays_if_fast"),
        "c3": GroundTruth(case_id="c3", profile="opts_out"),
    }
    path = build_report(cases, events, output_dir=tmp_path, truths=truths)
    import json

    data = json.loads((tmp_path / "report.json").read_text())
    assert data["capture"]["recoverable_case_count"] == 2
    assert data["capture"]["captured_case_count"] == 1
    assert data["capture"]["capture_rate"] == 0.5
    assert data["capture"]["misses_by_profile"] == {"pays_if_fast": 1}
    text = path.read_text()
    assert "agent is blind" in text
    assert "pays_if_fast: 1" in text
