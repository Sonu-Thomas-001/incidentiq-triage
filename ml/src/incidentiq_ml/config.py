"""Central configuration: paths, seeds, dataset provenance, field registry, leakage lists."""

from __future__ import annotations

from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ML_ROOT.parent
RAW_DIR = ML_ROOT / "data" / "raw"
PROCESSED_DIR = ML_ROOT / "data" / "processed"
ARTIFACT_DIR = ML_ROOT / "artifacts"
RESULTS_DIR = REPO_ROOT / "docs" / "report" / "results"
FIGURES_DIR = REPO_ROOT / "docs" / "report" / "figures"

SEED = 42
ACCESS_DATE = "2026-11-21"

# Real vs synthetic results must never be mixed; every artifact carries one of these.
PROV_REAL = "real"
PROV_SYNTHETIC = "synthetic-demo"

ZENODO_BASE = "https://zenodo.org/api/records/7648117/files"
ZENODO_FILES = {
    "X_train.csv": "789712F97FB472544EEB82D8F5A142ED46E0BF254C6C34AC53A9F1575A9D460E",
    "X_test.csv": "4B808BC32C57F063960A3A4E7A4A30769C96BE8143649AADC86835F4CB9763E5",
    "y_train.csv": "CB851FF4D5E792886504B3040BCC85A5DBF94514D31293EDDD6D69FCB7278D53",
    "y_test.csv": "2B10DB5E2F071E649EFB3D40DD007EC62BC661F35B4AFAF44117A00865760F94",
}
UCI_URL = "https://archive.ics.uci.edu/static/public/498/" "incident+management+process+enriched+event+log.zip"
UCI_ZIP_SHA256 = "6294E29A311647306BFDFC85783F7DF66517C197B9CD49AA5EE36BA9C525D1D6"
UCI_CSV_SHA256 = "FD184BBFD62329CFE093E99DA2EA7071905F2EAD91900B448EB2635870821BEF"

DATASETS = {
    "tickets": {
        "title": "Classification of IT Support Tickets (Zenodo)",
        "url": "https://doi.org/10.5281/zenodo.7648117",
        "license": "CC BY 4.0",
        "access_date": ACCESS_DATE,
        "records": 2229,
        "fields": "id, text, category_truth",
        "target_provenance": "Category labelled in 2020 by three IT professionals (dataset author).",
        "provenance": PROV_REAL,
    },
    "uci": {
        "title": "Incident management process enriched event log (UCI #498)",
        "url": "https://doi.org/10.24432/C57S4H",
        "license": "CC BY 4.0",
        "access_date": ACCESS_DATE,
        "records": "141,712 events / 24,918 incidents",
        "fields": "36 ServiceNow event-log columns; no free text",
        "target_provenance": "assignment_group and category as recorded in the ServiceNow log.",
        "provenance": PROV_REAL,
    },
    "synthetic": {
        "title": "IncidentIQ synthetic demo incidents (generated)",
        "url": "ml/src/incidentiq_ml/synthetic.py",
        "license": "Project code (generated data, no real records)",
        "access_date": ACCESS_DATE,
        "records": "configurable (default 3000)",
        "fields": "all required fields",
        "target_provenance": "Labels come from the generator's own rules. DEMONSTRATION ONLY.",
        "provenance": PROV_SYNTHETIC,
    },
}

# Field registry: where each required field comes from, per dataset.
# observed = present in the source; derived = computed from observed fields; synthetic = generated.
FIELD_REGISTRY: dict[str, dict[str, str]] = {
    "tickets": {
        "incident_id": "observed (id)",
        "short_description": "derived (first sentence of text)",
        "description": "observed (text)",
        "category": "observed (category_truth)",
        "priority": "absent",
        "assignment_group": "absent",
        "created_at": "absent",
        "service": "absent",
        "impact": "absent",
        "urgency": "absent",
    },
    "uci": {
        "incident_id": "observed (number)",
        "short_description": "absent (log has no free text)",
        "description": "absent",
        "category": "observed",
        "priority": "observed (deterministic function of impact x urgency)",
        "assignment_group": "observed (first event; see docs)",
        "created_at": "observed (opened_at)",
        "service": "absent (subcategory used as nearest proxy)",
        "impact": "observed",
        "urgency": "observed",
    },
    "synthetic": {
        k: "synthetic"
        for k in (
            "incident_id short_description description category priority assignment_group "
            "created_at service impact urgency"
        ).split()
    },
}
FIELD_REGISTRY["synthetic"]["priority"] = "derived (policy of synthetic impact x urgency)"

# UCI columns that are known only after triage/resolution -> never predictors.
UCI_LEAKAGE_COLUMNS = [
    "resolved_at", "closed_at", "closed_code", "close_code", "resolved_by", "assigned_to",
    "reassignment_count", "reopen_count", "sys_mod_count", "made_sla", "knowledge",
    "incident_state", "active", "problem_id", "rfc", "vendor", "caused_by",
    "u_priority_confirmation", "notify", "sys_updated_at", "sys_updated_by",
]  # fmt: skip

# Predictors allowed at ticket-opening time on UCI.
UCI_STRUCTURED_FEATURES = [
    "contact_type",
    "location",
    "subcategory",
    "u_symptom",
    "impact",
    "urgency",
]

# Fields derived from the target; excluded for the task they leak.
TARGET_DERIVED = {
    "category": ["category", "subcategory", "u_symptom"],  # sub-fields are nested under category
    "assignment_group": ["assignment_group"],
    "priority": ["priority"],
}

HIGH_PRIORITY_LABELS = ("1 - Critical", "2 - High")
