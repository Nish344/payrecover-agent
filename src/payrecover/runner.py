from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from payrecover.actions import execute
from payrecover.config import Settings
from payrecover.models import (
    ActionRequest,
    AuditEvent,
    AuditEventType,
    AuditSink,
    Case,
    CaseStatus,
    Diagnosis,
    Outcome,
)
from payrecover.razorpay_client import RazorpayClient
from payrecover.simulator.customer import respond
from payrecover.store import Store

DiagnoseFn = Callable[[Case], Diagnosis]
DecideFn = Callable[[Case, Diagnosis], ActionRequest]

_TERMINAL = {
    CaseStatus.RECOVERED,
    CaseStatus.STOPPED,
    CaseStatus.ESCALATED,
    CaseStatus.EXHAUSTED,
}


def run_batch(
    store: Store,
    *,
    settings: Settings,
    audit: AuditSink,
    diagnose: DiagnoseFn,
    decide: DecideFn,
    client: RazorpayClient | None,
    dry_run: bool = True,
    max_steps: int = 8,
    limit: int | None = None,
    case_id: str | None = None,
) -> list[Case]:
    finished: list[Case] = []
    cases = store.list_cases()
    if case_id is not None:
        cases = [case for case in cases if case.case_id == case_id]
        if not cases:
            raise LookupError(case_id)
    if limit is not None:
        cases = cases[:limit]
    for case in cases:
        finished.append(
            process_case(
                case,
                store=store,
                settings=settings,
                audit=audit,
                diagnose=diagnose,
                decide=decide,
                client=client,
                dry_run=dry_run,
                max_steps=max_steps,
            )
        )
    return finished


def process_case(
    case: Case,
    *,
    store: Store,
    settings: Settings,
    audit: AuditSink,
    diagnose: DiagnoseFn,
    decide: DecideFn,
    client: RazorpayClient | None,
    dry_run: bool = False,
    max_steps: int = 8,
) -> Case:
    if case.status in _TERMINAL:
        return case
    current = case
    _append(
        audit,
        current.case_id,
        AuditEventType.CASE_DETECTED,
        {
            "payment_id": current.failure.payment_id,
            "order_id": current.failure.order_id,
            "amount_paise": current.failure.amount_paise,
            "method": current.failure.method,
            "error_reason": current.failure.error_reason,
            "error_source": current.failure.error_source,
            "error_step": current.failure.error_step,
            "error_code": current.failure.error_code,
        },
    )
    for _ in range(max_steps):
        if current.status in _TERMINAL:
            return current
        diagnosis = diagnose(current)
        correlation_id = uuid.uuid4().hex
        _append(
            audit,
            current.case_id,
            AuditEventType.DIAGNOSIS_COMPLETED,
            {
                "cause": diagnosis.cause,
                "confidence": diagnosis.confidence,
                "rationale": diagnosis.rationale,
                "path": diagnosis.path.value,
                "model": diagnosis.model,
            },
            correlation_id=correlation_id,
        )
        action = decide(current, diagnosis)
        _append(
            audit,
            current.case_id,
            AuditEventType.POLICY_VERDICT,
            {
                "action_type": action.action_type.value,
                "rationale": action.rationale,
                "link_count": current.link_count,
                "reminder_count": current.reminder_count,
                "kill_switch": settings.kill_switch,
            },
            correlation_id=correlation_id,
        )
        current, result = execute(
            action,
            case=current,
            store=store,
            audit=audit,
            settings=settings,
            client=client,
            dry_run=dry_run,
            correlation_id=correlation_id,
        )
        if result.error_type == "kill_switch":
            current = current.model_copy(update={"status": CaseStatus.STOPPED})
            store.upsert_case(current)
        if not result.ok and current.status not in _TERMINAL:
            return current
        truth = store.get_ground_truth(current.case_id)
        if truth is not None and result.ok:
            response = respond(current, action, truth)
            payload: dict[str, object] = {
                "kind": response.kind,
                "payment_link_id": response.payment_link_id,
            }
            _append(
                audit,
                current.case_id,
                AuditEventType.CUSTOMER_RESPONSE,
                payload,
                correlation_id=correlation_id,
            )
            if response.kind == "opted_out":
                current = current.model_copy(update={"opted_out": True})
                store.upsert_case(current)
            elif response.kind == "paid" and response.payment_link_id:
                current = current.model_copy(update={"status": CaseStatus.RECOVERED})
                store.upsert_case(current)
        if current.status in _TERMINAL:
            _append(
                audit,
                current.case_id,
                AuditEventType.CASE_TERMINAL,
                {"outcome": _outcome(current).value},
                correlation_id=correlation_id,
            )
            return current
    return current


def _outcome(case: Case) -> Outcome:
    return {
        CaseStatus.RECOVERED: Outcome.RECOVERED,
        CaseStatus.ESCALATED: Outcome.ESCALATED,
        CaseStatus.STOPPED: Outcome.STOPPED_BY_POLICY,
        CaseStatus.EXHAUSTED: Outcome.EXHAUSTED,
        CaseStatus.WAITING: Outcome.WAITING,
    }.get(case.status, Outcome.WAITING)


def _append(
    audit: AuditSink,
    case_id: str,
    event_type: AuditEventType,
    payload: dict[str, object],
    correlation_id: str | None = None,
) -> None:
    audit.append(
        AuditEvent(
            event_id=uuid.uuid4().hex,
            case_id=case_id,
            ts=datetime.now(UTC),
            event_type=event_type,
            payload=payload,
            correlation_id=correlation_id,
        )
    )
