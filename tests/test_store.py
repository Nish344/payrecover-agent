from __future__ import annotations

from datetime import UTC, datetime

from payrecover.models import Case, CaseStatus, GroundTruth, PaymentFailure
from payrecover.store import Store


def test_upsert_and_reload(tmp_path: object) -> None:
    from pathlib import Path

    store = Store(Path(tmp_path) / "t.db")  # type: ignore[arg-type]
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, method="upi"),
        status=CaseStatus.DETECTED,
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)
    loaded = store.get_case("c1")
    assert loaded is not None
    assert loaded.failure.amount_paise == 10000
    assert "ground_truth" not in loaded.model_dump()


def test_ground_truth_is_separate(tmp_path: object) -> None:
    from pathlib import Path

    store = Store(Path(tmp_path) / "t.db")  # type: ignore[arg-type]
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=100),
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)
    store.save_ground_truth(GroundTruth(case_id="c1", profile="never_pays"))
    assert store.get_case("c1") is not None
    assert store.get_ground_truth("c1") is not None
    assert store.get_ground_truth("c1").profile == "never_pays"  # type: ignore[union-attr]
