from __future__ import annotations

from pathlib import Path

from payrecover.simulator.batchgen import BATCH_SIZE, PROFILE_COUNTS, seed_batch
from payrecover.store import Store


def test_same_seed_reproduces_profiles(tmp_path: Path) -> None:
    store_a = Store(tmp_path / "a.db")
    store_b = Store(tmp_path / "b.db")
    seed_batch(store_a, seed=7)
    seed_batch(store_b, seed=7)
    ids_a = [case.case_id for case in store_a.list_cases()]
    ids_b = [case.case_id for case in store_b.list_cases()]
    assert ids_a == ids_b
    profiles_a = [store_a.get_ground_truth(cid).profile for cid in ids_a]  # type: ignore[union-attr]
    profiles_b = [store_b.get_ground_truth(cid).profile for cid in ids_b]  # type: ignore[union-attr]
    assert profiles_a == profiles_b


def test_batch_size_and_mix(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    assert store.case_count() == BATCH_SIZE
    counts: dict[str, int] = {}
    leaked = False
    for case in store.list_cases():
        dumped = case.model_dump()
        leaked = leaked or "profile" in dumped or "ground_truth" in dumped
        truth = store.get_ground_truth(case.case_id)
        assert truth is not None
        counts[truth.profile] = counts.get(truth.profile, 0) + 1
    assert leaked is False
    expected = dict(PROFILE_COUNTS)
    assert counts == expected
    high = [
        case
        for case in store.list_cases()
        if store.get_ground_truth(case.case_id).profile == "high_value"  # type: ignore[union-attr]
    ]
    assert all(case.failure.amount_paise > 500000 for case in high)


def test_generic_failure_bucket_is_not_the_word_ambiguous(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    generic = [case for case in store.list_cases() if not (case.failure.error_reason or "").strip()]
    assert generic
    assert all(case.failure.error_reason != "ambiguous" for case in store.list_cases())


def test_seed_is_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    first = seed_batch(store, seed=1)
    second = seed_batch(store, seed=1)
    assert first == second
    assert store.case_count() == BATCH_SIZE
