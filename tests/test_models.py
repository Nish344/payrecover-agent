from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from payrecover.models import (
    ActionRequest,
    ActionType,
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
