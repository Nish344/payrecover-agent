from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from payrecover.models import (
    ActionRequest,
    ActionType,
    AuditEvent,
    AuditEventType,
    Case,
    CaseStatus,
    PaymentFailure,
    paise_to_inr,
)


def test_paise_to_inr() -> None:
    assert paise_to_inr(50000) == "₹500.00"
    assert paise_to_inr(101) == "₹1.01"


def test_case_has_no_ground_truth_field() -> None:
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=100, method="upi"),
        status=CaseStatus.DETECTED,
        created_at=datetime.now(UTC),
    )
    assert case.case_id == "c1"
    assert "ground_truth" not in Case.model_fields
    assert "profile" not in Case.model_fields


def test_action_request_from_policy() -> None:
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="first recovery attempt",
        amount_paise=100,
    )
    assert action.origin == "policy"


def test_action_request_is_frozen() -> None:
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.STOP,
        rationale="opt-out",
    )
    with pytest.raises(ValidationError):
        action.rationale = "mutated"  # type: ignore[misc]


def test_audit_event_requires_known_type() -> None:
    event = AuditEvent(
        event_id="e1",
        case_id="c1",
        ts=datetime.now(UTC),
        event_type=AuditEventType.CASE_DETECTED,
        payload={"payment_id": "pay_x"},
        correlation_id=None,
    )
    assert event.event_type == AuditEventType.CASE_DETECTED
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="e2",
            case_id="c1",
            ts=datetime.now(UTC),
            event_type="not_a_real_type",  # type: ignore[arg-type]
        )


def test_payment_failure_keeps_international_flag() -> None:
    failure = PaymentFailure(
        payment_id="pay_TVGlLnELbwZeV2",
        amount_paise=10000,
        method="card",
        error_reason="international_transaction_not_allowed",
        international=True,
    )
    assert failure.international is True
