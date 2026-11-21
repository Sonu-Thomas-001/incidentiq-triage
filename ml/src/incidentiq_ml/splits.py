"""Leakage-aware splitting. Test indices are produced here and only used for the final evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

from . import config as C
from .validation import normalize_text


@dataclass(frozen=True)
class Split:
    train: np.ndarray
    val: np.ndarray
    test: np.ndarray
    strategy: str

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "n_train": len(self.train),
            "n_val": len(self.val),
            "n_test": len(self.test),
        }


def near_duplicate_groups(texts: pd.Series, threshold: float = 0.9) -> np.ndarray:
    """Cluster exact/near-duplicate texts (cosine >= threshold on normalised word TF-IDF).

    The vectoriser is fit on the whole corpus only to define *groups*; it never feeds a model.
    """
    norm = texts.map(normalize_text)
    x = TfidfVectorizer(ngram_range=(1, 2), min_df=1).fit_transform(norm)
    sim = (x @ x.T).tocsr()
    sim.data = (sim.data >= threshold).astype(np.int8)
    sim.eliminate_zeros()
    return connected_components(sim, directed=False)[1]


def grouped_stratified_split(y: pd.Series, groups: np.ndarray, seed: int = C.SEED) -> Split:
    """~60/20/20 split where no group straddles partitions, stratified by label where possible."""
    idx = np.arange(len(y))
    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = [te for _, te in outer.split(idx, y, groups)]
    test, val = folds[0], folds[1]
    train = np.concatenate(folds[2:])
    return Split(
        np.sort(train),
        np.sort(val),
        np.sort(test),
        "stratified-grouped (near-duplicate clusters kept together)",
    )


def random_stratified_split(y: pd.Series, seed: int = C.SEED) -> Split:
    """Naive split used ONLY as a leakage diagnostic, never for reported model selection."""
    idx = np.arange(len(y))
    outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = [te for _, te in outer.split(idx, y)]
    return Split(
        np.sort(np.concatenate(folds[2:])),
        np.sort(folds[1]),
        np.sort(folds[0]),
        "naive random stratified (diagnostic)",
    )


def chronological_split(created_at: pd.Series, train: float = 0.70, val: float = 0.15) -> Split:
    order = np.argsort(created_at.to_numpy(), kind="stable")
    n = len(order)
    a, b = int(n * train), int(n * (train + val))
    return Split(
        np.sort(order[:a]),
        np.sort(order[a:b]),
        np.sort(order[b:]),
        "chronological 70/15/15 by created_at",
    )


def calibration_cv(y: pd.Series | np.ndarray, groups: np.ndarray | None, seed: int = C.SEED, n: int = 5):
    """Internal CV folds for calibration; grouped when near-duplicate groups exist."""
    idx = np.arange(len(y))
    if groups is not None:
        return list(StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=seed).split(idx, y, groups))
    return list(StratifiedKFold(n_splits=n, shuffle=True, random_state=seed).split(idx, y))
