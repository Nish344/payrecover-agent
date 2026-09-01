from __future__ import annotations

from payrecover.models import ActionRequest, ActionType, Case, CustomerResponse, GroundTruth


def respond(case: Case, action: ActionRequest, truth: GroundTruth) -> CustomerResponse:
    """Play the ground-truth profile. Opt-out is delivered at most once."""
    if case.opted_out:
        return CustomerResponse(case_id=case.case_id, kind="ignored")
    if action.action_type not in {ActionType.ISSUE_LINK, ActionType.REMIND, ActionType.WAIT}:
        return CustomerResponse(case_id=case.case_id, kind="ignored")

    profile = truth.profile
    link_id = action.payment_link_id or case.active_payment_link_id

    if profile == "opts_out":
        return CustomerResponse(case_id=case.case_id, kind="opted_out", payment_link_id=link_id)
    if profile == "never_pays" or profile == "high_value":
        return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
    if profile == "pays_on_first_link":
        if action.action_type == ActionType.ISSUE_LINK:
            return CustomerResponse(case_id=case.case_id, kind="paid", payment_link_id=link_id)
        return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
    if profile == "pays_after_reminder":
        target = truth.pay_on_reminder or 1
        if action.action_type == ActionType.REMIND and case.reminder_count >= target:
            return CustomerResponse(case_id=case.case_id, kind="paid", payment_link_id=link_id)
        return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
    if profile == "pays_if_fast":
        if action.action_type == ActionType.ISSUE_LINK and not case.wait_completed:
            return CustomerResponse(case_id=case.case_id, kind="paid", payment_link_id=link_id)
        return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
    if profile == "pays_after_wait":
        if action.action_type == ActionType.ISSUE_LINK and case.wait_completed:
            return CustomerResponse(case_id=case.case_id, kind="paid", payment_link_id=link_id)
        return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
    return CustomerResponse(case_id=case.case_id, kind="ignored", payment_link_id=link_id)
