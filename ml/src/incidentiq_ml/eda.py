"""Reproducible EDA: charts saved under docs/report/figures, numbers under docs/report/results."""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as C  # noqa: E402
from .validation import normalize_text  # noqa: E402


def cramers_v(a: pd.Series, b: pd.Series) -> float:
    """Bias-corrected Cramér's V for two categorical series (rows with NaN dropped)."""
    from scipy.stats import chi2_contingency

    m = pd.concat([a, b], axis=1).dropna()
    if m.empty:
        return float("nan")
    ct = pd.crosstab(m.iloc[:, 0], m.iloc[:, 1])
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        return 0.0
    chi2 = chi2_contingency(ct, correction=False)[0]
    n = ct.values.sum()
    phi2 = chi2 / n
    r, k = ct.shape
    phi2c = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1))
    rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    return float(np.sqrt(phi2c / max(min(kc - 1, rc - 1), 1e-9)))


def _save(fig, name: str) -> str:
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    p = C.FIGURES_DIR / f"{name}.png"
    fig.tight_layout()
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p.name


def _bar(series: pd.Series, title: str, name: str, top: int = 30, log: bool = False) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    series.head(top).plot.bar(ax=ax)
    ax.set_title(title)
    ax.set_ylabel("incidents")
    if log:
        ax.set_yscale("log")
    return _save(fig, name)


def _corr_heatmap(df: pd.DataFrame, cols: list[str], title: str, name: str) -> dict:
    mat = pd.DataFrame({a: {b: cramers_v(df[a], df[b]) for b in cols} for a in cols})
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(mat.values, vmin=0, vmax=1, cmap="viridis")
    ax.set_xticks(range(len(cols)), cols, rotation=60, ha="right")
    ax.set_yticks(range(len(cols)), cols)
    fig.colorbar(im, ax=ax, label="Cramér's V")
    ax.set_title(title)
    _save(fig, name)
    return {a: {b: round(float(v), 3) for b, v in mat[a].items()} for a in cols}


def eda_tickets(df: pd.DataFrame) -> dict:
    out: dict = {"figures": []}
    out["figures"].append(
        _bar(
            df["category"].value_counts(),
            "Tickets: category distribution (real)",
            "tickets_class_dist",
        )
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(df["description"].str.len().clip(upper=600), bins=50)
    ax.set_title("Tickets: text length (chars, clipped at 600; real)")
    ax.set_xlabel("characters")
    out["figures"].append(_save(fig, "tickets_text_length"))
    tr, te = df[df.author_split == "train"], df[df.author_split == "test"]
    n_tr = set(tr["description"].map(normalize_text))
    out["test_texts_also_in_train_exact"] = round(float(te["description"].isin(set(tr["description"])).mean()), 4)
    out["test_texts_also_in_train_normalized"] = round(
        float(te["description"].map(normalize_text).isin(n_tr).mean()), 4
    )
    out["note"] = "No timestamps, teams, priority or impact exist in this dataset."
    return out


def eda_uci(df: pd.DataFrame) -> dict:
    out: dict = {"figures": []}
    g = df["assignment_group"].value_counts()
    out["figures"].append(
        _bar(
            g,
            "UCI: incidents per first-event assignment group (top 30, log; real)",
            "uci_group_dist",
            log=True,
        )
    )
    out["figures"].append(
        _bar(
            df["category"].value_counts(),
            "UCI: category distribution (top 30; real)",
            "uci_category_dist",
        )
    )
    weekly = df.set_index("created_at").resample("W").size()
    fig, ax = plt.subplots(figsize=(8, 3.5))
    weekly.plot(ax=ax)
    ax.set_title("UCI: incident volume per week (real)")
    ax.set_ylabel("incidents")
    out["figures"].append(_save(fig, "uci_volume_over_time"))
    out["group_top1_share"] = round(float(g.iloc[0] / g.sum()), 4)
    out["groups_with_lt_30_incidents"] = int((g < 30).sum())
    out["first_vs_final_group_agree"] = round(float((df["assignment_group"] == df["final_assignment_group"]).mean()), 4)
    cols = [
        "impact",
        "urgency",
        "priority",
        "category",
        "subcategory",
        "location",
        "contact_type",
        "assignment_group",
    ]
    tmp = df.copy()
    tmp[["impact", "urgency"]] = tmp[["impact", "urgency"]].astype("object")
    out["cramers_v"] = _corr_heatmap(tmp, cols, "UCI: association between fields (real)", "uci_cramers_v")
    out["figures"].append("uci_cramers_v.png")
    return out


def eda_synthetic(df: pd.DataFrame) -> dict:
    out: dict = {"figures": [], "warning": "SYNTHETIC demo data"}
    out["figures"].append(
        _bar(
            df["assignment_group"].value_counts(),
            "SYNTHETIC: team distribution",
            "synthetic_team_dist",
        )
    )
    weekly = df.set_index("created_at").resample("W").size()
    fig, ax = plt.subplots(figsize=(8, 3.5))
    weekly.plot(ax=ax)
    ax.set_title("SYNTHETIC: incident volume per week")
    out["figures"].append(_save(fig, "synthetic_volume_over_time"))
    cols = ["category", "assignment_group", "service", "impact", "urgency", "priority"]
    tmp = df.copy()
    tmp[["impact", "urgency"]] = tmp[["impact", "urgency"]].astype(str)
    out["cramers_v"] = _corr_heatmap(tmp, cols, "SYNTHETIC: association between fields", "synthetic_cramers_v")
    out["figures"].append("synthetic_cramers_v.png")
    return out


def run_all(tickets: pd.DataFrame, uci: pd.DataFrame, synth: pd.DataFrame) -> dict:
    res = {"tickets": eda_tickets(tickets), "uci": eda_uci(uci), "synthetic": eda_synthetic(synth)}
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (C.RESULTS_DIR / "eda_summary.json").write_text(json.dumps(res, indent=2))
    return res
