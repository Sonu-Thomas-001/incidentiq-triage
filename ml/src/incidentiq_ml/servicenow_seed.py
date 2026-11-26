"""Create SYNTHETIC training incidents in YOUR OWN ServiceNow developer instance (writes!).

A fresh developer instance holds too few incidents to train on. This script POSTs generated
incidents to the Table API so the normal `servicenow-pull` / `servicenow-train` flow has data.

Safety:
- Dry run by default; nothing is sent without `--apply` AND `--confirm-host <instance host>`.
- Only creates `incident` rows; never updates or deletes existing ones.
- Every created row carries correlation_id `incidentiq-seed-NNNN`, so the run is idempotent and
  `unseed` can remove exactly these rows (and nothing else).
- The text is template-generated, NOT real operations data. Models trained on it measure how well
  they recover the generator's category/team mapping; report them as such.
"""

from __future__ import annotations

import random
import time
from urllib.parse import urlsplit

from .servicenow_data import ServiceNowPullError, _config

MARKER = "incidentiq-seed-"
MAX_COUNT = 600
SEED = 377

# category -> (assignment group name in the instance, subjects, symptoms, contexts)
SPEC: dict[str, tuple[str, list[str], list[str], list[str]]] = {
    "hardware": (
        "Hardware",
        [
            "laptop",
            "docking station",
            "monitor",
            "keyboard",
            "desktop PC",
            "printer",
            "scanner",
            "headset",
            "webcam",
            "mouse",
            "external hard drive",
            "UPS unit",
            "barcode reader",
            "tablet",
        ],
        [
            "will not power on",
            "shows a flickering screen",
            "makes a loud grinding noise",
            "overheats and shuts down",
            "battery drains within minutes",
            "is not detected by the computer",
            "has a cracked casing",
            "keeps freezing during use",
            "produces blank pages",
            "has keys that do not respond",
            "charges only intermittently",
            "displays a fault light",
        ],
        [
            "after being moved to a new desk",
            "since this morning",
            "after a firmware update",
            "following a power cut",
            "after a coffee spill nearby",
            "since returning from leave",
            "when connected to the dock",
            "every afternoon",
        ],
    ),
    "software": (
        "Software",
        [
            "Outlook",
            "Microsoft Teams",
            "Excel",
            "the CRM client",
            "the expense application",
            "Adobe Reader",
            "the HR portal",
            "Visual Studio",
            "the finance reporting tool",
            "Chrome",
            "Zoom",
            "the document management system",
            "SAP GUI",
            "the ticket approval app",
        ],
        [
            "crashes on startup",
            "shows an unexpected error dialog",
            "fails to install the latest update",
            "cannot open shared files",
            "runs extremely slowly",
            "keeps asking me to sign in again",
            "reports that my licence has expired",
            "loses unsaved work",
            "will not sync my data",
            "displays a blank window",
            "exits with a runtime exception",
            "will not let me export reports",
        ],
        [
            "after the weekend patching",
            "since the last version was pushed",
            "when working with large files",
            "for the whole team",
            "only on my account",
            "after upgrading the operating system",
            "when opening more than one window",
            "since this morning",
        ],
    ),
    "network": (
        "Network",
        [
            "VPN",
            "office Wi-Fi",
            "the wired connection",
            "the branch router",
            "the firewall",
            "the guest network",
            "DNS resolution",
            "the remote desktop gateway",
            "the load balancer",
            "the site-to-site link",
            "the VoIP phones",
            "the proxy server",
            "the switch on floor three",
            "the wireless access point",
        ],
        [
            "keeps disconnecting every few minutes",
            "is extremely slow",
            "drops all packets",
            "refuses new connections",
            "times out when I try to reach internal sites",
            "is unreachable from the meeting rooms",
            "shows an authentication failure",
            "has high latency during video calls",
            "does not hand out IP addresses",
            "blocks a legitimate website",
            "is down for the whole office",
            "intermittently loses signal",
        ],
        [
            "since the network maintenance window",
            "only when working from home",
            "in the east wing",
            "during peak hours",
            "after the router was restarted",
            "since this morning",
            "for several users at the branch",
            "after moving desks",
        ],
    ),
    "database": (
        "Database",
        [
            "the customer database",
            "the reporting warehouse",
            "the Oracle instance",
            "the SQL Server cluster",
            "the PostgreSQL replica",
            "the nightly ETL job",
            "the backup schedule",
            "the orders schema",
            "the analytics datastore",
            "the MongoDB collection",
            "the connection pool",
            "the stored procedure for invoicing",
            "the read replica",
            "the data export job",
        ],
        [
            "is running out of disk space",
            "returns query timeouts",
            "has replication lag of several hours",
            "failed its last backup",
            "shows deadlocks in the log",
            "rejects logins from the application",
            "has a corrupted index",
            "is returning duplicate rows",
            "needs a restore of yesterday's data",
            "is consuming all available memory",
            "cannot be reached by the reporting tool",
            "has a blocked transaction",
        ],
        [
            "since the overnight job",
            "after the schema migration",
            "during month-end processing",
            "after the storage expansion",
            "when more than fifty users connect",
            "since the failover test",
            "after the last patch",
            "every night around two",
        ],
    ),
    "inquiry": (
        "Service Desk",
        [
            "a new starter account",
            "my password",
            "access to the shared drive",
            "a software licence",
            "the VPN token",
            "the visitor Wi-Fi code",
            "a mailbox delegation",
            "the meeting room booking system",
            "a loan laptop",
            "multi-factor authentication",
            "the self-service portal",
            "an additional monitor",
            "a distribution list",
            "the IT induction",
        ],
        [
            "I need help setting up",
            "could you tell me how to request",
            "please explain the process for",
            "I would like to ask about",
            "who approves",
            "how long does it take to get",
            "I need a reset for",
            "can I get an update on my request for",
            "please advise on the policy for",
            "I forgot how to use",
            "where do I find instructions for",
            "I want to change",
        ],
        [
            "for a colleague joining on Monday",
            "before my trip next week",
            "as my manager requested",
            "for the new project",
            "because I changed teams",
            "ahead of the audit",
            "for a contractor",
            "as part of my onboarding",
        ],
    ),
}

IMPACT_URGENCY = [
    ("1", "1", 1),
    ("1", "2", 2),
    ("2", "2", 6),
    ("2", "3", 5),
    ("3", "3", 8),
    ("2", "1", 2),
    ("3", "2", 3),
]


def _text(rng: random.Random, category: str) -> tuple[str, str]:
    _, subjects, symptoms, contexts = SPEC[category]
    subject, symptom, context = rng.choice(subjects), rng.choice(symptoms), rng.choice(contexts)
    if category == "inquiry":
        short = f"{symptom} {subject}"
        desc = f"{symptom.capitalize()} {subject} {context}. Please let me know the next steps."
    else:
        short = f"{subject[0].upper()}{subject[1:]} {symptom}"
        desc = (
            f"{subject[0].upper()}{subject[1:]} {symptom} {context}. "
            f"{rng.choice(['I have already restarted it.', 'No recent changes on my side.', 'This is blocking my work.', 'A colleague sees the same.', 'Please investigate.'])}"
        )
    return short[:160], desc


def build(count: int) -> list[dict[str, str]]:
    rng = random.Random(SEED)
    cats = list(SPEC)
    weights = [w for _, _, w in IMPACT_URGENCY]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    attempts = 0
    while len(rows) < count and attempts < count * 50:
        attempts += 1
        cat = cats[len(rows) % len(cats)]
        short, desc = _text(rng, cat)
        if short + desc in seen:
            continue
        seen.add(short + desc)
        impact, urgency, _ = rng.choices(IMPACT_URGENCY, weights=weights)[0]
        rows.append(
            {
                "category": cat,
                "short_description": short,
                "description": desc,
                "impact": impact,
                "urgency": urgency,
                "correlation_id": f"{MARKER}{len(rows) + 1:04d}",
            }
        )
    return rows


def _session():
    import requests

    base, auth = _config()
    s = requests.Session()
    s.auth = auth
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return s, base


def _call(s, method: str, url: str, **kw):
    for attempt in range(4):
        r = s.request(method, url, timeout=30, allow_redirects=False, **kw)
        if r.status_code == 429 or (r.status_code >= 500 and method == "GET"):
            time.sleep(min(float(r.headers.get("Retry-After", 2**attempt)), 30))
            continue
        if r.status_code in (401, 403):
            raise ServiceNowPullError(f"ServiceNow rejected the credentials/permissions (HTTP {r.status_code})")
        if r.status_code >= 400:
            raise ServiceNowPullError(f"ServiceNow returned HTTP {r.status_code} for {method} {url.split('/api/')[-1]}")
        return r
    raise ServiceNowPullError("ServiceNow kept failing or rate-limiting")


def _existing(s, base: str) -> dict[str, str]:
    """correlation_id -> sys_id for rows created by a previous run."""
    out: dict[str, str] = {}
    offset = 0
    while True:
        r = _call(
            s,
            "GET",
            f"{base}/api/now/table/incident",
            params={
                "sysparm_query": f"correlation_idSTARTSWITH{MARKER}",
                "sysparm_fields": "sys_id,correlation_id",
                "sysparm_limit": 100,
                "sysparm_offset": offset,
            },
        )
        rows = r.json().get("result", [])
        out.update({x["correlation_id"]: x["sys_id"] for x in rows})
        if len(rows) < 100:
            return out
        offset += 100


def _group_ids(s, base: str) -> dict[str, str]:
    r = _call(
        s,
        "GET",
        f"{base}/api/now/table/sys_user_group",
        params={"sysparm_fields": "sys_id,name", "sysparm_limit": 500, "sysparm_query": "active=true"},
    )
    return {g["name"]: g["sys_id"] for g in r.json().get("result", [])}


def seed(count: int = 300, apply: bool = False, confirm_host: str = "") -> dict:
    if not 1 <= count <= MAX_COUNT:
        raise ServiceNowPullError(f"--count must be between 1 and {MAX_COUNT}")
    s, base = _session()
    host = urlsplit(base).hostname or ""
    groups = _group_ids(s, base)
    missing = sorted({g for g, *_ in SPEC.values()} - set(groups))
    if missing:
        raise ServiceNowPullError(f"Assignment groups missing in the instance: {missing}")
    done = _existing(s, base)
    todo = [r for r in build(count) if r["correlation_id"] not in done]
    plan = {
        "instance_host": host,
        "requested": count,
        "already_present": len(done),
        "to_create": len(todo),
        "fields_written": [
            "category",
            "short_description",
            "description",
            "impact",
            "urgency",
            "assignment_group",
            "correlation_id",
        ],
        "applied": False,
    }
    if not apply:
        plan["note"] = f"Dry run. To create {len(todo)} incidents re-run with --apply --confirm-host {host}"
        return plan
    if confirm_host != host:
        raise ServiceNowPullError(f"--confirm-host must equal the target instance host ({host})")
    created = 0
    for row in todo:
        body = {**row, "assignment_group": groups[SPEC[row["category"]][0]]}
        _call(s, "POST", f"{base}/api/now/table/incident", json=body)
        created += 1
    plan.update(applied=True, created=created)
    return plan


def unseed(apply: bool = False, confirm_host: str = "") -> dict:
    """Delete only rows whose correlation_id starts with the seed marker."""
    s, base = _session()
    host = urlsplit(base).hostname or ""
    rows = _existing(s, base)
    out = {"instance_host": host, "matching": len(rows), "applied": False}
    if not apply:
        out["note"] = f"Dry run. To delete {len(rows)} seeded incidents re-run with --apply --confirm-host {host}"
        return out
    if confirm_host != host:
        raise ServiceNowPullError(f"--confirm-host must equal the target instance host ({host})")
    for sys_id in rows.values():
        _call(s, "DELETE", f"{base}/api/now/table/incident/{sys_id}")
    out.update(applied=True, deleted=len(rows))
    return out
