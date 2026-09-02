from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from payrecover.config import Settings
from payrecover.models import (
    ActionRequest,
    ActionResult,
    ActionType,
    AuditEvent,
    AuditEventType,
    AuditSink,
    Case,
    CaseStatus,
)
from payrecover.razorpay_client import RazorpayClient, RazorpayClientError
from payrecover.store import Store

_WAIT_DELTA = timedelta(hours=1)


class ActionRefused(Exception):
    """Raised when execute() is given something policy did not issue."""


def execute(
    action: ActionRequest,
    *,
    case: Case,
    store: Store,
    audit: AuditSink,
    settings: Settings,
    client: RazorpayClient | None,
    dry_run: bool = False,
    correlation_id: str | None = None,
) -> tuple[Case, ActionResult]:
    if action.origin != "policy":
        raise ActionRefused("action was not issued by policy")
    if action.case_id != case.case_id:
        raise ActionRefused("action case_id does not match case")

    correlation_id = correlation_id or uuid.uuid4().hex
    now = datetime.now(UTC)
    audit.append(
        AuditEvent(
            event_id=uuid.uuid4().hex,
            case_id=case.case_id,
            ts=now,
            event_type=AuditEventType.ACTION_ATTEMPTED,
            payload={
                "action_type": action.action_type.value,
                "amount_paise": action.amount_paise,
                "payment_link_id": action.payment_link_id,
                "dry_run": dry_run,
            },
            correlation_id=correlation_id,
        )
    )

    if settings.kill_switch:
        result = ActionResult(
            case_id=case.case_id,
            action_type=action.action_type,
            ok=False,
            error_type="kill_switch",
            detail="KILL_SWITCH is on; no write executed",
        )
        updated = case
    else:
        updated, result = _dispatch(action, case=case, client=client, dry_run=dry_run)

    store.upsert_case(updated)
    audit.append(
        AuditEvent(
            event_id=uuid.uuid4().hex,
            case_id=case.case_id,
            ts=datetime.now(UTC),
            event_type=AuditEventType.ACTION_RESULT,
            payload={
                "ok": result.ok,
                "payment_link_id": result.payment_link_id,
                "error_type": result.error_type,
                "detail": result.detail,
            },
            correlation_id=correlation_id,
        )
    )
    return updated, result


def _dispatch(
    action: ActionRequest,
    *,
    case: Case,
    client: RazorpayClient | None,
    dry_run: bool,
) -> tuple[Case, ActionResult]:
    if action.action_type == ActionType.ISSUE_LINK:
        return _issue_link(action, case=case, client=client, dry_run=dry_run)
    if action.action_type == ActionType.REMIND:
        return _remind(action, case=case, client=client, dry_run=dry_run)
    if action.action_type == ActionType.WAIT:
        waited = case.model_copy(
            update={
                "status": CaseStatus.WAITING,
                "wait_until": action.wait_until or (datetime.now(UTC) + _WAIT_DELTA),
                "wait_completed": True,
            }
        )
        return waited, ActionResult(case_id=case.case_id, action_type=action.action_type, ok=True)
    if action.action_type == ActionType.ESCALATE:
        return (
            case.model_copy(update={"status": CaseStatus.ESCALATED}),
            ActionResult(case_id=case.case_id, action_type=action.action_type, ok=True),
        )
    if action.action_type == ActionType.STOP:
        status = CaseStatus.EXHAUSTED if "exhausted" in action.rationale else CaseStatus.STOPPED
        return (
            case.model_copy(update={"status": status}),
            ActionResult(case_id=case.case_id, action_type=action.action_type, ok=True),
        )
    raise ActionRefused(f"unknown action_type {action.action_type}")


def _issue_link(
    action: ActionRequest,
    *,
    case: Case,
    client: RazorpayClient | None,
    dry_run: bool,
) -> tuple[Case, ActionResult]:
    amount = action.amount_paise if action.amount_paise is not None else case.failure.amount_paise
    if amount != case.failure.amount_paise:
        return case, ActionResult(
            case_id=case.case_id,
            action_type=action.action_type,
            ok=False,
            error_type="amount_mismatch",
            detail="link amount must equal original order amount",
        )
    if case.active_payment_link_id:
        return case, ActionResult(
            case_id=case.case_id,
            action_type=action.action_type,
            ok=True,
            payment_link_id=case.active_payment_link_id,
            detail="idempotent: existing active link reused",
        )
    if dry_run or client is None:
        link_id = f"plink_dry_{case.case_id}_{case.link_count + 1}"
    else:
        try:
            created = client.create_payment_link(
                case_id=case.case_id,
                amount_paise=amount,
                description="PayRecover recovery",
                customer={
                    "name": "PayRecover customer",
                    "email": f"{case.case_id}@payrecover.test",
                    "contact": "+918765432109",
                },
                reference_id=_reference_id(case.case_id, case.link_count + 1),
            )
        except RazorpayClientError as exc:
            return case, ActionResult(
                case_id=case.case_id,
                action_type=action.action_type,
                ok=False,
                error_type=exc.__class__.__name__,
                detail=str(exc),
            )
        link_id = str(created.get("id") or "")
    updated = case.model_copy(
        update={
            "link_count": case.link_count + 1,
            "active_payment_link_id": link_id,
            "status": CaseStatus.DIAGNOSED,
        }
    )
    return updated, ActionResult(
        case_id=case.case_id,
        action_type=action.action_type,
        ok=True,
        payment_link_id=link_id,
    )


def _remind(
    action: ActionRequest,
    *,
    case: Case,
    client: RazorpayClient | None,
    dry_run: bool,
) -> tuple[Case, ActionResult]:
    link_id = action.payment_link_id or case.active_payment_link_id
    if not link_id:
        return case, ActionResult(
            case_id=case.case_id,
            action_type=action.action_type,
            ok=False,
            error_type="no_link",
            detail="cannot remind without an active payment link",
        )
    if not dry_run and client is not None:
        try:
            client.notify_payment_link(
                case_id=case.case_id, payment_link_id=link_id, medium="email"
            )
        except RazorpayClientError as exc:
            return case, ActionResult(
                case_id=case.case_id,
                action_type=action.action_type,
                ok=False,
                payment_link_id=link_id,
                error_type=exc.__class__.__name__,
                detail=str(exc),
            )
    updated = case.model_copy(update={"reminder_count": case.reminder_count + 1})
    return updated, ActionResult(
        case_id=case.case_id,
        action_type=action.action_type,
        ok=True,
        payment_link_id=link_id,
    )


def _reference_id(case_id: str, attempt: int) -> str:
    raw = f"pr_{case_id}_{attempt}"
    return raw[:40]
