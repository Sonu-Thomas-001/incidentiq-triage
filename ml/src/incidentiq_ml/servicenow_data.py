"""Pull incident records from the user's own ServiceNow instance (read-only GETs) for training.

Credentials come from the environment or backend/.env and are never written to disk by this
module. Raw pulls and everything derived from them stay under git-ignored paths because the
records belong to the instance owner.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from . import config as C

SN_RAW_DIR = C.RAW_DIR / "servicenow"
PAGE = 100
MAX_ROWS = 20000
# Opening-time fields only. Resolution notes, close codes, resolved_* and reassignment history are
# never requested, so they cannot leak into features.
INCIDENT_FIELDS = (
    "sys_id,number,short_description,description,category,priority,impact,urgency,"
    "assignment_group,opened_at,business_service,state"
)


class ServiceNowPullError(RuntimeError):
    pass


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = C.REPO_ROOT / "backend" / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k.startswith("SERVICENOW_")})
    return env


def _config() -> tuple[str, tuple[str, str]]:
    env = _load_env()
    url, user, pwd = (
        env.get("SERVICENOW_INSTANCE_URL", ""),
        env.get("SERVICENOW_USERNAME", ""),
        env.get("SERVICENOW_PASSWORD", ""),
    )
    if not (url and user and pwd):
        raise ServiceNowPullError(
            "Set SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME and SERVICENOW_PASSWORD in backend/.env"
        )
    parts = urlsplit(url if "//" in url else f"https://{url}")
    host = parts.hostname or ""
    if parts.scheme != "https" or not host.endswith(".service-now.com"):
        raise ServiceNowPullError("SERVICENOW_INSTANCE_URL must be https://<instance>.service-now.com")
    return f"https://{host}", (user, pwd)


def _get(session, base: str, table: str, params: dict) -> list[dict]:
    for attempt in range(4):
        r = session.get(f"{base}/api/now/table/{table}", params=params, timeout=30, allow_redirects=False)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(float(r.headers.get("Retry-After", 2**attempt)), 30))
            continue
        if r.status_code in (401, 403):
            raise ServiceNowPullError(f"ServiceNow rejected the credentials/permissions (HTTP {r.status_code})")
        if r.status_code != 200:
            raise ServiceNowPullError(f"ServiceNow returned HTTP {r.status_code} for table {table}")
        return r.json().get("result", [])
    raise ServiceNowPullError(f"ServiceNow kept failing or rate-limiting for table {table}")


def _paged(session, base: str, table: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    while len(rows) < MAX_ROWS:
        chunk = _get(session, base, table, {**params, "sysparm_limit": PAGE, "sysparm_offset": len(rows)})
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
    return rows


def _val(v):
    """Reference fields arrive as plain strings or {'value': ..., 'link': ...}."""
    if isinstance(v, dict):
        return v.get("value") or None
    return v if v not in ("", None) else None


def pull() -> dict:
    """Download incidents + assignment groups, store raw JSONL and the processed parquet."""
    import requests

    base, auth = _config()
    s = requests.Session()
    s.auth = auth
    s.headers["Accept"] = "application/json"
    common = {"sysparm_exclude_reference_link": "true", "sysparm_display_value": "false"}
    incidents = _paged(
        s, base, "incident", {**common, "sysparm_fields": INCIDENT_FIELDS, "sysparm_query": "ORDERBYnumber"}
    )
    groups = _paged(
        s, base, "sys_user_group", {**common, "sysparm_fields": "sys_id,name", "sysparm_query": "ORDERBYname"}
    )
    SN_RAW_DIR.mkdir(parents=True, exist_ok=True)
    (SN_RAW_DIR / "incidents.jsonl").write_text("\n".join(json.dumps(r) for r in incidents), encoding="utf-8")
    df = to_frame(incidents, {g["sys_id"]: g["name"] for g in groups if g.get("sys_id")})
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(C.PROCESSED_DIR / "servicenow_incidents.parquet", index=False)
    meta = {
        "source": "servicenow-table-api",
        "instance_host": urlsplit(base).hostname,
        "accessed_at": datetime.now(UTC).isoformat(),
        "incident_rows": len(incidents),
        "assignment_groups": len(groups),
        "fields_requested": INCIDENT_FIELDS.split(","),
        "note": "Private instance data: keep out of Git. Labels are the values stored in the instance at pull time.",
    }
    (SN_RAW_DIR / "pull.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def to_frame(incidents: list[dict], group_names: dict[str, str]) -> pd.DataFrame:
    rows = []
    for r in incidents:
        gid = _val(r.get("assignment_group"))
        rows.append(
            {
                "incident_id": r.get("number"),
                "sys_id": r.get("sys_id"),
                "short_description": (r.get("short_description") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "category": _val(r.get("category")),
                "priority": _val(r.get("priority")),
                "impact": _val(r.get("impact")),
                "urgency": _val(r.get("urgency")),
                "assignment_group": group_names.get(gid) if gid else None,
                "assignment_group_sys_id": gid,
                "created_at": pd.to_datetime(r.get("opened_at"), errors="coerce", utc=True),
                "service": _val(r.get("business_service")),
                "state": _val(r.get("state")),
                "provenance": C.PROV_REAL,
                "source": "servicenow",
            }
        )
    return pd.DataFrame(rows)


def processed_path() -> Path:
    return C.PROCESSED_DIR / "servicenow_incidents.parquet"
