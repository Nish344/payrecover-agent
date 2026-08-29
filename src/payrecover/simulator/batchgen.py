from __future__ import annotations

import random
from datetime import UTC, datetime

from payrecover.models import Case, CaseStatus, GroundTruth, PaymentFailure
from payrecover.store import Store

BATCH_SIZE = 80

PROFILE_COUNTS: tuple[tuple[str, int], ...] = (
    ("pays_on_first_link", 16),
    ("pays_after_reminder", 14),
    ("pays_if_fast", 8),
    ("pays_after_wait", 8),
    ("never_pays", 18),
    ("opts_out", 10),
    ("high_value", 6),
)

_CAUSES: tuple[tuple[str, str, bool | None, str, str, str, str], ...] = (
    (
        "international_transaction_not_allowed",
        "card",
        True,
        "BAD_REQUEST_ERROR",
        "business",
        "payment_initiation",
        "This business accepts domestic (Indian) card payments only.",
    ),
    (
        "insufficient_funds",
        "card",
        False,
        "GATEWAY_ERROR",
        "bank",
        "payment_authorization",
        "Payment failed due to insufficient funds.",
    ),
    (
        "bank_downtime",
        "upi",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "The customer's bank is currently unavailable.",
    ),
    (
        "issuer_unavailable",
        "card",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "The card issuer is currently unavailable.",
    ),
    (
        "invalid_otp",
        "upi",
        False,
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authentication",
        "Authentication failed due to incorrect otp.",
    ),
    (
        "ambiguous",
        "card",
        False,
        "BAD_REQUEST_ERROR",
        "unknown",
        "payment_authorization",
        "Payment could not be completed. Please try again.",
    ),
)


def seed_batch(store: Store, *, seed: int) -> str:
    """Create 80 synthetic failed cases. Same seed reproduces the batch."""
    existing = store.batch_for_seed(seed)
    if existing is not None:
        return existing
    rng = random.Random(seed)
    batch_id = f"batch_{seed}"
    profiles = _expand_profiles(rng)
    for index, profile in enumerate(profiles):
        case_id = f"c{seed}_{index:02d}"
        cause = _CAUSES[index % len(_CAUSES)]
        amount = 750000 if profile == "high_value" else rng.randint(10000, 250000)
        pay_on_reminder = None
        if profile == "pays_after_reminder":
            pay_on_reminder = 1 if rng.random() < 0.5 else 2
        failure = PaymentFailure(
            payment_id=f"pay_sim_{case_id}",
            order_id=f"order_sim_{case_id}",
            amount_paise=amount,
            method=cause[1],
            status="failed",
            error_reason=cause[0],
            error_code=cause[3],
            error_source=cause[4],
            error_step=cause[5],
            error_description=cause[6],
            international=cause[2],
        )
        case = Case(
            case_id=case_id,
            failure=failure,
            status=CaseStatus.DETECTED,
            created_at=datetime.now(UTC),
        )
        store.upsert_case(case)
        store.save_ground_truth(
            GroundTruth(case_id=case_id, profile=profile, pay_on_reminder=pay_on_reminder)
        )
    store.record_batch(batch_id, seed)
    return batch_id


def _expand_profiles(rng: random.Random) -> list[str]:
    slots: list[str] = []
    for name, count in PROFILE_COUNTS:
        slots.extend([name] * count)
    if len(slots) != BATCH_SIZE:
        raise RuntimeError("PROFILE_COUNTS must sum to BATCH_SIZE")
    rng.shuffle(slots)
    return slots
