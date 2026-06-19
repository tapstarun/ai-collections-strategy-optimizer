"""In-memory audit log of recommendations and (mock) executed actions.

Every entry records WHO did WHAT to WHICH borrower and WHEN — the basis for the
accountability and traceability a regulated lender needs. In production this would be
an append-only store (e.g. write-once table or log sink) rather than a process-memory
list, and would never contain raw PII.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from .models import AuditEntry

_lock = threading.Lock()
_entries: list[AuditEntry] = []


def record(
    *, actor_id: str, actor_role: str, borrower_id: str, event: str, detail: str
) -> AuditEntry:
    """Append an audit entry and return it. Thread-safe."""
    entry = AuditEntry(
        audit_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor_id=actor_id,
        actor_role=actor_role,
        borrower_id=borrower_id,
        event=event,
        detail=detail,
    )
    with _lock:
        _entries.append(entry)
    return entry


def all_entries() -> list[AuditEntry]:
    with _lock:
        return list(_entries)


def reset() -> None:
    """Test helper — clear the log."""
    with _lock:
        _entries.clear()
