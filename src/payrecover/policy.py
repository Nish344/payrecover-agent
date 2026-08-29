"""Policy engine — implement from docs/decisions.md (Day 1, Policy rules).

Return ActionRequest.from_policy(...). Caps live in this file only.
"""

from __future__ import annotations

from payrecover.models import ActionRequest, Case, Diagnosis


def decide(case: Case, diagnosis: Diagnosis, *, kill_switch: bool) -> ActionRequest:
    raise NotImplementedError(
        "Implement policy.decide from docs/decisions.md Day 1 (first-match precedence)."
    )
