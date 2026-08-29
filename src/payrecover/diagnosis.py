"""Failure diagnosis — implement from docs/decisions.md (Day 1).

Map error_reason + method + international → (cause, confidence, rationale).
Unambiguous Razorpay reasons should skip the LLM. On LLM timeout/failure, use rules
and set path=rules.
"""

from __future__ import annotations

from payrecover.config import Settings
from payrecover.models import Case, Diagnosis


def diagnose(case: Case, *, settings: Settings) -> Diagnosis:
    raise NotImplementedError("Implement diagnosis.diagnose. Key off error_reason, not error_code.")
