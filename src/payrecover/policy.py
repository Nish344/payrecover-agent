"""Policy engine. Caps and first-match precedence live only here."""

from __future__ import annotations

from payrecover.models import ActionRequest, ActionType, Case, CaseStatus, Diagnosis

MAX_LINKS = 2
MAX_REMINDERS = 3
ESCALATE_AMOUNT_PAISE = 500_000  # ₹5,000; escalate when strictly greater
MIN_CONFIDENCE = 0.6
_TRANSIENT_CAUSES = frozenset({"bank_downtime", "issuer_unavailable"})
_TERMINAL = {
    CaseStatus.RECOVERED,
    CaseStatus.STOPPED,
    CaseStatus.ESCALATED,
    CaseStatus.EXHAUSTED,
}


def decide(case: Case, diagnosis: Diagnosis, *, kill_switch: bool) -> ActionRequest:
    if kill_switch:
        return _stop(case, "kill_switch")
    if case.opted_out:
        return _stop(case, "opt_out")
    if case.status in _TERMINAL:
        return _stop(case, "already_terminal")
    if case.failure.amount_paise > ESCALATE_AMOUNT_PAISE:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="high_amount",
        )
    if diagnosis.cause == "ambiguous":
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="ambiguous",
        )
    if diagnosis.confidence < MIN_CONFIDENCE:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="low_confidence",
        )
    if diagnosis.cause in _TRANSIENT_CAUSES and not case.wait_completed:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.WAIT,
            rationale="transient_rail",
        )
    if case.active_payment_link_id is None and case.link_count < MAX_LINKS:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="issue_link",
            amount_paise=case.failure.amount_paise,
        )
    if case.active_payment_link_id is not None and case.reminder_count < MAX_REMINDERS:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.REMIND,
            rationale="remind",
            payment_link_id=case.active_payment_link_id,
        )
    return _stop(case, "exhausted")


def _stop(case: Case, reason: str) -> ActionRequest:
    return ActionRequest.from_policy(
        case_id=case.case_id,
        action_type=ActionType.STOP,
        rationale=reason,
    )
