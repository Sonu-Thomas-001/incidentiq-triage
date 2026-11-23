"""In-memory fake ServiceNow for offline tests only (never reachable from the running app). All data is fabricated."""

from __future__ import annotations

import copy
from typing import Any

from app.core.errors import UpstreamError
from app.integrations.servicenow.client import validate_sys_id

MOCK_HOST = "mock.service-now.com"


def _id(n: int) -> str:
    return f"{n:032x}"


GROUPS = [
    {
        "sys_id": _id(0xA1),
        "name": "Mock Network Support",
        "description": "SYNTHETIC",
        "active": "true",
    },
    {
        "sys_id": _id(0xA2),
        "name": "Mock Application Support",
        "description": "SYNTHETIC",
        "active": "true",
    },
    {
        "sys_id": _id(0xA3),
        "name": "Mock Service Desk",
        "description": "SYNTHETIC",
        "active": "true",
    },
]

INCIDENTS = [
    {
        "sys_id": _id(0xB1),
        "number": "INC9000001",
        "short_description": "[SYNTHETIC] VPN disconnects every few minutes",
        "description": "Synthetic mock record: the VPN client drops repeatedly on the office network.",
        "state": "1",
        "priority": "3",
        "impact": "2",
        "urgency": "2",
        "category": "network",
        "assignment_group": "",
        "sys_created_on": "2026-01-10 09:00:00",
        "sys_updated_on": "2026-01-10 09:00:00",
    },
    {
        "sys_id": _id(0xB2),
        "number": "INC9000002",
        "short_description": "[SYNTHETIC] Application crashes when saving a report",
        "description": "Synthetic mock record: the reporting application throws an error on save.",
        "state": "2",
        "priority": "2",
        "impact": "1",
        "urgency": "2",
        "category": "software",
        "assignment_group": {"value": _id(0xA3), "link": "https://mock/x"},
        "sys_created_on": "2026-01-11 10:30:00",
        "sys_updated_on": "2026-01-11 11:00:00",
    },
    {
        "sys_id": _id(0xB3),
        "number": "INC9000003",
        "short_description": "[SYNTHETIC] Printer queue stuck",
        "description": "Synthetic mock record: closed example that must not be importable.",
        "state": "7",
        "priority": "4",
        "impact": "3",
        "urgency": "3",
        "category": "hardware",
        "assignment_group": "",
        "sys_created_on": "2026-01-05 08:00:00",
        "sys_updated_on": "2026-01-06 08:00:00",
    },
]


class MockServiceNowClient:
    host = MOCK_HOST

    def __init__(self) -> None:
        self.incidents = copy.deepcopy(INCIDENTS)
        self.groups = copy.deepcopy(GROUPS)
        self.patch_calls: list[tuple[str, str]] = []
        self.fail_next_patch: UpstreamError | None = None
        self._clock = 0

    def _find(self, sys_id: str) -> dict[str, Any]:
        sys_id = validate_sys_id(sys_id)
        for rec in self.incidents:
            if rec["sys_id"] == sys_id:
                return rec
        raise UpstreamError(
            "ServiceNow record not found", status_code=404, code="UPSTREAM_NOT_FOUND"
        )

    def list_incidents(self, *, limit, offset, state, query, group):
        rows = self.incidents
        if state:
            rows = [r for r in rows if r["state"] == state]
        if query:
            rows = [r for r in rows if query.lower() in r["short_description"].lower()]
        if group:
            from app.integrations.servicenow.mapping import ref_value

            rows = [r for r in rows if ref_value(r["assignment_group"]) == group]
        return copy.deepcopy(rows[offset : offset + limit]), len(rows)

    def get_incident(self, sys_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._find(sys_id))

    def list_groups(self, *, limit, offset):
        return copy.deepcopy(self.groups[offset : offset + limit]), len(self.groups)

    def update_assignment_group(self, sys_id: str, group_sys_id: str) -> dict[str, Any]:
        if self.fail_next_patch is not None:
            err, self.fail_next_patch = self.fail_next_patch, None
            raise err
        rec = self._find(sys_id)
        group_sys_id = validate_sys_id(group_sys_id)
        self.patch_calls.append((rec["sys_id"], group_sys_id))
        rec["assignment_group"] = {"value": group_sys_id}
        self._clock += 1
        rec["sys_updated_on"] = f"2026-02-01 00:00:{self._clock:02d}"
        return copy.deepcopy(rec)
