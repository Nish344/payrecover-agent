from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from payrecover.models import Case, CaseStatus, PaymentFailure
from payrecover.store import Store

_TERMINAL = {
    CaseStatus.RECOVERED,
    CaseStatus.STOPPED,
    CaseStatus.ESCALATED,
    CaseStatus.EXHAUSTED,
}


def case_from_payment(payload: Mapping[str, Any], *, case_id: str) -> Case:
    """Normalize a Razorpay payment dict into an agent-visible Case."""
    card = payload.get("card") if isinstance(payload.get("card"), dict) else {}
    international = payload.get("international")
    if international is None and isinstance(card, dict):
        international = card.get("international")
    return Case(
        case_id=case_id,
        failure=PaymentFailure(
            payment_id=payload.get("id"),
            order_id=payload.get("order_id"),
            amount_paise=int(payload.get("amount") or 0),
            currency=str(payload.get("currency") or "INR"),
            method=payload.get("method"),
            status=payload.get("status"),
            error_code=payload.get("error_code"),
            error_description=payload.get("error_description"),
            error_reason=payload.get("error_reason"),
            error_source=payload.get("error_source"),
            error_step=payload.get("error_step"),
            international=None if international is None else bool(international),
        ),
        status=CaseStatus.DETECTED,
        created_at=datetime.now(UTC),
    )


def ingest_failed_payments(store: Store, payments: list[Mapping[str, Any]]) -> list[Case]:
    """Turn Razorpay payment objects into cases. Non-failed rows are ignored."""
    ingested: list[Case] = []
    for payload in payments:
        if str(payload.get("status") or "") != "failed":
            continue
        payment_id = str(payload.get("id") or "").strip()
        if not payment_id:
            continue
        case = case_from_payment(payload, case_id=f"rzp_{payment_id}")
        ingested.append(upsert_detected(store, case))
    return ingested


def upsert_detected(store: Store, case: Case) -> Case:
    """Idempotent: same case_id keeps terminal/in-progress state on re-detect."""
    existing = store.get_case(case.case_id)
    if existing is None:
        store.upsert_case(case)
        return case
    if existing.status in _TERMINAL:
        return existing
    merged = existing.model_copy(
        update={
            "failure": case.failure,
        }
    )
    store.upsert_case(merged)
    return merged
