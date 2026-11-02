"""
NidhiGuard V2.1 - run the UNMODIFIED V1 engine on the evaluation pool.

Writes (engine outputs only, no ground truth):
    <dir>/evaluation_predictions.csv        one row per project, total + 5 component scores
    <dir>/evaluation_predictions_meta.json  input hashes + hashes of the engine source files used

Safety checks
    * Refuses to run if engine_input/ no longer matches the SHA-256 hashes frozen in
      evaluation_metadata.json (override only with --allow-changed, and log it in CHANGELOG.md).
    * Never opens the label file. Metrics are V2.2's job; none are computed here.

Usage (repo root):
    python -m evaluation.run_v1_predictions --dir evaluation
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import subprocess
import sys

from intelligence.data_loader import load_dataset
from intelligence.risk_engine import build_engine


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="evaluation")
    ap.add_argument("--allow-changed", action="store_true")
    a = ap.parse_args()

    eng_dir = os.path.join(a.dir, "engine_input")
    with open(os.path.join(a.dir, "evaluation_metadata.json"), encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    current = {k: _sha(os.path.join(a.dir, k)) for k in frozen if k.startswith("engine_input/")}
    drift = [k for k, h in current.items() if frozen[k] != h]
    if drift and not a.allow_changed:
        print("REFUSING TO RUN: engine input differs from the frozen hashes:", drift, file=sys.stderr)
        return 2

    ds = load_dataset(eng_dir)
    results = build_engine(ds).score_all()
    rows = []
    for r in results:
        d = r.to_dict()
        c = d["components"]
        rows.append({
            "project_id": d["project_id"], "risk_score": d["risk_score"], "risk_level": d["risk_level"],
            "recommendation": d["recommendation"],
            "cost_anomaly_score": c["cost_anomaly"]["score"],
            "project_similarity_score": c["project_similarity"]["score"],
            "contractor_pattern_score": c["contractor_pattern"]["score"],
            "billing_anomaly_score": c["billing_anomaly"]["score"],
            "geographic_signal_score": c["geographic_signal"]["score"],
        })
    rows.sort(key=lambda x: x["project_id"])      # ID order, deliberately NOT score order
    out = os.path.join(a.dir, "evaluation_predictions.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    engine_files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intelligence", "*.py")))
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = ""
    meta = {
        "projects_scored": len(rows),
        "engine_input_sha256": current,
        "engine_source_sha256": {os.path.basename(f): _sha(f) for f in engine_files},
        "git_commit_at_run": commit or "unavailable",
        "frozen_hash_check": "passed" if not drift else f"OVERRIDDEN, drift in {drift}",
        "note": "Engine outputs only. No labels were read. No metrics were computed.",
    }
    with open(os.path.join(a.dir, "evaluation_predictions_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")
    print(f"Wrote {out} ({len(rows)} projects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
