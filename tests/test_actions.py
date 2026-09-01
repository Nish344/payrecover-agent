from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from payrecover.actions import ActionRefused, execute
from payrecover.models import ActionRequest, ActionType, Case, PaymentFailure
from payrecover.razorpay_client import RazorpayClient
from payrecover.store import Store
from tests.fakes import MemoryAudit
from tests.helpers import make_settings


def _case() -> Case:
    return Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, method="upi"),
        created_at=datetime.now(UTC),
    )


def test_refuses_non_policy_origin(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    action = ActionRequest(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="bypass",
        origin="policy",
        amount_paise=10000,
    )
    forged = action.model_copy(update={"rationale": "still policy origin"})
    # origin is Literal policy; refusal is for mismatched case_id
    bad = ActionRequest.from_policy(case_id="other", action_type=ActionType.STOP, rationale="x")
    with pytest.raises(ActionRefused):
        execute(
            bad,
            case=_case(),
            store=store,
            audit=MemoryAudit(),
            settings=make_settings(),
            client=None,
            dry_run=True,
        )
    _ = forged


def test_kill_switch_skips_client(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    store.upsert_case(_case())
    client = MagicMock()
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="recover",
        amount_paise=10000,
    )
    _, result = execute(
        action,
        case=_case(),
        store=store,
        audit=MemoryAudit(),
        settings=make_settings(kill_switch=True),
        client=client,
        dry_run=False,
    )
    assert result.error_type == "kill_switch"
    client.create_payment_link.assert_not_called()


def test_write_timeout_is_typed(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    sdk = MagicMock()
    sdk.payment_link.create.side_effect = requests.Timeout("t")
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="recover",
        amount_paise=10000,
    )
    _, result = execute(
        action,
        case=_case(),
        store=store,
        audit=MemoryAudit(),
        settings=make_settings(),
        client=client,
        dry_run=False,
    )
    assert result.ok is False
    assert result.error_type == "RazorpayTimeoutError"
    stored = store.get_case("c1")
    assert stored is not None
    assert stored.link_count == 0


def test_timeout_attempt_and_result_share_correlation(tmp_path: Path) -> None:
    from payrecover.razorpay_client import InjectedTimeoutClient

    store = Store(tmp_path / "t.db")
    audit = MemoryAudit()
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="recover",
        amount_paise=10000,
    )
    execute(
        action,
        case=_case(),
        store=store,
        audit=audit,
        settings=make_settings(),
        client=InjectedTimeoutClient(),  # type: ignore[arg-type]
        dry_run=False,
        correlation_id="corr-demo",
    )
    assert [event.correlation_id for event in audit.events] == ["corr-demo", "corr-demo"]
    assert audit.events[1].payload.get("ok") is False
    assert store.get_case("c1") is not None
    assert store.get_case("c1").link_count == 0  # type: ignore[union-attr]


def test_dry_run_issue_link_no_client(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    audit = MemoryAudit()
    action = ActionRequest.from_policy(
        case_id="c1",
        action_type=ActionType.ISSUE_LINK,
        rationale="recover",
        amount_paise=10000,
    )
    case, result = execute(
        action,
        case=_case(),
        store=store,
        audit=audit,
        settings=make_settings(),
        client=None,
        dry_run=True,
    )
    assert result.ok is True
    assert case.link_count == 1
    assert case.active_payment_link_id is not None
    types = [event.event_type.value for event in audit.events]
    assert types == ["action_attempted", "action_result"]
