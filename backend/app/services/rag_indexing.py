"""Build the local Chroma index from ServiceNow incidents that already have an assignment group."""

from __future__ import annotations

from typing import Any

from app.integrations.servicenow import service as sn
from app.services import rag_service

PAGE = 100
MAX_PAGES = 50  # hard cap: 5,000 incidents


def _group_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for page in range(1, MAX_PAGES + 1):
        res = sn.list_remote_groups(page, PAGE)
        for g in res["items"]:
            if g["sys_id"] and g["name"]:
                names[g["sys_id"].lower()] = g["name"]
        if page * res["page_size"] >= (res["total"] or 0):
            break
    return names


def collect_records() -> tuple[list[dict[str, Any]], int]:
    groups = _group_names()
    records: list[dict[str, Any]] = []
    seen = 0
    for page in range(1, MAX_PAGES + 1):
        res = sn.list_remote_incidents(page, PAGE, state=None, query=None, group=None)
        for r in res["items"]:
            seen += 1
            team = groups.get(r["assignment_group_sys_id"] or "")
            if team:
                records.append({**r, "team": team})
        if page * res["page_size"] >= (res["total"] or 0):
            break
    return records, seen


def sync_index() -> dict[str, Any]:
    records, seen = collect_records()
    return {"source_incidents": seen, **rag_service.build_index(records)}
