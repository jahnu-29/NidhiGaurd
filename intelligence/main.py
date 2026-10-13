"""
NidhiGuard Intelligence — Batch Analysis Entry Point

Runs the risk engine over every current project and writes:
  intelligence/output/risk_results.json
  intelligence/output/risk_results.csv

Usage:
    python -m intelligence.main
    python intelligence/main.py

anomaly_signals.csv is loaded ONLY to print a validation comparison against
the independently-computed scores at the end of the run — it is never
passed into the risk engine or any detector.
"""
from __future__ import annotations

import csv
import json
import os

from .data_loader import load_dataset, DEFAULT_DATA_DIR
from .risk_engine import build_engine, DISCLAIMER

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def run(data_dir: str = DEFAULT_DATA_DIR, output_dir: str = OUTPUT_DIR) -> list[dict]:
    dataset = load_dataset(data_dir)
    engine = build_engine(dataset)
    results = engine.score_all()
    result_dicts = [r.to_dict() for r in results]

    os.makedirs(output_dir, exist_ok=True)

    sorted_results = sorted(result_dicts, key=lambda r: r["risk_score"], reverse=True)

    json_path = os.path.join(output_dir, "risk_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "disclaimer": DISCLAIMER,
            "project_count": len(sorted_results),
            "results": sorted_results,
        }, f, indent=2, default=str)

    csv_path = os.path.join(output_dir, "risk_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "project_id", "risk_score", "risk_level", "recommendation",
            "cost_anomaly_score", "project_similarity_score",
            "contractor_pattern_score", "billing_anomaly_score", "geographic_signal_score",
        ])
        for r in sorted_results:
            c = r["components"]
            writer.writerow([
                r["project_id"], r["risk_score"], r["risk_level"], r["recommendation"],
                c["cost_anomaly"]["score"], c["project_similarity"]["score"],
                c["contractor_pattern"]["score"], c["billing_anomaly"]["score"],
                c["geographic_signal"]["score"],
            ])

    print(f"Analyzed {len(sorted_results)} projects.")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print()
    print("Top 10 by risk_score:")
    for r in sorted_results[:10]:
        print(f"  {r['project_id']}  {r['risk_score']:>5}/100  {r['risk_level']:<8}  {r['recommendation']}")

    _print_validation_comparison(dataset, {r["project_id"]: r for r in result_dicts})

    return sorted_results


def _print_validation_comparison(dataset, results_by_id: dict) -> None:
    """Reference-only comparison against the planted ground truth. Not used
    anywhere in the scoring path above — this runs strictly after scoring."""
    signals = dataset.anomaly_signals
    if signals.empty:
        return

    planted_ids = set(signals["project_id"])
    print()
    print("-" * 60)
    print("Validation reference (anomaly_signals.csv, NOT used for scoring):")
    print(f"  Projects with at least one planted signal: {len(planted_ids)}")

    scores_planted = [results_by_id[pid]["risk_score"] for pid in planted_ids if pid in results_by_id]
    all_ids = set(results_by_id.keys())
    scores_normal = [results_by_id[pid]["risk_score"] for pid in (all_ids - planted_ids)]

    if scores_planted and scores_normal:
        avg_planted = sum(scores_planted) / len(scores_planted)
        avg_normal = sum(scores_normal) / len(scores_normal)
        print(f"  Avg independently-computed risk_score for planted-signal projects: {avg_planted:.1f}")
        print(f"  Avg independently-computed risk_score for normal projects:         {avg_normal:.1f}")
    print("-" * 60)


if __name__ == "__main__":
    run()
