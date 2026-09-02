from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from payrecover.detector import case_from_payment, ingest_failed_payments, upsert_detected
from payrecover.models import Case, CaseStatus, PaymentFailure
from payrecover.store import Store


def test_case_from_payment_maps_reason_and_international() -> None:
    case = case_from_payment(
        {
            "id": "pay_TVGlLnELbwZeV2",
            "order_id": "order_x",
            "amount": 10000,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "international": True,
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "international_transaction_not_allowed",
            "error_source": "business",
            "error_step": "payment_initiation",
            "error_description": "domestic cards only",
        },
        case_id="c1",
    )
    assert case.failure.error_reason == "international_transaction_not_allowed"
    assert case.failure.international is True
    assert case.failure.error_code == "BAD_REQUEST_ERROR"


def test_redetect_does_not_reset_terminal(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    existing = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=100, payment_id="pay_1"),
        status=CaseStatus.RECOVERED,
        created_at=datetime.now(UTC),
    )
    store.upsert_case(existing)
    incoming = case_from_payment({"id": "pay_1", "amount": 100, "status": "failed"}, case_id="c1")
    result = upsert_detected(store, incoming)
    assert result.status == CaseStatus.RECOVERED


def test_ingest_skips_non_failed_and_uses_rzp_prefix(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    ingested = ingest_failed_payments(
        store,
        [
            {"id": "pay_ok", "status": "captured", "amount": 10000},
            {
                "id": "pay_fail",
                "status": "failed",
                "amount": 5000,
                "error_reason": "insufficient_funds",
            },
            {"id": "", "status": "failed", "amount": 100},
        ],
    )
    assert [case.case_id for case in ingested] == ["rzp_pay_fail"]
    stored = store.get_case("rzp_pay_fail")
    assert stored is not None
    assert stored.failure.payment_id == "pay_fail"
    assert stored.failure.error_reason == "insufficient_funds"
