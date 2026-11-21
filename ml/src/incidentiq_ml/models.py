"""Feature frames, sklearn pipelines, baselines and metrics.

Serving models are plain scikit-learn Pipelines (no custom classes) so the backend can load
them without importing this package. Baseline estimators below are for evaluation only.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.svm import LinearSVC

from . import config as C

TOKEN = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def build_text(short_description: str | None, description: str | None) -> str:
    """Same text construction at training and serving time."""
    short, desc = (short_description or "").strip(), (description or "").strip()
    return f"{short}. {desc}" if short and desc else (short or desc)


def make_frame(df: pd.DataFrame, cat_cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    if "description" in df:
        if "short_description" in df and df["provenance"].iloc[0] == C.PROV_SYNTHETIC:
            out["text"] = [build_text(s, d) for s, d in zip(df["short_description"], df["description"])]
        else:
            out["text"] = df["description"].fillna("").astype(str)
    for c in cat_cols:
        out[c] = df[c].astype("object").where(df[c].notna(), "missing").astype(str)
    return out


def build_pipeline(feature_set: str, algo: str, params: dict, cat_cols: list[str], seed: int = C.SEED) -> Pipeline:
    parts = []
    if feature_set in ("text", "combined"):
        parts.append(
            (
                "word",
                TfidfVectorizer(ngram_range=(1, params.get("ngram", 1)), sublinear_tf=True),
                "text",
            )
        )
        if params.get("char"):
            parts.append(
                (
                    "char",
                    TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2),
                    "text",
                )
            )
    if feature_set.startswith("structured") or feature_set == "combined":
        parts.append(("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols))
    if not parts:
        raise ValueError(f"empty feature set {feature_set}")
    if algo == "logreg":
        clf = LogisticRegression(
            C=params["C"],
            class_weight="balanced",
            max_iter=params.get("max_iter", 1000),
            random_state=seed,
        )
    elif algo == "linsvm":
        clf = LinearSVC(C=params["C"], class_weight="balanced", random_state=seed, max_iter=5000)
    else:
        raise ValueError(algo)
    return Pipeline([("features", ColumnTransformer(parts)), ("clf", clf)])


# --------------------------------------------------------------------------- baselines
class MajorityBaseline(DummyClassifier):
    def __init__(self):
        super().__init__(strategy="most_frequent")


class KeywordRuleClassifier(BaseEstimator, ClassifierMixin):
    """Data-driven keyword rules learned on TRAIN only: each class keeps its most distinctive
    tokens; prediction = class with most keyword hits, falling back to the majority class."""

    def __init__(self, top_k: int = 15, min_count: int = 3):
        self.top_k = top_k
        self.min_count = min_count

    def fit(self, X, y):
        texts = pd.Series(X["text"] if hasattr(X, "columns") else X).str.lower()
        y = np.asarray(y)
        self.classes_ = np.unique(y)
        toks = [set(TOKEN.findall(t)) for t in texts]
        total = len(toks)
        df_all: dict[str, int] = {}
        for s in toks:
            for w in s:
                df_all[w] = df_all.get(w, 0) + 1
        self.keywords_: dict = {}
        for c in self.classes_:
            sel = [s for s, lab in zip(toks, y) if lab == c]
            cnt: dict[str, int] = {}
            for s in sel:
                for w in s:
                    cnt[w] = cnt.get(w, 0) + 1
            scored = [
                (
                    np.log((n + 1) / (len(sel) + 2)) - np.log((df_all[w] - n + 1) / (total - len(sel) + 2)),
                    w,
                )
                for w, n in cnt.items()
                if n >= self.min_count
            ]
            self.keywords_[c] = {w for _, w in sorted(scored, reverse=True)[: self.top_k]}
        vals, counts = np.unique(y, return_counts=True)
        self.majority_ = vals[np.argmax(counts)]
        return self

    def predict(self, X):
        texts = pd.Series(X["text"] if hasattr(X, "columns") else X).str.lower()
        out = []
        for t in texts:
            toks = set(TOKEN.findall(t))
            hits = {c: len(toks & kw) for c, kw in self.keywords_.items()}
            best = max(hits.values()) if hits else 0
            out.append(self.majority_ if best == 0 else min(c for c, h in hits.items() if h == best))
        return np.array(out)


class CategoryMapBaseline(BaseEstimator, ClassifierMixin):
    """category -> assignment group lookup learned on train. predict_proba is the empirical
    P(group | category), a valid ranking for top-k; unseen categories fall back to the prior."""

    def __init__(self, category_col: str = "category"):
        self.category_col = category_col

    def fit(self, X, y):
        y = pd.Series(np.asarray(y), index=X.index)
        self.classes_ = np.array(sorted(y.unique()))
        self.prior_ = (y.value_counts(normalize=True).reindex(self.classes_).fillna(0)).to_numpy()
        ct = pd.crosstab(X[self.category_col], y).reindex(columns=self.classes_, fill_value=0)
        self.table_ = ct.div(ct.sum(axis=1), axis=0)
        return self

    def predict_proba(self, X):
        return np.vstack(
            [self.table_.loc[c].to_numpy() if c in self.table_.index else self.prior_ for c in X[self.category_col]]
        )

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


# --------------------------------------------------------------------------- metrics
def scores_for_topk(model, X) -> np.ndarray | None:
    """Return valid ranking scores or None (majority/keyword models have none)."""
    if isinstance(model, (DummyClassifier, KeywordRuleClassifier)):
        return None
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)
    if hasattr(model, "decision_function"):
        return model.decision_function(X)
    return None


def topk_accuracy(scores: np.ndarray, classes: np.ndarray, y_true, k: int) -> float:
    top = np.argsort(-scores, axis=1)[:, :k]
    hit = [yt in set(classes[row]) for yt, row in zip(y_true, top)]
    return float(np.mean(hit))


def evaluate(model, X, y, topk: tuple[int, ...] = (), high_labels: tuple[str, ...] = ()) -> dict:
    y = np.asarray(y)
    pred = model.predict(X)
    labels = sorted(set(y) | set(pred))
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=labels, zero_division=0)
    wp, wr, wf, _ = precision_recall_fscore_support(y, pred, average="weighted", zero_division=0)
    mp, mr, mf, _ = precision_recall_fscore_support(y, pred, average="macro", zero_division=0)
    res = {
        "n": int(len(y)),
        "accuracy": float(accuracy_score(y, pred)),
        "macro": {"precision": float(mp), "recall": float(mr), "f1": float(mf)},
        "weighted": {"precision": float(wp), "recall": float(wr), "f1": float(wf)},
        "per_class": {
            str(lab): {"precision": float(a), "recall": float(b), "f1": float(c), "support": int(d)}
            for lab, a, b, c, d in zip(labels, p, r, f, s)
        },
        "confusion_matrix": {
            "labels": [str(x) for x in labels],
            "matrix": confusion_matrix(y, pred, labels=labels).tolist(),
        },
    }
    if topk:
        sc = scores_for_topk(model, X)
        if sc is None:
            res["topk"] = {str(k): None for k in topk}
            res["topk_note"] = "not computed: model exposes no valid scores/probabilities"
        else:
            cls = model.classes_ if hasattr(model, "classes_") else model[-1].classes_
            res["topk"] = {str(k): topk_accuracy(sc, np.asarray(cls), y, k) for k in topk}
    if high_labels:
        m = np.isin(y, high_labels)
        res["high_priority_recall"] = float(np.isin(pred[m], high_labels).mean()) if m.any() else None
        res["high_priority_exact_recall"] = float((pred[m] == y[m]).mean()) if m.any() else None
    return res


def ece_score(proba: np.ndarray, classes: np.ndarray, y_true, bins: int = 10) -> tuple[float, list[dict]]:
    """Top-label expected calibration error plus per-bin reliability data."""
    conf = proba.max(axis=1)
    correct = (classes[proba.argmax(axis=1)] == np.asarray(y_true)).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    ece, rows = 0.0, []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            gap = abs(correct[m].mean() - conf[m].mean())
            ece += m.mean() * gap
            rows.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": int(m.sum()),
                    "confidence": float(conf[m].mean()),
                    "accuracy": float(correct[m].mean()),
                }
            )
    return float(ece), rows


def calibration_metrics(proba: np.ndarray, classes: np.ndarray, y_true) -> dict:
    y_true = np.asarray(y_true)
    onehot = (y_true[:, None] == classes[None, :]).astype(float)
    ece, rows = ece_score(proba, classes, y_true)
    ll = float(-np.mean(np.log(np.clip((proba * onehot).sum(axis=1), 1e-12, 1))))
    return {
        "ece_top_label": ece,
        "brier_multiclass": float(np.mean(((proba - onehot) ** 2).sum(axis=1))),
        "log_loss": ll,
        "mean_confidence": float(proba.max(axis=1).mean()),
        "accuracy": float((classes[proba.argmax(axis=1)] == y_true).mean()),
        "reliability_bins": rows,
    }
