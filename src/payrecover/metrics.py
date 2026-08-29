"""Batch metrics — implement from docs/decisions.md.

Recovered = customer_response kind paid (simulator attested). Link sent ≠ recovered.
"""

from __future__ import annotations

from pathlib import Path

from payrecover.models import AuditEvent, Case


def build_report(cases: list[Case], events: list[AuditEvent], *, output_dir: Path) -> Path:
    raise NotImplementedError(
        "Write markdown+JSON: rupees at risk, recovered, rate, outcomes, exception list."
    )
