"""Report figures generated from experiment results (never hand-drawn)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import config as C  # noqa: E402


def _save(fig, name: str) -> str:
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / f"{name}.png", dpi=130)
    plt.close(fig)
    return f"{name}.png"


def confusion(cm: dict, title: str, name: str, max_labels: int = 25) -> str:
    labels, m = cm["labels"], np.array(cm["matrix"], dtype=float)
    if len(labels) > max_labels:  # keep the figure readable: show the most frequent classes
        top = np.argsort(-m.sum(axis=1))[:max_labels]
        labels, m = [labels[i] for i in top], m[np.ix_(top, top)]
    m = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(max(5, len(labels) * 0.5), max(4.5, len(labels) * 0.45)))
    im = ax.imshow(m, vmin=0, vmax=1, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=75, ha="right", fontsize=7)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title, fontsize=9)
    fig.colorbar(im, ax=ax, label="row-normalised")
    return _save(fig, name)


def per_class_recall(per_class: dict, title: str, name: str, top: int = 30) -> str:
    items = sorted(per_class.items(), key=lambda kv: -kv[1]["support"])[:top]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.bar([k for k, _ in items], [v["recall"] for _, v in items])
    ax.set_ylim(0, 1)
    ax.set_ylabel("recall (test)")
    ax.set_title(title, fontsize=9)
    ax.tick_params(axis="x", rotation=75, labelsize=7)
    return _save(fig, name)


def ablation(models: dict, title: str, name: str) -> str:
    fsets = sorted({m["feature_set"] for m in models.values()})
    algos = sorted({m["algorithm"] for m in models.values()})
    fig, ax = plt.subplots(figsize=(max(6, 1.3 * len(fsets)), 4))
    w = 0.8 / len(algos)
    for i, a in enumerate(algos):
        vals = [models[f"{f}/{a}"]["test"]["macro"]["f1"] for f in fsets]
        ax.bar(np.arange(len(fsets)) + i * w, vals, w, label=a)
    ax.set_xticks(np.arange(len(fsets)) + w * (len(algos) - 1) / 2, fsets, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("test macro-F1")
    ax.set_ylim(0, 1)
    ax.legend()
    ax.set_title(title, fontsize=9)
    return _save(fig, name)


def reliability(cal: dict, title: str, name: str) -> str:
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    series = [("calibrated", cal["calibrated_test"])]
    if "uncalibrated_native_logreg_test" in cal:
        series.append(("native LR proba", cal["uncalibrated_native_logreg_test"]))
    for label, c in series:
        b = c["reliability_bins"]
        ax.plot(
            [x["confidence"] for x in b],
            [x["accuracy"] for x in b],
            "o-",
            label=f"{label} (ECE {c['ece_top_label']:.3f})",
        )
    ax.set_xlabel("mean confidence")
    ax.set_ylabel("empirical accuracy")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7)
    return _save(fig, name)
