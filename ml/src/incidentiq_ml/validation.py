"""Schema validation and data-quality reports (missing values, duplicates, imbalance)."""

from __future__ import annotations

import json
import re

import pandas as pd

from . import config as C

SCHEMAS = {
    "tickets": {"required": ["incident_id", "description", "category"], "unique": ["incident_id"]},
    "uci_incidents": {
        "required": ["incident_id", "created_at", "category", "impact", "urgency", "priority", "assignment_group"],
        "unique": ["incident_id"],
    },
    "synthetic_incidents": {
        "required": [
            "incident_id", "short_description", "description", "category", "priority",
            "assignment_group", "created_at", "service", "impact", "urgency",
        ],
        "unique": ["incident_id"],
    },
}  # fmt: skip


class ValidationError(ValueError):
    pass


def normalize_text(s: str) -> str:
    """Canonical form for duplicate detection: lowercase, digits and masked tags collapsed."""
    s = re.sub(r"\[[^\]]+\]", " tag ", str(s).lower())
    s = re.sub(r"\d+", "0", s)
    return re.sub(r"\s+", " ", s).strip()


def validate_schema(df: pd.DataFrame, name: str) -> None:
    spec = SCHEMAS[name]
    missing = [c for c in spec["required"] if c not in df.columns]
    if missing:
        raise ValidationError(f"{name}: missing required columns {missing}")
    for col in spec["unique"]:
        if df[col].duplicated().any():
            raise ValidationError(f"{name}: duplicate values in {col}")
    if df.empty:
        raise ValidationError(f"{name}: empty dataset")
    if name == "uci_incidents" and not df["impact"].dropna().isin([1, 2, 3]).all():
        raise ValidationError("uci_incidents: impact outside 1..3")


def assert_no_leakage(feature_columns: list[str], target: str, name: str) -> None:
    """Fail loudly if predictors contain post-triage columns or the target itself."""
    bad = set(feature_columns) & set(C.UCI_LEAKAGE_COLUMNS)
    bad |= {target} & set(feature_columns)
    bad |= {"final_assignment_group", "template_id", "author_split", "provenance"} & set(feature_columns)
    if bad:
        raise ValidationError(f"{name}: leaking/non-predictor columns in features: {sorted(bad)}")


def report(df: pd.DataFrame, name: str, target_cols: list[str]) -> dict:
    validate_schema(df, name)
    rep: dict = {
        "dataset": name,
        "provenance": df["provenance"].iloc[0] if "provenance" in df else None,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "field_registry": C.FIELD_REGISTRY.get(name.replace("_incidents", ""), {}),
        "missing": {c: {"n": int(df[c].isna().sum()), "pct": round(float(df[c].isna().mean() * 100), 2)} for c in df.columns},
        "duplicates": {"duplicate_incident_ids": int(df["incident_id"].duplicated().sum())},
    }  # fmt: skip
    text_cols = [c for c in ("short_description", "description") if c in df]
    if text_cols:
        txt = df[text_cols].fillna("").agg(" ".join, axis=1) if len(text_cols) > 1 else df[text_cols[0]]
        norm = txt.map(normalize_text)
        rep["duplicates"]["exact_text_duplicates"] = int(txt.duplicated().sum())
        rep["duplicates"]["normalized_text_duplicates"] = int(norm.duplicated().sum())
        n = txt.str.len()
        rep["text_length_chars"] = {k: round(float(v), 1) for k, v in n.describe().items()}
    else:
        feat = [c for c in df.columns if c not in ("incident_id", "provenance", "created_at", "final_assignment_group")]
        rep["duplicates"]["identical_feature_rows"] = int(df[feat].duplicated().sum())
    for t in target_cols:
        vc = df[t].value_counts(dropna=False)
        rep.setdefault("class_distribution", {})[t] = {
            "n_classes": int(df[t].nunique()),
            "top": {str(k): int(v) for k, v in vc.head(15).items()},
            "imbalance_ratio_max_to_min": round(float(vc.max() / max(vc.min(), 1)), 1),
            "singleton_classes": int((vc == 1).sum()),
        }
    return rep


def write_report(rep: dict) -> None:
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (C.RESULTS_DIR / f"validation_{rep['dataset']}.json").write_text(json.dumps(rep, indent=2, default=str))
