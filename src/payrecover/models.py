from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

# Shared contract. Cause taxonomy lives in diagnosis.py — kept as str here.


class CaseStatus(StrEnum):
    DETECTED = "detected"
    DIAGNOSED = "diagnosed"
    WAITING = "waiting"
    ESCALATED = "escalated"
    STOPPED = "stopped"
    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"


class ActionType(StrEnum):
    ISSUE_LINK = "issue_link"
    REMIND = "remind"
    WAIT = "wait"
    ESCALATE = "escalate"
    STOP = "stop"


class DiagnosisPath(StrEnum):
    LLM = "llm"
    RULES = "rules"


class Outcome(StrEnum):
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    STOPPED_BY_POLICY = "stopped_by_policy"
    EXHAUSTED = "exhausted"
    WAITING = "waiting"


class AuditEventType(StrEnum):
    CASE_DETECTED = "case_detected"
    DIAGNOSIS_COMPLETED = "diagnosis_completed"
    POLICY_VERDICT = "policy_verdict"
    ACTION_ATTEMPTED = "action_attempted"
    ACTION_RESULT = "action_result"
    CUSTOMER_RESPONSE = "customer_response"
    CASE_TERMINAL = "case_terminal"


class PaymentFailure(BaseModel):
    """Razorpay failure snapshot. No simulator ground-truth fields."""

    model_config = ConfigDict(frozen=True)

    payment_id: str | None = None
    order_id: str | None = None
    amount_paise: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    method: str | None = None
    status: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    error_reason: str | None = None
    error_source: str | None = None
    error_step: str | None = None
    international: bool | None = None


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    failure: PaymentFailure
    status: CaseStatus = CaseStatus.DETECTED
    link_count: int = Field(default=0, ge=0)
    reminder_count: int = Field(default=0, ge=0)
    opted_out: bool = False
    wait_until: datetime | None = None
    wait_completed: bool = False
    active_payment_link_id: str | None = None
    created_at: datetime


class Diagnosis(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    path: DiagnosisPath
    model: str | None = None


class ActionRequest(BaseModel):
    """Only policy.py should construct these via `from_policy`."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    action_type: ActionType
    amount_paise: int | None = Field(default=None, ge=0)
    payment_link_id: str | None = None
    wait_until: datetime | None = None
    rationale: str
    origin: Literal["policy"] = "policy"

    @classmethod
    def from_policy(
        cls,
        *,
        case_id: str,
        action_type: ActionType,
        rationale: str,
        amount_paise: int | None = None,
        payment_link_id: str | None = None,
        wait_until: datetime | None = None,
    ) -> ActionRequest:
        return cls(
            case_id=case_id,
            action_type=action_type,
            amount_paise=amount_paise,
            payment_link_id=payment_link_id,
            wait_until=wait_until,
            rationale=rationale,
            origin="policy",
        )


class ActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    action_type: ActionType
    ok: bool
    payment_link_id: str | None = None
    error_type: str | None = None
    detail: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    kind: Literal["paid", "ignored", "opted_out"]
    payment_link_id: str | None = None


class GroundTruth(BaseModel):
    """Hidden from diagnose/policy. Simulator only."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    profile: str
    pay_on_reminder: int | None = None


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...

    def list_for_case(self, case_id: str) -> list[AuditEvent]: ...


class AuditEvent(BaseModel):
    """Append-only row. Schema is locked to docs/decisions.md (Day 1)."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    case_id: str
    ts: datetime
    event_type: AuditEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


def paise_to_inr(amount_paise: int) -> str:
    rupees, paise = divmod(amount_paise, 100)
    return f"₹{rupees}.{paise:02d}"
