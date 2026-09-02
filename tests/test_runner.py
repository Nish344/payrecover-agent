from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from payrecover.models import (
    ActionRequest,
    ActionType,
    Case,
    CaseStatus,
    Diagnosis,
    DiagnosisPath,
    GroundTruth,
    PaymentFailure,
)
from payrecover.runner import process_case
from payrecover.store import Store
from tests.fakes import MemoryAudit
from tests.helpers import make_settings


def _diagnose(case: Case) -> Diagnosis:
    return Diagnosis(
        case_id=case.case_id,
        cause=case.failure.error_reason or "unknown",
        confidence=0.9,
        rationale="test",
        path=DiagnosisPath.RULES,
    )


def test_issue_link_then_pay_recovers(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)
    store.save_ground_truth(GroundTruth(case_id="c1", profile="pays_on_first_link"))

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        if case.status == CaseStatus.RECOVERED:
            return ActionRequest.from_policy(
                case_id=case.case_id, action_type=ActionType.STOP, rationale="already_terminal"
            )
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="first link",
            amount_paise=case.failure.amount_paise,
        )

    audit = MemoryAudit()
    finished = process_case(
        case,
        store=store,
        settings=make_settings(),
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=None,
        dry_run=True,
    )
    assert finished.status == CaseStatus.RECOVERED
    types = [event.event_type.value for event in audit.list_for_case("c1")]
    assert "case_detected" in types
    assert "diagnosis_completed" in types
    assert "policy_verdict" in types
    assert "customer_response" in types
    assert "case_terminal" in types
    paid = [event for event in audit.events if event.event_type.value == "customer_response"]
    attempted = [event for event in audit.events if event.event_type.value == "action_attempted"]
    assert paid and attempted
    assert paid[0].correlation_id == attempted[0].correlation_id
    assert paid[0].payload.get("payment_link_id")


def test_rerun_of_recovered_is_noop(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000),
        status=CaseStatus.RECOVERED,
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)
    calls = {"n": 0}

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = case, diagnosis
        calls["n"] += 1
        return ActionRequest.from_policy(
            case_id="c1", action_type=ActionType.ISSUE_LINK, rationale="should not run"
        )

    audit = MemoryAudit()
    finished = process_case(
        case,
        store=store,
        settings=make_settings(),
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=None,
        dry_run=True,
    )
    assert finished.status == CaseStatus.RECOVERED
    assert calls["n"] == 0
    verdicts = [event for event in audit.events if event.event_type.value == "policy_verdict"]
    assert len(verdicts) == 1
    assert verdicts[0].payload.get("rationale") == "already_terminal"
    assert verdicts[0].payload.get("amount_paise") == 10000
    assert "case_detected" not in {event.event_type.value for event in audit.events}


def test_injected_timeout_does_not_increment_link_count(tmp_path: Path) -> None:
    from payrecover.razorpay_client import InjectedTimeoutClient

    store = Store(tmp_path / "t.db")
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="first link",
            amount_paise=case.failure.amount_paise,
        )

    audit = MemoryAudit()
    finished = process_case(
        case,
        store=store,
        settings=make_settings(),
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=InjectedTimeoutClient(),  # type: ignore[arg-type]
        dry_run=False,
    )
    assert finished.link_count == 0
    attempted = [event for event in audit.events if event.event_type.value == "action_attempted"]
    results = [event for event in audit.events if event.event_type.value == "action_result"]
    assert len(attempted) == 1
    assert len(results) == 1
    assert attempted[0].correlation_id == results[0].correlation_id
    assert results[0].payload.get("error_type") == "RazorpayTimeoutError"
    terminals = [event for event in audit.events if event.event_type.value == "case_terminal"]
    assert len(terminals) == 1
    assert terminals[0].payload.get("outcome") == "waiting"
    assert terminals[0].payload.get("reason") == "run_released"
    verdicts = [event for event in audit.events if event.event_type.value == "policy_verdict"]
    assert verdicts[0].payload.get("amount_paise") == 10000


def test_failed_api_write_does_not_retry_in_same_run(tmp_path: Path) -> None:
    from payrecover.razorpay_client import RazorpayAPIError

    store = Store(tmp_path / "t.db")
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)

    class BoomClient:
        calls = 0

        def create_payment_link(self, **kwargs: object) -> dict[str, object]:
            BoomClient.calls += 1
            raise RazorpayAPIError("recurring digits", kind="bad_request")

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="first link",
            amount_paise=case.failure.amount_paise,
        )

    audit = MemoryAudit()
    finished = process_case(
        case,
        store=store,
        settings=make_settings(),
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=BoomClient(),  # type: ignore[arg-type]
        dry_run=False,
    )
    assert BoomClient.calls == 1
    assert finished.link_count == 0
    results = [event for event in audit.events if event.event_type.value == "action_result"]
    assert len(results) == 1
    assert results[0].payload.get("error_type") == "RazorpayAPIError"
    terminals = [event for event in audit.events if event.event_type.value == "case_terminal"]
    assert terminals[-1].payload.get("outcome") == "waiting"


def test_limit_processes_prefix(tmp_path: Path) -> None:
    from payrecover.runner import run_batch
    from payrecover.simulator.batchgen import seed_batch

    settings = make_settings()
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    audit = MemoryAudit()

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.STOP,
            rationale="test stop",
        )

    finished = run_batch(
        store,
        settings=settings,
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=None,
        dry_run=True,
        limit=3,
    )
    assert len(finished) == 3
    open_cases = [case for case in store.list_cases() if case.status == CaseStatus.DETECTED]
    assert len(open_cases) == 77


def test_case_id_filters_to_one(tmp_path: Path) -> None:
    from payrecover.runner import run_batch
    from payrecover.simulator.batchgen import seed_batch

    settings = make_settings()
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    audit = MemoryAudit()

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.STOP,
            rationale="test stop",
        )

    finished = run_batch(
        store,
        settings=settings,
        audit=audit,
        diagnose=_diagnose,
        decide=decide,
        client=None,
        dry_run=True,
        case_id="c42_02",
    )
    assert [case.case_id for case in finished] == ["c42_02"]
    still = [case for case in store.list_cases() if case.status == CaseStatus.DETECTED]
    assert len(still) == 79


def test_unknown_case_id_raises(tmp_path: Path) -> None:
    from payrecover.runner import run_batch
    from payrecover.simulator.batchgen import seed_batch

    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42)
    with pytest.raises(LookupError):
        run_batch(
            store,
            settings=make_settings(),
            audit=MemoryAudit(),
            diagnose=_diagnose,
            decide=lambda case, diagnosis: ActionRequest.from_policy(
                case_id=case.case_id, action_type=ActionType.STOP, rationale="x"
            ),
            client=None,
            case_id="missing",
        )


def test_case_detected_emitted_once_on_rerun(tmp_path: Path) -> None:
    from payrecover.razorpay_client import InjectedTimeoutClient

    store = Store(tmp_path / "t.db")
    case = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)

    def decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        _ = diagnosis
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="first link",
            amount_paise=case.failure.amount_paise,
        )

    audit = MemoryAudit()
    kwargs = {
        "store": store,
        "settings": make_settings(),
        "audit": audit,
        "diagnose": _diagnose,
        "decide": decide,
        "client": InjectedTimeoutClient(),
        "dry_run": False,
    }
    process_case(case, **kwargs)  # type: ignore[arg-type]
    again = store.get_case("c1")
    assert again is not None
    process_case(again, **kwargs)  # type: ignore[arg-type]
    detected = [event for event in audit.events if event.event_type.value == "case_detected"]
    assert len(detected) == 1
