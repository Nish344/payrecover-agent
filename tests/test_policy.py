from __future__ import annotations

from datetime import UTC, datetime

from payrecover.models import (
    ActionType,
    Case,
    CaseStatus,
    Diagnosis,
    DiagnosisPath,
    PaymentFailure,
)
from payrecover.policy import decide


def _case(**updates: object) -> Case:
    base = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    return base.model_copy(update=updates) if updates else base


def _diag(*, confidence: float = 0.9, cause: str = "insufficient_funds") -> Diagnosis:
    return Diagnosis(
        case_id="c1",
        cause=cause,
        confidence=confidence,
        rationale="t",
        path=DiagnosisPath.RULES,
    )


def test_kill_switch_wins() -> None:
    action = decide(_case(opted_out=True), _diag(), kill_switch=True)
    assert action.action_type == ActionType.STOP
    assert action.rationale == "kill_switch"
    assert action.origin == "policy"


def test_opt_out() -> None:
    action = decide(_case(opted_out=True), _diag(), kill_switch=False)
    assert action.rationale == "opt_out"


def test_high_amount_beats_high_confidence() -> None:
    case = _case(failure=PaymentFailure(amount_paise=750000, error_reason="insufficient_funds"))
    action = decide(case, _diag(confidence=0.99), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "high_amount"


def test_low_confidence_escalates() -> None:
    action = decide(_case(), _diag(confidence=0.59), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "low_confidence"


def test_ambiguous_never_reaches_an_action() -> None:
    action = decide(_case(), _diag(confidence=0.9, cause="ambiguous"), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "ambiguous"


def test_wait_then_link() -> None:
    waiting = decide(_case(), _diag(cause="bank_downtime"), kill_switch=False)
    assert waiting.action_type == ActionType.WAIT
    after = decide(_case(wait_completed=True), _diag(cause="bank_downtime"), kill_switch=False)
    assert after.action_type == ActionType.ISSUE_LINK
    assert after.amount_paise == 10000


def test_remind_then_exhaust() -> None:
    linked = _case(active_payment_link_id="plink_1", link_count=1, reminder_count=0)
    remind = decide(linked, _diag(), kill_switch=False)
    assert remind.action_type == ActionType.REMIND
    exhausted = decide(
        linked.model_copy(update={"reminder_count": 3}),
        _diag(),
        kill_switch=False,
    )
    assert exhausted.action_type == ActionType.STOP
    assert exhausted.rationale == "exhausted"


def test_already_terminal_is_noop() -> None:
    action = decide(_case(status=CaseStatus.RECOVERED), _diag(), kill_switch=False)
    assert action.rationale == "already_terminal"


def test_no_second_live_link() -> None:
    case = _case(active_payment_link_id="plink_1", link_count=1)
    action = decide(case, _diag(), kill_switch=False)
    assert action.action_type == ActionType.REMIND
