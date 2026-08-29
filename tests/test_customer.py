from __future__ import annotations

from datetime import UTC, datetime

from payrecover.models import ActionRequest, ActionType, Case, GroundTruth, PaymentFailure
from payrecover.simulator.customer import respond


def _case(**updates: object) -> Case:
    base = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000),
        created_at=datetime.now(UTC),
        active_payment_link_id="plink_x",
    )
    return base.model_copy(update=updates) if updates else base


def _link() -> ActionRequest:
    return ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="r",
        amount_paise=10000,
        payment_link_id="plink_x",
    )


def test_opts_out_once() -> None:
    truth = GroundTruth(case_id="c1", profile="opts_out")
    first = respond(_case(), _link(), truth)
    assert first.kind == "opted_out"
    second = respond(_case(opted_out=True), _link(), truth)
    assert second.kind == "ignored"


def test_pays_on_first_link() -> None:
    truth = GroundTruth(case_id="c1", profile="pays_on_first_link")
    assert respond(_case(), _link(), truth).kind == "paid"


def test_pays_after_nth_reminder() -> None:
    truth = GroundTruth(case_id="c1", profile="pays_after_reminder", pay_on_reminder=2)
    remind = ActionRequest.from_policy(
        case_id="c1", action_type=ActionType.REMIND, rationale="r", payment_link_id="plink_x"
    )
    assert respond(_case(reminder_count=1), remind, truth).kind == "ignored"
    assert respond(_case(reminder_count=2), remind, truth).kind == "paid"


def test_pays_after_wait() -> None:
    truth = GroundTruth(case_id="c1", profile="pays_after_wait")
    wait = ActionRequest.from_policy(case_id="c1", action_type=ActionType.WAIT, rationale="r")
    assert respond(_case(), _link(), truth).kind == "ignored"
    assert respond(_case(), wait, truth).kind == "paid"
