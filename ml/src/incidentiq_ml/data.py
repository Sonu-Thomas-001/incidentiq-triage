"""Download, verify and prepare the public datasets. Raw files stay out of Git."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pandas as pd

from . import config as C


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _get(url: str) -> bytes:
    import requests

    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def download_all(force: bool = False) -> None:
    """Fetch both real datasets and verify their pinned SHA-256 digests."""
    tdir = C.RAW_DIR / "zenodo_tickets"
    tdir.mkdir(parents=True, exist_ok=True)
    for name, digest in C.ZENODO_FILES.items():
        dest = tdir / name
        if force or not dest.exists():
            dest.write_bytes(_get(f"{C.ZENODO_BASE}/{name}/content"))
        if sha256_file(dest) != digest:
            raise RuntimeError(f"Checksum mismatch for {name}; refusing to use it")
    udir = C.RAW_DIR / "uci"
    udir.mkdir(parents=True, exist_ok=True)
    csv = udir / "incident_event_log.csv"
    if force or not csv.exists():
        with zipfile.ZipFile(io.BytesIO(_get(C.UCI_URL))) as z:
            csv.write_bytes(z.read("incident_event_log.csv"))
    if sha256_file(csv) != C.UCI_CSV_SHA256:
        raise RuntimeError("Checksum mismatch for incident_event_log.csv")


def prepare_tickets() -> pd.DataFrame:
    d = C.RAW_DIR / "zenodo_tickets"
    parts = []
    for split in ("train", "test"):
        x = pd.read_csv(d / f"X_{split}.csv")
        y = pd.read_csv(d / f"y_{split}.csv")
        m = x.merge(y, on="id", validate="one_to_one")
        m["author_split"] = split
        parts.append(m)
    df = pd.concat(parts, ignore_index=True)
    df = df.rename(columns={"id": "incident_id", "text": "description", "category_truth": "category"})
    df["description"] = df["description"].fillna("").astype(str)
    df["short_description"] = df["description"].str.split(r"[\n.!?]", n=1, regex=True).str[0].str.slice(0, 120)
    df["incident_id"] = "TKT-" + df["incident_id"].astype(str)
    df["provenance"] = C.PROV_REAL
    return df[["incident_id", "short_description", "description", "category", "author_split", "provenance"]]


def prepare_uci() -> pd.DataFrame:
    """One row per incident using ONLY the first logged event (state at opening time)."""
    raw = pd.read_csv(C.RAW_DIR / "uci" / "incident_event_log.csv", dtype=str, na_values=["?"])
    raw["_mod"] = pd.to_numeric(raw["sys_mod_count"], errors="coerce")
    raw = raw.sort_values(["number", "_mod"], kind="stable")
    first = raw.groupby("number", sort=False).head(1).copy()
    last = raw.groupby("number", sort=False).tail(1).set_index("number")["assignment_group"]
    first["created_at"] = pd.to_datetime(first["opened_at"], format="%d/%m/%Y %H:%M")
    out = first.rename(columns={"number": "incident_id"})[
        [
            "incident_id", "created_at", "category", "subcategory", "u_symptom", "contact_type",
            "location", "impact", "urgency", "priority", "assignment_group",
        ]
    ].copy()  # fmt: skip
    for col in ("impact", "urgency"):  # "2 - Medium" -> 2 (1 = highest)
        out[col] = pd.to_numeric(out[col].str[0], errors="coerce").astype("Int64")
    out["final_assignment_group"] = out["incident_id"].map(last)  # analysis only, never a predictor
    out["provenance"] = C.PROV_REAL
    return out.sort_values("created_at", kind="stable").reset_index(drop=True)


def fingerprint(df: pd.DataFrame) -> str:
    """Order-independent content hash of a dataframe."""
    h = pd.util.hash_pandas_object(df.astype(str), index=False).values
    return hashlib.sha256(h.tobytes()).hexdigest()[:16]


def prepare_all(n_synthetic: int = 3000) -> dict[str, Path]:
    from .synthetic import generate

    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, df in (
        ("tickets", prepare_tickets()),
        ("uci_incidents", prepare_uci()),
        ("synthetic_incidents", generate(n_synthetic, seed=C.SEED)),
    ):
        p = C.PROCESSED_DIR / f"{name}.parquet"
        df.to_parquet(p, index=False)
        paths[name] = p
    return paths


def load(name: str) -> pd.DataFrame:
    p = C.PROCESSED_DIR / f"{name}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `python -m incidentiq_ml prepare`")
    return pd.read_parquet(p)
