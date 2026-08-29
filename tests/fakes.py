from __future__ import annotations

from payrecover.models import AuditEvent


class MemoryAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    def list_for_case(self, case_id: str) -> list[AuditEvent]:
        return [event for event in self.events if event.case_id == case_id]
