from __future__ import annotations

from pathlib import Path

from payrecover.audit import SqliteAudit, list_all
from payrecover.diagnosis import diagnose
from payrecover.metrics import build_report
from payrecover.policy import decide
from payrecover.runner import run_batch
from payrecover.simulator.batchgen import seed_batch
from payrecover.store import Store
from tests.helpers import make_settings


def test_seed_run_report_dry(tmp_path: Path) -> None:
    settings = make_settings()
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    assert store.case_count() == 80

    def _diagnose(case):  # type: ignore[no-untyped-def]
        return diagnose(case, settings=settings)

    def _decide(case, diagnosis):  # type: ignore[no-untyped-def]
        return decide(case, diagnosis, kill_switch=False)

    audit = SqliteAudit(store.conn)
    finished = run_batch(
        store,
        settings=settings,
        audit=audit,
        diagnose=_diagnose,
        decide=_decide,
        client=None,
        dry_run=True,
    )
    assert len(finished) == 80
    recovered = [case for case in store.list_cases() if case.status.value == "recovered"]
    escalated = [case for case in store.list_cases() if case.status.value == "escalated"]
    assert len(recovered) > 0
    assert len(escalated) >= 6
    events = list_all(store.conn)
    assert events
    path = build_report(store.list_cases(), events, output_dir=tmp_path / "reports")
    assert path.exists()
    rerun = run_batch(
        store,
        settings=settings,
        audit=audit,
        diagnose=_diagnose,
        decide=_decide,
        client=None,
        dry_run=True,
    )
    recovered_again = [case for case in rerun if case.status.value == "recovered"]
    assert len(recovered_again) == len(recovered)
