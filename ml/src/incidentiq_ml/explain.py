"""Explainability: linear feature contributions, global coefficients, permutation importance.

SHAP/LIME are intentionally not used. For linear TF-IDF models the exact contribution of a term to a class
score is coef * tf-idf value, so post-hoc approximations would add cost and sampling noise
without extra fidelity. Permutation importance covers the structured (non-text) columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from . import config as C


def _clf(pipe):
    return pipe.named_steps["clf"]


def feature_names(pipe) -> np.ndarray:
    return np.asarray(pipe.named_steps["features"].get_feature_names_out())


def class_row(pipe, label: str) -> int:
    classes = list(_clf(pipe).classes_)
    return classes.index(label)


def contributions(pipe, frame: pd.DataFrame, label: str, top: int = 8) -> list[dict]:
    """Top terms pushing the (uncalibrated) linear score of `label` up for one incident."""
    x = pipe.named_steps["features"].transform(frame)
    coef = _clf(pipe).coef_
    row = coef[class_row(pipe, label)] if coef.shape[0] > 1 else coef[0] * (1 if class_row(pipe, label) == 1 else -1)
    x = x.tocsr()
    idx = x.indices
    contrib = x.data * row[idx]
    order = np.argsort(-contrib)[:top]
    names = feature_names(pipe)
    return [
        {
            "feature": str(names[idx[i]]).split("__", 1)[-1],
            "contribution": round(float(contrib[i]), 4),
        }
        for i in order
        if contrib[i] > 0
    ]


def global_top_features(pipe, top: int = 10) -> dict[str, list[dict]]:
    names, coef, classes = feature_names(pipe), _clf(pipe).coef_, _clf(pipe).classes_
    out = {}
    for i, c in enumerate(classes):
        order = np.argsort(-coef[i])[:top]
        out[str(c)] = [
            {
                "feature": str(names[j]).split("__", 1)[-1],
                "coef": round(float(coef[i][j]), 4),
            }
            for j in order
        ]
    return out


def permutation_groups(
    model, X: pd.DataFrame, y, columns: list[str], seed: int = C.SEED, repeats: int = 10
) -> list[dict]:
    """Global importance: macro-F1 drop when one input column is shuffled (held-out data)."""
    r = permutation_importance(
        model,
        X[columns],
        np.asarray(y),
        scoring="f1_macro",
        n_repeats=repeats,
        random_state=seed,
    )
    rows = [
        {"column": c, "importance_mean": float(m), "importance_std": float(s)}
        for c, m, s in zip(columns, r.importances_mean, r.importances_std)
    ]
    return sorted(rows, key=lambda d: -d["importance_mean"])
