"""Honest batch metrics. Recovered = paid response on a payment link, not link sent."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from payrecover.models import (
    AuditEvent,
    AuditEventType,
    Case,
    CaseStatus,
    GroundTruth,
    Outcome,
    paise_to_inr,
)

_RECOVERABLE_PROFILES = frozenset(
    {
        "pays_on_first_link",
        "pays_after_reminder",
        "pays_if_fast",
        "pays_after_wait",
    }
)

_TERMINAL_OK = {
    CaseStatus.RECOVERED,
    CaseStatus.ESCALATED,
    CaseStatus.STOPPED,
    CaseStatus.EXHAUSTED,
}


def build_report(
    cases: list[Case],
    events: list[AuditEvent],
    *,
    output_dir: Path,
    truths: dict[str, GroundTruth] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    paid_ids = {
        event.case_id
        for event in events
        if event.event_type == AuditEventType.CUSTOMER_RESPONSE
        and event.payload.get("kind") == "paid"
        and event.payload.get("payment_link_id")
    }
    at_risk = sum(case.failure.amount_paise for case in cases)
    recovered_cases = [case for case in cases if case.case_id in paid_ids]
    recovered = sum(case.failure.amount_paise for case in recovered_cases)
    rate = (recovered / at_risk) if at_risk else 0.0

    outcomes = Counter(_outcome(case, paid_ids).value for case in cases)
    action_counts = Counter(
        str(event.payload.get("action_type"))
        for event in events
        if event.event_type == AuditEventType.ACTION_ATTEMPTED
    )
    exceptions = [
        case for case in cases if case.status not in _TERMINAL_OK and case.case_id not in paid_ids
    ]
    policy_stops = [case for case in cases if case.status == CaseStatus.STOPPED]
    escalations = _escalations(cases, events)

    body = {
        "cases": len(cases),
        "at_risk_paise": at_risk,
        "at_risk_inr": paise_to_inr(at_risk),
        "recovered_paise": recovered,
        "recovered_inr": paise_to_inr(recovered),
        "recovery_rate": round(rate, 4),
        "recovered_case_count": len(recovered_cases),
        "note": (
            "recovered = customer_response.kind=paid AND a payment_link_id exists; "
            "link sent is not recovered. v1 payment is simulated, not settled on Razorpay."
        ),
        "outcomes": dict(outcomes),
        "action_counts": dict(action_counts),
        "exception_list": [_case_row(case) for case in exceptions],
        "policy_stop_list": [_case_row(case) for case in policy_stops],
        "escalations": escalations,
    }
    if truths:
        body["capture"] = _capture(paid_ids, truths)
    json_path = output_dir / "report.json"
    json_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    md_path = output_dir / "report.md"
    md_path.write_text(_markdown(body), encoding="utf-8")
    return md_path


def _outcome(case: Case, paid_ids: set[str]) -> Outcome:
    if case.case_id in paid_ids:
        return Outcome.RECOVERED
    return {
        CaseStatus.ESCALATED: Outcome.ESCALATED,
        CaseStatus.STOPPED: Outcome.STOPPED_BY_POLICY,
        CaseStatus.EXHAUSTED: Outcome.EXHAUSTED,
        CaseStatus.WAITING: Outcome.WAITING,
        CaseStatus.RECOVERED: Outcome.RECOVERED,
    }.get(case.status, Outcome.WAITING)


def _capture(paid_ids: set[str], truths: dict[str, GroundTruth]) -> dict[str, object]:
    recoverable = [
        case_id for case_id, truth in truths.items() if truth.profile in _RECOVERABLE_PROFILES
    ]
    captured = [case_id for case_id in recoverable if case_id in paid_ids]
    n_recoverable = len(recoverable)
    n_captured = len(captured)
    rate = (n_captured / n_recoverable) if n_recoverable else 0.0
    by_profile: dict[str, dict[str, int]] = {}
    misses: dict[str, int] = {}
    for case_id in recoverable:
        profile = truths[case_id].profile
        row = by_profile.setdefault(profile, {"recoverable": 0, "captured": 0, "missed": 0})
        row["recoverable"] += 1
        if case_id in paid_ids:
            row["captured"] += 1
        else:
            row["missed"] += 1
            misses[profile] = misses.get(profile, 0) + 1
    return {
        "note": (
            "Evaluator-only. Reads hidden ground truth; the agent is blind. "
            "Recoverable profiles would pay given the right actions "
            "(pays_on_first_link, pays_after_reminder, pays_if_fast, pays_after_wait). "
            "never_pays / opts_out / high_value are excluded. "
            "Misses include pays_if_fast customers whose cause correctly triggered a wait."
        ),
        "recoverable_case_count": n_recoverable,
        "captured_case_count": n_captured,
        "capture_rate": round(rate, 4),
        "by_profile": by_profile,
        "misses_by_profile": misses,
    }


def _escalations(cases: list[Case], events: list[AuditEvent]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case in cases:
        if case.status != CaseStatus.ESCALATED:
            continue
        verdicts = [
            event
            for event in events
            if event.case_id == case.case_id
            and event.event_type == AuditEventType.POLICY_VERDICT
            and event.payload.get("action_type") == "escalate"
        ]
        diagnoses = [
            event
            for event in events
            if event.case_id == case.case_id
            and event.event_type == AuditEventType.DIAGNOSIS_COMPLETED
        ]
        last_verdict = verdicts[-1] if verdicts else None
        last_diag = diagnoses[-1] if diagnoses else None
        rows.append(
            {
                "case_id": case.case_id,
                "amount_inr": paise_to_inr(case.failure.amount_paise),
                "cause": None if last_diag is None else last_diag.payload.get("cause"),
                "rationale": (
                    None if last_verdict is None else last_verdict.payload.get("rationale")
                ),
            }
        )
    return rows


def _case_row(case: Case) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "amount_inr": paise_to_inr(case.failure.amount_paise),
        "status": case.status.value,
        "error_reason": case.failure.error_reason,
    }


def _markdown(body: dict[str, object]) -> str:
    outcomes = body["outcomes"]
    assert isinstance(outcomes, dict)
    exceptions = body["exception_list"]
    assert isinstance(exceptions, list)
    stops = body["policy_stop_list"]
    assert isinstance(stops, list)
    escalations = body["escalations"]
    assert isinstance(escalations, list)
    actions = body["action_counts"]
    assert isinstance(actions, dict)
    lines = [
        "# PayRecover report",
        "",
        f"- Cases: {body['cases']}",
        f"- ₹ at risk: {body['at_risk_inr']}",
        f"- ₹ recovered: {body['recovered_inr']} ({body['recovered_case_count']} cases)",
        f"- Recovery rate: {float(body['recovery_rate']) * 100:.2f}%",
        f"- Note: {body['note']}",
        "",
        "## Outcomes",
        "",
    ]
    for key, value in sorted(outcomes.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Action counts", ""])
    for key, value in sorted(actions.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Exception list (unresolved)", ""])
    if not exceptions:
        lines.append("(none)")
    else:
        for row in exceptions:
            assert isinstance(row, dict)
            lines.append(
                f"- {row['case_id']}  {row['amount_inr']}  {row['status']}  {row['error_reason']}"
            )
    lines.extend(["", "## Policy-stop list", ""])
    if not stops:
        lines.append("(none)")
    else:
        for row in stops:
            assert isinstance(row, dict)
            lines.append(f"- {row['case_id']}  {row['amount_inr']}  {row['status']}")
    lines.extend(["", "## Escalations (needs human)", ""])
    if not escalations:
        lines.append("(none)")
    else:
        for row in escalations:
            assert isinstance(row, dict)
            lines.append(
                f"- {row['case_id']}  {row['amount_inr']}  cause={row['cause']}  "
                f"rationale={row['rationale']}"
            )
    capture = body.get("capture")
    if isinstance(capture, dict):
        lines.extend(
            [
                "",
                "## Evaluator (hidden ground truth; agent is blind)",
                "",
                f"- Recoverable by construction: {capture['recoverable_case_count']}",
                (
                    f"- Captured: {capture['captured_case_count']} "
                    f"({float(capture['capture_rate']) * 100:.2f}%)"
                ),
                f"- Note: {capture['note']}",
                "",
                "### Misses by profile",
                "",
            ]
        )
        misses = capture.get("misses_by_profile")
        if not isinstance(misses, dict) or not misses:
            lines.append("(none)")
        else:
            for profile, count in sorted(misses.items()):
                lines.append(f"- {profile}: {count}")
    lines.append("")
    return "\n".join(lines)
