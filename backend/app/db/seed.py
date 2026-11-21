"""Seed SYNTHETIC demo users, teams, routing rules and incidents.

Usage (after `alembic upgrade head`):  python -m app.db.seed
All seeded records are flagged is_synthetic=True. No real data or credentials are used.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Incident, RoutingRule, Team, User
from app.models.enums import Priority, Role
from app.services import incidents as svc

TEAMS = {
    "Network Operations": "Connectivity, VPN, Wi-Fi (synthetic demo team)",
    "Application Support": "Business applications and ERP (synthetic demo team)",
    "Database Administration": "Database availability and performance (synthetic demo team)",
    "Service Desk": "Accounts, access and end-user hardware (synthetic demo team)",
    "Security Operations": "Phishing, malware, suspicious activity (synthetic demo team)",
}

# (email, full name, role, team)
USERS = [
    ("reporter@synthetic.example", "Demo Reporter (synthetic)", Role.REPORTER, None),
    ("analyst@synthetic.example", "Demo Triage Analyst (synthetic)", Role.TRIAGE_ANALYST, None),
    (
        "engineer.network@synthetic.example",
        "Demo Network Engineer (synthetic)",
        Role.SUPPORT_ENGINEER,
        "Network Operations",
    ),
    (
        "engineer.apps@synthetic.example",
        "Demo Apps Engineer (synthetic)",
        Role.SUPPORT_ENGINEER,
        "Application Support",
    ),
    ("admin@synthetic.example", "Demo Admin (synthetic)", Role.ADMIN, None),
]

RULES = [
    ("SYNTHETIC vpn-keyword", "vpn", "Network", Priority.P2, "Network Operations"),
    ("SYNTHETIC database-keyword", "database", "Database", Priority.P2, "Database Administration"),
    ("SYNTHETIC phishing-keyword", "phishing", "Security", Priority.P1, "Security Operations"),
]

INCIDENTS = [
    (
        "VPN disconnects every 10 minutes",
        "Remote users on the branch network report the VPN client drops roughly every ten minutes and must re-authenticate.",
    ),
    (
        "ERP invoice posting is failing",
        "Finance users get a timeout error when posting vendor invoices in the ERP since this morning.",
    ),
    (
        "Database reporting queries are slow",
        "Nightly reporting queries on the sales database now take over an hour instead of ten minutes.",
    ),
    (
        "Cannot reset my account password",
        "The self-service password reset page loops back to the login page after submitting the form.",
    ),
    (
        "Suspicious email asking for credentials",
        "Several staff received an email pretending to be IT asking them to confirm their password via a link.",
    ),
    (
        "Conference room Wi-Fi is unstable",
        "Wi-Fi in the third floor conference rooms drops for about 30 seconds several times an hour.",
    ),
    (
        "Laptop will not boot after update",
        "After the latest OS update the laptop shows a black screen after the vendor logo.",
    ),
    (
        "Shared drive permissions missing",
        "The new analyst joiner cannot open the team shared drive; access denied message is shown.",
    ),
    (
        "Printer queue stuck on 2nd floor",
        "Print jobs on the second floor stay in the queue and never print; restarting does not help.",
    ),
    (
        "CRM dashboard shows stale numbers",
        "The CRM sales dashboard has not refreshed since yesterday evening.",
    ),
    (
        "Intermittent packet loss to data center",
        "Monitoring shows 5-8% packet loss between HQ and the data center during business hours.",
    ),
    (
        "Mailbox storage limit warning",
        "A user reports repeated mailbox full warnings despite having archived old mail.",
    ),
]


def seed(db: Session) -> str | None:
    settings = get_settings()
    password = settings.demo_password
    generated = None
    if not password:
        password = generated = secrets.token_urlsafe(12)

    teams: dict[str, Team] = {}
    for name, desc in TEAMS.items():
        team = db.scalar(select(Team).where(Team.name == name))
        if team is None:
            team = Team(name=name, description=desc, is_synthetic=True)
            db.add(team)
        teams[name] = team
    db.flush()

    users: dict[Role, User] = {}
    created_users = False
    for email, full_name, role, team_name in USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name=full_name,
                role=role,
                team_id=teams[team_name].id if team_name else None,
                password_hash=hash_password(password),
                is_synthetic=True,
            )
            db.add(user)
            created_users = True
        users.setdefault(role, user)
    for name, keyword, category, priority, team_name in RULES:
        if db.scalar(select(RoutingRule).where(RoutingRule.name == name)) is None:
            db.add(
                RoutingRule(
                    name=name,
                    keyword_pattern=keyword,
                    category=category,
                    priority=priority,
                    team_id=teams[team_name].id,
                    is_synthetic=True,
                )
            )
    db.commit()

    if db.scalar(select(Incident.id).where(Incident.is_synthetic).limit(1)) is None:
        _seed_incidents(db, users, teams)
    return generated if created_users else None


def _seed_incidents(db: Session, users: dict[Role, User], teams: dict[str, Team]) -> None:
    reporter, analyst, admin = users[Role.REPORTER], users[Role.TRIAGE_ANALYST], users[Role.ADMIN]
    engineer = db.scalar(select(User).where(User.email == "engineer.network@synthetic.example"))
    created = []
    for title, description in INCIDENTS:
        incident = svc.create_incident(
            db, reporter, f"[SYNTHETIC] {title}", f"{description} (Synthetic demo data.)"
        )
        incident.is_synthetic = True
        db.commit()
        created.append(incident)

    def triage(i: Incident) -> None:
        svc.request_triage(db, analyst, i.id, i.version)

    def assign(i: Incident, team: str, priority: Priority, category: str) -> None:
        db.refresh(i)
        svc.assign_incident(
            db,
            analyst,
            i.id,
            expected_version=i.version,
            team_id=teams[team].id,
            priority=priority,
            category=category,
            reason="Synthetic seed decision",
            prediction_id=None,
        )

    for i in created[0:2]:
        triage(i)
    triage(created[2])
    assign(created[2], "Database Administration", Priority.P2, "Database")
    triage(created[3])
    assign(created[3], "Service Desk", Priority.P3, "Access")
    assign(created[4], "Security Operations", Priority.P1, "Security")
    assign(created[5], "Network Operations", Priority.P3, "Network")
    db.refresh(created[5])
    svc.accept_incident(db, engineer, created[5].id, created[5].version)
    assign(created[10], "Application Support", Priority.P2, "Network")
    db.refresh(created[10])
    svc.override_assignment(
        db,
        admin,
        created[10].id,
        expected_version=created[10].version,
        team_id=teams["Network Operations"].id,
        priority=Priority.P2,
        category="Network",
        reason="Synthetic seed override: network issue misrouted to apps",
    )


def main() -> None:
    with SessionLocal() as db:
        generated = seed(db)
    print("Seeded SYNTHETIC demo data.")
    if generated:
        print(f"Generated demo password (shown once, store it safely): {generated}")
    else:
        print("Demo password: value of DEMO_PASSWORD (or unchanged for existing users).")
    print("Demo logins: " + ", ".join(email for email, *_ in USERS))


if __name__ == "__main__":
    main()
