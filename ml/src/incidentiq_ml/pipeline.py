"""End-to-end task runners. Real-data and synthetic-demo results are written to separate files."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from . import artifacts, data, explain, plots
from . import config as C
from . import models as M
from .experiments import run_classification
from .policy import PRIORITY_POLICY, priority_from_impact_urgency
from .splits import (
    chronological_split,
    grouped_stratified_split,
    near_duplicate_groups,
    random_stratified_split,
)
from .validation import assert_no_leakage

RARE_MIN = 30
SYN_STRUCT = ["service", "impact", "urgency"]
UCI_SETS = {
    "structured_category": ["category"],
    "structured_category_sub_symptom": ["category", "subcategory", "u_symptom"],
    "structured_context": ["location", "contact_type"],
    "structured_impact_urgency": ["impact", "urgency"],
    "structured_all": [
        "category",
        "subcategory",
        "u_symptom",
        "location",
        "contact_type",
        "impact",
        "urgency",
    ],
}


def _write(name: str, res: dict) -> dict:
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in res.items() if not k.startswith("_")}
    (C.RESULTS_DIR / f"{name}.json").write_text(json.dumps(clean, indent=2, default=str))
    return clean


def _figures(prefix: str, res: dict, label: str) -> None:
    best = res["models"][res["selected_by_validation"]]
    plots.confusion(
        best["test"]["confusion_matrix"],
        f"{label}: confusion (test, {res['selected_by_validation']})",
        f"{prefix}_confusion",
    )
    plots.per_class_recall(
        best["test"]["per_class"],
        f"{label}: per-class recall (test)",
        f"{prefix}_per_class_recall",
    )
    if len({m["feature_set"] for m in res["models"].values()}) > 1:
        plots.ablation(res["models"], f"{label}: feature ablation", f"{prefix}_ablation")
    if "calibration" in res:
        plots.reliability(res["calibration"], f"{label}: reliability", f"{prefix}_reliability")


def _save_model(
    res: dict,
    task: str,
    provenance: str,
    fingerprint: str,
    input_features: list[str],
    model_dir: Path,
    extra: dict,
) -> None:
    dep = res["_fitted"]["__deploy__"]
    key = res["deploy_choice"]
    cfg = {
        "model": key,
        "params": dep["params"],
        "calibration": res["calibration"]["method_selected_on_validation"],
        "seed": res["seed"],
    }
    entry = artifacts.save_artifact(
        model_dir,
        task,
        {
            "model": dep["calibrated"],
            "explainer": dep["model"],
            "classes": [str(c) for c in dep["calibrated"].classes_],
        },
        {
            "task": task,
            "provenance": provenance,
            "is_demo": provenance != C.PROV_REAL,
            "model_version": f"{task}-{fingerprint[:8]}",
            "dataset_fingerprint": fingerprint,
            "input_features": input_features,
            "class_mapping": {str(i): str(c) for i, c in enumerate(dep["calibrated"].classes_)},
            "training_config": cfg,
            "split": res["split"],
            "metrics": {
                "test_macro_f1": res["models"][key]["test"]["macro"]["f1"],
                "test_weighted_f1": res["models"][key]["test"]["weighted"]["f1"],
                "test_accuracy": res["models"][key]["test"]["accuracy"],
                "calibrated_macro_f1": res["calibration"]["calibrated_macro_f1"],
                "ece_top_label": res["calibration"]["calibrated_test"]["ece_top_label"],
                "brier": res["calibration"]["calibrated_test"]["brier_multiclass"],
                "n_test": res["models"][key]["test"]["n"],
            },
            **extra,
        },
    )
    res["_manifest_entry"] = entry


def task_tickets_category(fast: bool, model_dir: Path | None) -> dict:
    df = data.load("tickets")
    fp = data.fingerprint(df)
    X, y = M.make_frame(df, []), df["category"]
    assert_no_leakage(list(X.columns), "category", "tickets")
    groups = near_duplicate_groups(df["description"])
    split = grouped_stratified_split(y, groups)
    res = run_classification(
        name="tickets_category_real", X=X, y=y, split=split, cat_cols={"text": []}, groups=groups,
        baselines=("majority", "keyword"), deploy_feature_set="text", fast=fast,
    )  # fmt: skip
    sizes = pd.Series(groups).value_counts()
    res["dataset"] = {
        "provenance": C.PROV_REAL,
        "fingerprint": fp,
        "rows": len(df),
        "near_duplicate_clusters": int(len(sizes)),
        "rows_in_multi_row_clusters": int(sizes[sizes > 1].sum()),
    }
    # Leakage diagnostic: same fixed config on a naive random split vs the grouped split.
    cfg = M.build_pipeline("text", "logreg", {"C": 1.0, "ngram": 1, "max_iter": 500}, [])
    diag = {}
    for label, sp in (("grouped", split), ("naive_random", random_stratified_split(y))):
        tv = np.concatenate([sp.train, sp.val])
        m = M.build_pipeline("text", "logreg", {"C": 1.0, "ngram": 1, "max_iter": 500}, []).fit(X.iloc[tv], y.iloc[tv])
        diag[label] = M.evaluate(m, X.iloc[sp.test], y.iloc[sp.test])["macro"]["f1"]
    del cfg
    res["leakage_diagnostic_macro_f1"] = diag
    dep = res["_fitted"]["__deploy__"]
    res["global_top_features"] = explain.global_top_features(dep["model"])
    res["_model_dir"] = model_dir
    if model_dir:
        _save_model(
            res,
            "category_real",
            C.PROV_REAL,
            fp,
            ["text"],
            model_dir,
            {
                "text_template": "description",
                "description": "Category from incident text; trained on the public Zenodo IT-ticket dataset.",
            },
        )
    _figures("tickets_category", res, "Tickets (real) Task A")
    return _write("tickets_category_real", res)


def _synthetic_frame() -> tuple[pd.DataFrame, pd.DataFrame, str, np.ndarray]:
    df = data.load("synthetic_incidents")
    X = M.make_frame(df, SYN_STRUCT)
    X["category"] = df["category"].astype(str)  # present only for the category->team baseline
    groups = pd.factorize(df["template_id"])[0]
    return df, X, data.fingerprint(df), groups


def task_synthetic(fast: bool, model_dir: Path | None) -> dict:
    df, X, fp, groups = _synthetic_frame()
    feats = [c for c in X.columns if c != "category"]
    assert_no_leakage(feats, "category", "synthetic")
    assert_no_leakage(feats, "assignment_group", "synthetic")
    sets = {"text": [], "structured": SYN_STRUCT, "combined": SYN_STRUCT}
    out = {}
    split = grouped_stratified_split(df["category"], groups)
    a = run_classification(
        name="synthetic_category_DEMO",
        X=X,
        y=df["category"],
        split=split,
        cat_cols=sets,
        groups=groups,
        baselines=("majority", "keyword"),
        fast=fast,
    )
    a["dataset"] = {
        "provenance": C.PROV_SYNTHETIC,
        "fingerprint": fp,
        "rows": len(df),
        "warning": "SYNTHETIC demo data: results are not evidence of real-world performance",
    }
    split_b = grouped_stratified_split(df["assignment_group"], groups)
    b = run_classification(
        name="synthetic_team_DEMO", X=X, y=df["assignment_group"], split=split_b, cat_cols=sets, groups=groups,
        baselines=("majority", "keyword", "category_map"), category_col="category", topk=(1, 3), deploy_feature_set="text", fast=fast,
    )  # fmt: skip
    b["dataset"] = a["dataset"]
    comb = b["_fitted"]["combined/logreg"]
    te = split_b.test
    b["permutation_importance_combined_logreg"] = explain.permutation_groups(
        comb["model"],
        X.iloc[te],
        df["assignment_group"].iloc[te],
        ["text", *SYN_STRUCT],
    )
    dep = b["_fitted"]["__deploy__"]
    b["global_top_features"] = explain.global_top_features(dep["model"])
    if model_dir:
        _save_model(
            b,
            "team_synthetic",
            C.PROV_SYNTHETIC,
            fp,
            ["text"],
            model_dir,
            {
                "text_template": "title_description",
                "description": "DEMO team routing trained on SYNTHETIC incidents using the app's five team names.",
            },
        )
    _figures("synthetic_category", a, "SYNTHETIC Task A")
    _figures("synthetic_team", b, "SYNTHETIC Task B")
    out["category"] = _write("synthetic_category_DEMO", a)
    out["team"] = _write("synthetic_team_DEMO", b)
    return out


def task_uci_group(fast: bool) -> dict:
    df = data.load("uci_incidents")
    n0 = len(df)
    df = df[df["assignment_group"].notna()].reset_index(drop=True)
    split = chronological_split(df["created_at"])
    train_counts = df["assignment_group"].iloc[split.train].value_counts()
    keep = set(train_counts[train_counts >= RARE_MIN].index)
    y = df["assignment_group"].where(df["assignment_group"].isin(keep), "OTHER (rare)")
    cols = UCI_SETS["structured_all"]
    X = M.make_frame(df, cols)
    assert_no_leakage(cols, "assignment_group", "uci")
    res = run_classification(
        name="uci_group_real", X=X, y=y, split=split, cat_cols=UCI_SETS, baselines=("majority", "category_map"),
        category_col="category", topk=(1, 3), fast=fast,
    )  # fmt: skip
    te = split.test
    res["dataset"] = {
        "provenance": C.PROV_REAL, "fingerprint": data.fingerprint(df.drop(columns=["created_at"])),
        "rows_total": n0, "rows_dropped_unknown_group": n0 - len(df), "target": "first-event assignment_group",
        "rare_group_threshold_train_count": RARE_MIN, "groups_kept": len(keep),
        "share_of_incidents_in_OTHER_rare": float((y == "OTHER (rare)").mean()),
        "note": "Group changes after opening are not predicted; 'final group' is not used.",
    }  # fmt: skip
    res["permutation_importance_structured_all_logreg"] = explain.permutation_groups(
        res["_fitted"]["structured_all/logreg"]["model"], X.iloc[te], y.iloc[te], cols
    )
    _figures("uci_group", res, "UCI (real) Task B")
    return _write("uci_group_real", res)


class _PolicyModel:
    """Applies the documented impact x urgency policy (not a trained model)."""

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.array([priority_from_impact_urgency(i, u) or "UNDEFINED" for i, u in zip(X["impact"], X["urgency"])])


def task_priority() -> dict:
    df = data.load("uci_incidents")
    df = df.dropna(subset=["impact", "urgency", "priority"]).reset_index(drop=True)
    split = chronological_split(df["created_at"])
    Xn = df[["impact", "urgency"]].astype(int)
    y = df["priority"]
    pol = _PolicyModel()
    violations = int((pol.predict(Xn) != y.to_numpy()).sum())
    res: dict = {
        "experiment": "uci_priority_real",
        "dataset": {"provenance": C.PROV_REAL, "incidents": len(df)},
        "finding": "priority is a deterministic function of impact x urgency; implemented as a documented policy, not claimed as ML discovery",
        "policy_table": {f"impact={i},urgency={u}": p for (i, u), p in sorted(PRIORITY_POLICY.items())},
        "policy_violations_on_first_events": violations,
        "split": split.summary(),
    }
    raw = C.RAW_DIR / "uci" / "incident_event_log.csv"
    if raw.exists():
        ev = pd.read_csv(raw, dtype=str, na_values=["?"], usecols=["impact", "urgency", "priority"]).dropna()
        ev_pred = [priority_from_impact_urgency(i[0], u[0]) for i, u in zip(ev["impact"], ev["urgency"])]
        res["policy_violations_all_events"] = {
            "events": len(ev),
            "violations": int(sum(p != t for p, t in zip(ev_pred, ev["priority"]))),
        }
    te, tr = split.test, np.concatenate([split.train, split.val])
    Xt, yt = Xn.iloc[te], y.iloc[te]
    res["policy_test"] = M.evaluate(pol, Xt, yt, high_labels=C.HIGH_PRIORITY_LABELS)
    maj = M.MajorityBaseline().fit(Xn.iloc[tr], y.iloc[tr])
    res["majority_baseline_test"] = M.evaluate(maj, Xt, yt, high_labels=C.HIGH_PRIORITY_LABELS)
    tree = DecisionTreeClassifier(max_depth=4, random_state=C.SEED).fit(Xn.iloc[tr], y.iloc[tr])
    res["decision_tree_on_impact_urgency_test"] = M.evaluate(tree, Xt, yt, high_labels=C.HIGH_PRIORITY_LABELS)
    res["decision_tree_note"] = (
        "A shallow tree merely re-learns the policy; it demonstrates determinism, not independent prediction."
    )
    plots.confusion(
        res["policy_test"]["confusion_matrix"],
        "UCI (real) Task C: policy vs observed priority (test)",
        "uci_priority_confusion",
    )
    return _write("uci_priority_real", res)


def run_all(fast: bool = False, model_dir: Path | None = None) -> dict:
    model_dir = model_dir or C.ARTIFACT_DIR
    return {
        "tickets_category": task_tickets_category(fast, model_dir),
        "synthetic": task_synthetic(fast, model_dir),
        "uci_group": task_uci_group(fast),
        "priority": task_priority(),
    }
