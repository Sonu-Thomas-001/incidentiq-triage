"""Offline fakes for the retrieval-augmented triage (no Gemini, no network)."""

from __future__ import annotations

import hashlib
import math
import re

import pytest

from app.core.config import get_settings
from app.services import rag_service

DIM = 64

# (sys_id seed, team, category, title, description)
LABELLED = [
    *[
        (f"net{i}", "Network", "network", t, "vpn wifi router connection drops")
        for i, t in enumerate(
            [
                "VPN disconnects",
                "Wifi keeps dropping",
                "Router unreachable",
                "Cannot connect to VPN",
                "Network latency high",
                "Switch port down",
                "Firewall blocks vpn",
                "DNS resolution failing",
            ]
        )
    ],
    *[
        (f"app{i}", "Apps", "software", t, "application crashes error report saving")
        for i, t in enumerate(
            [
                "App crashes on save",
                "Report export error",
                "Application freezes",
                "Software install fails",
                "Excel macro error",
                "CRM application timeout",
                "Login page error in app",
                "Application update broken",
            ]
        )
    ],
    *[
        (f"hw{i}", "Hardware", "hardware", t, "printer laptop keyboard screen broken")
        for i, t in enumerate(
            [
                "Printer jammed",
                "Laptop screen flickers",
                "Keyboard keys not working",
                "Monitor has no signal",
            ]
        )
    ],
]


def _vec(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class FakeEmbedder:
    model_name = "fake-embed"

    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    def embed(self, texts, *, query):
        self.calls.append((len(texts), query))
        return [_vec(t) for t in texts]


class FakeDecider:
    model_name = "fake-llm"

    def __init__(self, team=None, category=None, fail=False) -> None:
        self.team, self.category, self.fail = team, category, fail
        self.seen: list[str] = []

    def decide(self, incident_text, evidence, teams, categories):
        self.seen.append(incident_text + evidence)
        if self.fail:
            raise TimeoutError("simulated")
        from app.services.rag_service import AssignmentDecision

        top_team = re.search(r"team=([^;]+);", evidence)
        top_cat = re.search(r"category=([^;]+);", evidence)
        return AssignmentDecision(
            team=self.team or (top_team.group(1) if top_team else teams[0]),
            category=self.category or (top_cat.group(1) if top_cat else categories[0]),
            rationale="because similar incidents were handled by this team",
        )


def records():
    return [
        {
            "sys_id": s.ljust(32, "0"),
            "team": team,
            "category": cat,
            "title": title,
            "description": desc,
            "number": f"INC{n:07d}",
        }
        for n, (s, team, cat, title, desc) in enumerate(LABELLED)
    ]


@pytest.fixture
def rag(monkeypatch):
    """A populated index (20 labelled incidents) with fake embedder + decider."""
    embedder, decider = FakeEmbedder(), FakeDecider()
    rag_service.set_factories(lambda s: embedder, lambda s: decider)
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    get_settings.cache_clear()
    res = rag_service.build_index(records())
    assert res["indexed"] == len(LABELLED)
    return {"embedder": embedder, "decider": decider}
