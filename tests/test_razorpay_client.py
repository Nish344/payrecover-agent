from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from payrecover.razorpay_client import (
    RazorpayAPIError,
    RazorpayAuthError,
    RazorpayClient,
    RazorpayTimeoutError,
)
from tests.helpers import make_settings


def _sdk(
    *,
    payment_all: Any = None,
    payment_link_create: Any = None,
    payment_link_notify: Any = None,
) -> MagicMock:
    sdk = MagicMock()
    if payment_all is not None:
        sdk.payment.all.side_effect = payment_all
    if payment_link_create is not None:
        sdk.payment_link.create.side_effect = payment_link_create
    if payment_link_notify is not None:
        sdk.payment_link.notifyBy.side_effect = payment_link_notify
    return sdk


def test_refuses_live_keys() -> None:
    settings = make_settings(razorpay_key_id="rzp_live_should_not_work")
    with pytest.raises(RazorpayAuthError, match="non-test"):
        RazorpayClient(settings)


def test_read_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    sdk = _sdk(
        payment_all=[
            requests.Timeout("t1"),
            requests.Timeout("t2"),
            {"entity": "collection", "count": 0, "items": []},
        ]
    )
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=sleeps.append)
    result = client.list_payments(count=1)
    assert result["count"] == 0
    assert sdk.payment.all.call_count == 3
    assert sleeps == [0.5, 1.0]


def test_write_timeout_is_not_retried() -> None:
    sdk = _sdk(payment_link_create=[requests.Timeout("create timed out")])
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    with pytest.raises(RazorpayTimeoutError):
        client.create_payment_link(
            case_id="case-1",
            amount_paise=10000,
            description="recovery",
            customer={"email": "a@example.com", "contact": "+919999999999", "name": "A"},
            reference_id="pr_case-1_1",
        )
    assert sdk.payment_link.create.call_count == 1


def test_write_embeds_case_id() -> None:
    sdk = _sdk(payment_link_create=[{"id": "plink_x"}])
    sdk.payment_link.create.side_effect = None
    sdk.payment_link.create.return_value = {"id": "plink_x"}
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    client.create_payment_link(
        case_id="case-9",
        amount_paise=2500,
        description="recovery",
        customer={"email": "a@example.com", "contact": "+919999999999", "name": "A"},
        reference_id="pr_case-9_1",
    )
    payload = sdk.payment_link.create.call_args.args[0]
    assert payload["notes"]["case_id"] == "case-9"
    assert payload["reference_id"] == "pr_case-9_1"
    assert payload["amount"] == 2500
    assert payload["accept_partial"] is False


def test_timeout_message_does_not_include_secret(caplog: pytest.LogCaptureFixture) -> None:
    sdk = _sdk(payment_all=[requests.Timeout("rzp_test_dummykeyid leaked?")])
    client = RazorpayClient(make_settings(razorpay_read_retries=1), sdk=sdk, sleep=lambda _: None)
    with caplog.at_level("WARNING"), pytest.raises(RazorpayTimeoutError) as exc_info:
        client.list_payments(count=1)
    assert "test_secret" not in str(exc_info.value)
    assert "test_secret" not in caplog.text


def test_bad_request_is_api_error() -> None:
    from razorpay.errors import BadRequestError

    sdk = _sdk(payment_all=[BadRequestError("id is invalid")])
    client = RazorpayClient(make_settings(razorpay_read_retries=3), sdk=sdk, sleep=lambda _: None)
    with pytest.raises(RazorpayAPIError) as exc_info:
        client.list_payments(count=1)
    assert exc_info.value.kind == "bad_request"
    assert sdk.payment.all.call_count == 1
