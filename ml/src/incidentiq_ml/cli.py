"""Command line: `servicenow-pull` then `servicenow-train` (primary); other commands are the legacy public-data pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import config as C
from . import data, eda, pipeline
from . import validation as V


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="incidentiq_ml")
    ap.add_argument(
        "command",
        choices=["servicenow-pull", "servicenow-train", "download", "prepare", "validate", "eda", "train", "all"],
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="tiny hyper-parameter grid (smoke test only)",
    )
    ap.add_argument("--model-dir", type=Path, default=None)
    ns = ap.parse_args(argv)
    cmds = ["download", "prepare", "validate", "eda", "train"] if ns.command == "all" else [ns.command]
    for c in cmds:
        if c == "servicenow-pull":
            from . import servicenow_data

            print(servicenow_data.pull())
        elif c == "servicenow-train":
            from . import servicenow_tasks

            status = servicenow_tasks.run_all(fast=ns.fast, model_dir=ns.model_dir or C.ARTIFACT_DIR)
            for task, info in status["tasks"].items():
                print(f"  {task}: {info['status']} {info.get('reason', '')}")
        elif c == "download":
            data.download_all()
        elif c == "prepare":
            print(data.prepare_all())
        elif c == "validate":
            for n, t in (
                ("tickets", ["category"]),
                ("uci_incidents", ["assignment_group", "category", "priority"]),
                ("synthetic_incidents", ["category", "assignment_group", "priority"]),
            ):
                V.write_report(V.report(data.load(n), n, t))
        elif c == "eda":
            eda.run_all(
                data.load("tickets"),
                data.load("uci_incidents"),
                data.load("synthetic_incidents"),
            )
        elif c == "train":
            pipeline.run_all(fast=ns.fast, model_dir=ns.model_dir or C.ARTIFACT_DIR)
        print(f"[{c}] done")


if __name__ == "__main__":
    main()
