"""Persist models with joblib plus a manifest (versions, config, class mapping, metrics, hashes).

Security: joblib/pickle files can execute code when loaded. Only load artifacts that you produced
yourself; the backend additionally verifies the SHA-256 recorded in the manifest.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn


def library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pandas": pd.__version__,
        "joblib": joblib.__version__,
    }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_artifact(model_dir: Path, key: str, bundle: dict, info: dict) -> dict:
    model_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{key}.joblib"
    path = model_dir / fname
    joblib.dump(bundle, path, compress=3)
    entry = {
        **info,
        "key": key,
        "file": fname,
        "sha256": sha256_of(path),
        "library_versions": library_versions(),
        "trained_at": datetime.now(UTC).isoformat(),
    }
    mpath = model_dir / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"schema_version": 1, "models": {}}
    manifest["models"][key] = entry
    mpath.write_text(json.dumps(manifest, indent=2, default=str))
    return entry
