"""SYNTHETIC demo incident generator. Output is NOT real operational data.

Labels follow the generator's own rules, so any model trained on it only demonstrates the
pipeline; it says nothing about performance on real incidents.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .policy import priority_from_impact_urgency

TEAMS = [
    "Network Operations", "Application Support", "Database Administration",
    "Service Desk", "Security Operations",
]  # fmt: skip

# category -> (primary team, alternate team, services, impact weights over 1..3, urgency weights)
SPEC = {
    "Network": ("Network Operations", "Service Desk", ["VPN", "WiFi", "LAN", "DNS"], (.2, .5, .3), (.2, .5, .3)),
    "Application": ("Application Support", "Service Desk", ["ERP", "CRM", "Intranet", "Email"], (.15, .5, .35), (.25, .45, .3)),
    "Database": ("Database Administration", "Application Support", ["ERP DB", "Reporting DB", "Data Warehouse"], (.35, .45, .2), (.3, .45, .25)),
    "Access": ("Service Desk", "Security Operations", ["Active Directory", "SSO", "Email"], (.05, .35, .6), (.1, .4, .5)),
    "Hardware": ("Service Desk", "Network Operations", ["Laptop", "Printer", "Mobile"], (.02, .28, .7), (.05, .35, .6)),
    "Security": ("Security Operations", "Service Desk", ["Endpoint Protection", "Firewall", "Email"], (.4, .4, .2), (.4, .4, .2)),
}  # fmt: skip

TEMPLATES = {
    "Network": [
        ("{svc} connection keeps dropping", "Users at {loc} report that {svc} disconnects every few minutes since this morning."),
        ("Cannot reach internal sites over {svc}", "From {loc} none of the internal sites load while on {svc}; ping times out."),
        ("Slow network at {loc}", "Throughput on {svc} at {loc} is extremely slow, downloads stall."),
        ("{svc} outage", "Complete loss of {svc} for the {loc} office, switch ports show no link."),
        ("Packet loss on {svc}", "Intermittent packet loss and high latency observed on {svc} at {loc}."),
        ("DNS names not resolving", "Hostnames fail to resolve from {loc}; {svc} returns timeout errors."),
    ],
    "Application": [
        ("{svc} returns error 500", "Opening {svc} shows an internal server error after login at {loc}."),
        ("{svc} very slow to load", "Pages in {svc} take over a minute to open for several users at {loc}."),
        ("{svc} crashes on save", "The {svc} client freezes and closes when saving a record."),
        ("Feature broken in {svc}", "After the last release a report in {svc} no longer exports to PDF."),
        ("{svc} login page blank", "The {svc} login page renders blank in the browser at {loc}."),
        ("Data not syncing in {svc}", "Changes made in {svc} are not visible to colleagues at {loc}."),
    ],
    "Database": [
        ("{svc} query timeouts", "Queries against {svc} time out; the nightly job is blocked by locks."),
        ("{svc} disk almost full", "Monitoring shows the {svc} data volume at 95 percent capacity."),
        ("Replication lag on {svc}", "The replica for {svc} is minutes behind the primary."),
        ("Restore request for {svc}", "Please restore {svc} tables to yesterday's backup after a bad import."),
        ("Deadlocks in {svc}", "Application logs show repeated deadlock errors on {svc}."),
        ("{svc} connection pool exhausted", "Applications cannot open new connections to {svc}."),
    ],
    "Access": [
        ("Locked out of account", "My {svc} account is locked after several attempts, I am at {loc}."),
        ("Password reset needed", "Please reset my password for {svc}; I forgot it."),
        ("Need access to shared folder", "New joiner at {loc} needs permissions granted via {svc}."),
        ("MFA code not accepted", "The {svc} multi-factor prompt rejects my code."),
        ("Account expired", "My {svc} account shows as expired although I am still employed."),
        ("Add user to distribution group", "Please add the new colleague to the team group in {svc}."),
    ],
    "Hardware": [
        ("{svc} not powering on", "My {svc} does not turn on, no lights at all, at {loc}."),
        ("{svc} screen broken", "The screen of my {svc} is cracked and flickering."),
        ("{svc} paper jam", "The {svc} near {loc} keeps jamming and shows an error."),
        ("Battery drains quickly on {svc}", "The {svc} battery lasts under an hour now."),
        ("Request replacement {svc}", "My {svc} is damaged, I need a replacement at {loc}."),
        ("Keyboard not working", "Several keys on the {svc} keyboard do not respond."),
    ],
    "Security": [
        ("Suspicious email reported", "I received a phishing message in {svc} asking for my credentials."),
        ("{svc} alert malware detected", "{svc} flagged a malware infection on a workstation at {loc}."),
        ("Unauthorized login attempts", "Many failed logins from unknown IPs on {svc}."),
        ("Possible data leak", "A user at {loc} sent a file with sensitive data to an external address."),
        ("Firewall rule review", "Please review the exposed ports reported by {svc}."),
        ("Lost laptop with company data", "A {svc} protected device was lost on a trip, please lock it."),
    ],
}  # fmt: skip

LOCATIONS = ["Guwahati", "Delhi", "Mumbai", "Bengaluru", "Chennai", "Remote"]


def generate(n: int = 3000, seed: int = C.SEED, label_noise: float = 0.08) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cats = list(SPEC)
    rows = []
    start = pd.Timestamp("2025-01-01", tz=None)
    for i in range(n):
        cat = cats[rng.integers(len(cats))]
        primary, alt, services, iw, uw = SPEC[cat]
        svc = services[rng.integers(len(services))]
        text_cat = cat if rng.random() > label_noise else cats[rng.integers(len(cats))]
        t_idx = int(rng.integers(len(TEMPLATES[text_cat])))
        short_t, long_t = TEMPLATES[text_cat][t_idx]
        loc = LOCATIONS[rng.integers(len(LOCATIONS))]
        team = primary if rng.random() > 0.12 else alt
        impact = int(rng.choice([1, 2, 3], p=iw))
        urgency = int(rng.choice([1, 2, 3], p=uw))
        if impact == 1 and urgency == 3:  # cell undefined in the policy (never observed)
            urgency = 2
        rows.append(
            {
                "incident_id": f"SYN-{i:06d}",
                "short_description": short_t.format(svc=svc, loc=loc),
                "description": long_t.format(svc=svc, loc=loc),
                "category": cat,
                "assignment_group": team,
                "service": svc,
                "impact": impact,
                "urgency": urgency,
                "priority": priority_from_impact_urgency(impact, urgency),
                "created_at": start + pd.Timedelta(minutes=int(rng.integers(0, 60 * 24 * 150))),
                "template_id": f"{text_cat}-{t_idx}",
                "provenance": C.PROV_SYNTHETIC,
                "is_synthetic": True,
            }
        )
    return pd.DataFrame(rows).sort_values("created_at", kind="stable").reset_index(drop=True)
