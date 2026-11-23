"""Training and evaluation on incidents pulled from the user's ServiceNow instance.

Nothing here invents labels. If the instance holds too few labelled incidents for a valid
stratified, leakage-safe split the task is skipped with an explicit reason and no model artifact
is written, so the backend keeps reporting NOT_READY instead of serving a meaningless model.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from . import config as C
from . import data, explain
from . import models as M
from .experiments import run_classification
from .pipeline import _figures, _save_model, _write
from .servicenow_data import processed_path
from .splits import chronological_split, grouped_stratified_split, near_duplicate_groups
from .validation import assert_no_leakage

MIN_ROWS = 150
MIN_CLASS = 20
STRUCT_CANDIDATES = ("service", "impact", "urgency")
HIGH_LABELS = ("1", "2")


class InsufficientDataError(RuntimeError):
    pass


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    text = [M.build_text(s, d) for s, d in zip(df["short_description"], df["description"])]
    out = df.assign(_text=text)
    return out[out["_text"].str.len() > 0].reset_index(drop=True)


def data_report(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df),
        "missing_share": {
            c: float(df[c].isna().mean() + (df[c] == "").mean())
            for c in df.columns
            if c not in ("provenance", "source")
        },
        "duplicate_text_rows": int(df.duplicated(subset=["short_description", "description"]).sum()),
        "category_counts": df["category"].value_counts(dropna=False).astype(int).to_dict(),
        "assignment_group_counts": df["assignment_group"].value_counts(dropna=False).astype(int).to_dict(),
        "priority_counts": df["priority"].value_counts(dropna=False).astype(int).to_dict(),
        "text_length_chars": df[["short_description", "description"]]
        .apply(lambda s: s.str.len())
        .describe()
        .round(1)
        .to_dict(),
    }


def _classification(df: pd.DataFrame, target: str, name: str, key: str, fast: bool, model_dir: Path | None) -> dict:
    d = _frame(df.dropna(subset=[target]))
    counts = d[target].value_counts()
    keep = counts[counts >= MIN_CLASS]
    if len(d) < MIN_ROWS or len(keep) < 2:
        raise InsufficientDataError(
            f"{target}: need >= {MIN_ROWS} labelled incidents and >= 2 classes with >= {MIN_CLASS} each; "
            f"found {len(d)} rows, class counts {counts.to_dict()}"
        )
    dropped = {str(k): int(v) for k, v in counts[counts < MIN_CLASS].items()}
    d = d[d[target].isin(keep.index)].reset_index(drop=True)
    y = d[target].astype(str)
    X = pd.DataFrame({"text": d["_text"]})
    struct = []
    for c in STRUCT_CANDIDATES:
        col = d[c].astype("object").where(d[c].notna(), "missing").astype(str)
        if col.nunique() >= 2:
            X[c] = col
            struct.append(c)
    is_team = target == "assignment_group"
    if is_team:
        X["category"] = d["category"].astype("object").where(d["category"].notna(), "missing").astype(str)
    feats = [c for c in X.columns if c != "category"]
    assert_no_leakage(feats, target, "servicenow")
    sets = {"text": []} | ({"structured": struct, "combined": struct} if struct else {})
    groups = near_duplicate_groups(d["_text"])
    split = grouped_stratified_split(y, groups)
    res = run_classification(
        name=name, X=X, y=y, split=split, cat_cols=sets, groups=groups,
        baselines=("majority", "keyword", "category_map") if is_team else ("majority", "keyword"),
        category_col="category" if is_team else None, topk=(1, 3) if is_team else (),
        deploy_feature_set="text", fast=fast,
    )  # fmt: skip
    fp = data.fingerprint(d[["short_description", "description", target]])
    res["dataset"] = {
        "provenance": C.PROV_REAL,
        "source": "servicenow",
        "fingerprint": fp,
        "rows": len(d),
        "classes_kept": int(len(keep)),
        "classes_dropped_below_min_count": dropped,
        "min_class_count": MIN_CLASS,
        "target_provenance": "Value stored in the ServiceNow instance at pull time (may reflect later reassignment).",
        "warning": "Measured on one private instance; not evidence of performance elsewhere.",
    }
    res["global_top_features"] = explain.global_top_features(res["_fitted"]["__deploy__"]["model"])
    if model_dir:
        _save_model(
            res, key, C.PROV_REAL, fp, ["text"], model_dir,
            {"text_template": "title_description", "data_source": "servicenow",
             "description": f"{target} predicted from incident text; trained on incidents pulled from a ServiceNow instance."},
        )  # fmt: skip
    _figures(name, res, f"ServiceNow {target}")
    return _write(name, res)


class _Lookup:
    """(impact, urgency) -> modal training priority; evaluation only."""

    def __init__(self, table: dict[tuple[str, str], str], fallback: str):
        self.table, self.fallback = table, fallback

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.array([self.table.get((i, u), self.fallback) for i, u in zip(X["impact"], X["urgency"])])


def _priority(df: pd.DataFrame) -> dict:
    d = df.dropna(subset=["impact", "urgency", "priority", "created_at"]).reset_index(drop=True)
    if len(d) < MIN_ROWS:
        raise InsufficientDataError(
            f"priority: need >= {MIN_ROWS} rows with impact, urgency, priority and created_at; found {len(d)}"
        )
    cells = d.groupby(["impact", "urgency"])["priority"].agg(lambda s: s.value_counts().to_dict())
    deterministic = bool(all(len(v) == 1 for v in cells))
    split = chronological_split(d["created_at"])
    tv = np.concatenate([split.train, split.val])
    Xs = d[["impact", "urgency"]].astype(str)
    y = d["priority"].astype(str)
    modal = {
        (i, u): g.mode().iloc[0] for (i, u), g in y.iloc[tv].groupby([Xs["impact"].iloc[tv], Xs["urgency"].iloc[tv]])
    }
    lookup = _Lookup(modal, y.iloc[tv].mode().iloc[0])
    te = split.test
    maj = M.MajorityBaseline().fit(Xs.iloc[tv], y.iloc[tv])
    enc = Xs.astype(int)
    tree = DecisionTreeClassifier(max_depth=4, random_state=C.SEED).fit(enc.iloc[tv], y.iloc[tv])
    res = {
        "experiment": "servicenow_priority",
        "dataset": {"provenance": C.PROV_REAL, "source": "servicenow", "incidents": len(d)},
        "finding": (
            "Every observed (impact, urgency) cell maps to exactly one priority: priority follows an instance-side rule, "
            "implemented as a documented lookup rather than claimed as ML discovery."
            if deterministic
            else "Priority is NOT a pure function of (impact, urgency) on this instance; see observed_cells."
        ),
        "observed_cells": {f"impact={i},urgency={u}": {k: int(v) for k, v in c.items()} for (i, u), c in cells.items()},
        "policy_table": {f"impact={i},urgency={u}": p for (i, u), p in sorted(modal.items())},
        "split": split.summary(),
        "policy_test": M.evaluate(lookup, Xs.iloc[te], y.iloc[te], high_labels=HIGH_LABELS),
        "majority_baseline_test": M.evaluate(maj, Xs.iloc[te], y.iloc[te], high_labels=HIGH_LABELS),
        "decision_tree_on_impact_urgency_test": M.evaluate(tree, enc.iloc[te], y.iloc[te], high_labels=HIGH_LABELS),
    }
    return _write("servicenow_priority", res)


def run_all(fast: bool = False, model_dir: Path | None = None) -> dict:
    model_dir = model_dir or C.ARTIFACT_DIR
    C.RESULTS_DIR, C.FIGURES_DIR = C.SN_RESULTS_DIR, C.SN_FIGURES_DIR
    path = processed_path()
    if not path.is_file():
        raise FileNotFoundError("No ServiceNow data: run `python -m incidentiq_ml servicenow-pull` first")
    df = pd.read_parquet(path)
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    status: dict = {"data": data_report(df), "tasks": {}}
    jobs = {
        "category": lambda: _classification(
            df, "category", "servicenow_category", "category_servicenow", fast, model_dir
        ),
        "team": lambda: _classification(df, "assignment_group", "servicenow_team", "team_servicenow", fast, model_dir),
        "priority": lambda: _priority(df),
    }
    for task, job in jobs.items():
        try:
            job()
            status["tasks"][task] = {"status": "TRAINED_AND_EVALUATED"}
        except InsufficientDataError as exc:
            status["tasks"][task] = {"status": "SKIPPED_INSUFFICIENT_DATA", "reason": str(exc)}
    (C.RESULTS_DIR / "validation_servicenow_training_status.json").write_text(json.dumps(status, indent=2, default=str))
    return status
