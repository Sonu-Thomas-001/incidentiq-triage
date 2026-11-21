"""Experiment runner: baselines, validation-only tuning, one final held-out evaluation, calibration."""

from __future__ import annotations

import itertools
import time

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import f1_score

from . import config as C
from . import models as M
from .splits import Split, calibration_cv

GRID_TEXT = {"C": [0.1, 1.0, 10.0], "ngram": [1, 2], "char": [False, True]}
GRID_STRUCT = {"C": [0.1, 1.0, 10.0]}
ALGOS = ("logreg", "linsvm")


def _grid(feature_set: str, fast: bool) -> list[dict]:
    g = GRID_STRUCT if feature_set.startswith("structured") else GRID_TEXT
    if fast:
        g = {k: v[:1] if k != "C" else [1.0] for k, v in g.items()}
    keys = list(g)
    return [dict(zip(keys, vals)) for vals in itertools.product(*g.values())]


def _macro(model, X, y) -> float:
    return float(f1_score(np.asarray(y), model.predict(X), average="macro", zero_division=0))


def _cut(X: pd.DataFrame, idx: np.ndarray) -> pd.DataFrame:
    return X.iloc[idx]


def run_classification(
    *,
    name: str,
    X: pd.DataFrame,
    y: pd.Series,
    split: Split,
    cat_cols: dict[str, list[str]],
    groups: np.ndarray | None = None,
    baselines: tuple[str, ...] = ("majority",),
    category_col: str | None = None,
    topk: tuple[int, ...] = (),
    high_labels: tuple[str, ...] = (),
    deploy_feature_set: str | None = None,
    fast: bool = False,
    seed: int = C.SEED,
) -> dict:
    """cat_cols maps feature_set -> categorical columns used by it (feature sets present are run)."""
    tr, va, te = split.train, split.val, split.test
    trva = np.concatenate([tr, va])
    y = pd.Series(np.asarray(y), index=X.index)
    ytr, yva, yte, ytrva = y.iloc[tr], y.iloc[va], y.iloc[te], y.iloc[trva]
    res: dict = {
        "experiment": name,
        "split": split.summary(),
        "n_classes": int(y.nunique()),
        "seed": seed,
        "baselines": {},
        "models": {},
        "protocol": "tune on validation only; refit finalists on train+val; evaluate once on untouched test",
    }

    def base_estimator(b: str):
        if b == "majority":
            return M.MajorityBaseline()
        if b == "keyword":
            return M.KeywordRuleClassifier()
        if b == "category_map":
            return M.CategoryMapBaseline(category_col)
        raise ValueError(b)

    for b in baselines:
        est = base_estimator(b)
        v = clone(est).fit(_cut(X, tr), ytr)
        final = clone(est).fit(_cut(X, trva), ytrva)
        res["baselines"][b] = {
            "val_macro_f1": _macro(v, _cut(X, va), yva),
            "test": M.evaluate(final, _cut(X, te), yte, topk=topk, high_labels=high_labels),
        }

    fitted: dict = {}
    for fs, cols in cat_cols.items():
        for algo in ALGOS:
            trials = []
            for params in _grid(fs, fast):
                t0 = time.time()
                pipe = M.build_pipeline(fs, algo, {**params, "max_iter": 500}, cols, seed)
                pipe.fit(_cut(X, tr), ytr)
                trials.append(
                    {
                        "params": params,
                        "val_macro_f1": _macro(pipe, _cut(X, va), yva),
                        "fit_s": round(time.time() - t0, 1),
                    }
                )
            best = max(trials, key=lambda t: t["val_macro_f1"])
            final = M.build_pipeline(fs, algo, {**best["params"], "max_iter": 500}, cols, seed).fit(
                _cut(X, trva), ytrva
            )
            key = f"{fs}/{algo}"
            fitted[key] = {
                "model": final,
                "params": best["params"],
                "cols": cols,
                "fs": fs,
                "algo": algo,
            }
            res["models"][key] = {
                "feature_set": fs,
                "algorithm": algo,
                "categorical_columns": cols,
                "tuning_trials": trials,
                "selected_params": best["params"],
                "val_macro_f1": best["val_macro_f1"],
                "test": M.evaluate(final, _cut(X, te), yte, topk=topk, high_labels=high_labels),
            }
    res["selected_by_validation"] = max(res["models"], key=lambda k: res["models"][k]["val_macro_f1"])
    if deploy_feature_set:
        cands = [k for k in res["models"] if k.startswith(deploy_feature_set + "/")]
        res["deploy_choice"] = max(cands, key=lambda k: res["models"][k]["val_macro_f1"])
        cal, extra = calibrate_deploy(X, y, split, fitted[res["deploy_choice"]], groups, seed)
        res["calibration"] = extra
        fitted["__deploy__"] = {
            "calibrated": cal,
            **fitted[res["deploy_choice"]],
            "key": res["deploy_choice"],
        }
    return res | {"_fitted": fitted}


def calibrate_deploy(X, y, split: Split, entry: dict, groups, seed: int) -> tuple[CalibratedClassifierCV, dict]:
    """Choose sigmoid vs isotonic on validation ECE, refit on train+val, report on test."""
    tr, va, te = split.train, split.val, split.test
    trva = np.concatenate([tr, va])
    base = M.build_pipeline(
        entry["fs"],
        entry["algo"],
        {**entry["params"], "max_iter": 500},
        entry["cols"],
        seed,
    )

    def fit_cal(idx: np.ndarray, method: str) -> CalibratedClassifierCV:
        g = groups[idx] if groups is not None else None
        cv = calibration_cv(y.iloc[idx], g, seed)
        return CalibratedClassifierCV(clone(base), method=method, cv=cv).fit(_cut(X, idx), y.iloc[idx])

    val_ece = {}
    for method in ("sigmoid", "isotonic"):
        c = fit_cal(tr, method)
        val_ece[method] = M.calibration_metrics(c.predict_proba(_cut(X, va)), c.classes_, y.iloc[va])["ece_top_label"]
    method = min(val_ece, key=val_ece.get)
    cal = fit_cal(trva, method)
    p_te = cal.predict_proba(_cut(X, te))
    out = {
        "method_selected_on_validation": method,
        "validation_ece_by_method": val_ece,
        "calibrated_test": M.calibration_metrics(p_te, cal.classes_, y.iloc[te]),
        "calibrated_macro_f1": float(
            f1_score(
                y.iloc[te],
                cal.classes_[p_te.argmax(1)],
                average="macro",
                zero_division=0,
            )
        ),
        "note": "SVM margins are never reported as probabilities; probabilities come only from calibration.",
    }
    if entry["algo"] == "logreg":
        raw = entry["model"].predict_proba(_cut(X, te))
        out["uncalibrated_native_logreg_test"] = M.calibration_metrics(raw, entry["model"].classes_, y.iloc[te])
    confs = p_te.max(1)
    correct = cal.classes_[p_te.argmax(1)] == y.iloc[te].to_numpy()
    out["confidence_threshold_tradeoff"] = [
        {
            "threshold": t,
            "coverage": float((confs >= t).mean()),
            "accuracy_on_covered": (float(correct[confs >= t].mean()) if (confs >= t).any() else None),
        }
        for t in (0.5, 0.6, 0.7, 0.8, 0.9)
    ]
    return cal, out
