"""
NidhiGuard Intelligence — Stage 5A Batch Entry Point

Runs the relationship and geospatial intelligence engines over the full
current dataset and writes:

  intelligence/output/relationship_results.json
  intelligence/output/relationship_results.csv
  intelligence/output/geographic_results.json
  intelligence/output/geographic_results.csv

This is a NEW, separate entry point from main.py (Stage 4). It does not
import risk_engine and does not touch risk_results.json/csv.

Usage:
    python -m intelligence.stage5a_main
    python intelligence/stage5a_main.py
"""
from __future__ import annotations

import csv
import json
import os

from .data_loader import load_dataset, DEFAULT_DATA_DIR
from .relationship_analysis import (
    build_relationship_index,
    build_direct_edges,
    build_contractor_network,
    build_multi_hop_paths,
    generate_project_relationships,
    RELATIONSHIP_REPORT_THRESHOLD,
)
from .geographic_intelligence import (
    build_geospatial_engine,
    find_duplicate_like_matches,
    build_geographic_clusters,
    DEFAULT_RADIUS_KM,
)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

RELATIONSHIP_DISCLAIMER = (
    "Relationship strength indicates how strongly two entities are connected "
    "according to available data. It does not represent fraud, collusion, or "
    "corruption probability."
)
GEOGRAPHIC_DISCLAIMER = (
    "Geographic proximity is contextual information for investigators. "
    "Proximity alone is never treated as an anomaly."
)


def run(data_dir: str = DEFAULT_DATA_DIR, output_dir: str = OUTPUT_DIR) -> dict:
    dataset = load_dataset(data_dir)
    os.makedirs(output_dir, exist_ok=True)

    # ---------------- Part 1: Relationship intelligence ----------------
    rel_index = build_relationship_index(dataset.projects, dataset.locations)
    project_relationships = generate_project_relationships(rel_index)
    direct_edges = build_direct_edges(dataset)
    contractor_network = build_contractor_network(dataset)
    multi_hop_paths = build_multi_hop_paths(dataset, project_relationships)

    all_relationships = direct_edges + project_relationships

    relationship_output = {
        "disclaimer": RELATIONSHIP_DISCLAIMER,
        "methodology": {
            "relationship_strength_formula": (
                "same_contractor=20 + same_work_type=10 + same_district=10 + "
                "proximity(up to 15, linear decay to 0 at 10km) + "
                "description_similarity*25 + cost_similarity*10 + "
                "date_proximity(up to 10, linear decay to 0 at 365 days)"
            ),
            "report_threshold": RELATIONSHIP_REPORT_THRESHOLD,
            "direct_edges_strength": "always 100 (deterministic foreign-key relationship, not inferred)",
        },
        "projects": [
            {"project_id": pid, "contractor_id": row["contractor_id"]}
            for pid, row in zip(dataset.projects["project_id"], dataset.projects.to_dict("records"))
        ],
        "contractors": contractor_network,
        "relationships": all_relationships,
        "multi_hop_paths": multi_hop_paths,
    }

    rel_json_path = os.path.join(output_dir, "relationship_results.json")
    with open(rel_json_path, "w", encoding="utf-8") as f:
        json.dump(relationship_output, f, indent=2, default=str)

    rel_csv_path = os.path.join(output_dir, "relationship_results.csv")
    with open(rel_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source", "target", "relationship_type", "relationship_strength",
            "same_contractor", "same_work_type", "same_district", "same_state",
            "distance_km", "description_similarity", "cost_similarity", "date_proximity",
        ])
        for r in all_relationships:
            ev = r.get("evidence", {}) if isinstance(r.get("evidence"), dict) else {}
            writer.writerow([
                r["source"], r["target"], r["relationship_type"], r["relationship_strength"],
                ev.get("same_contractor", ""), ev.get("same_work_type", ""),
                ev.get("same_district", ""), ev.get("same_state", ""),
                ev.get("distance_km", ""), ev.get("description_similarity", ""),
                ev.get("cost_similarity", ""), ev.get("date_proximity", ""),
            ])

    # ---------------- Part 2: Geospatial intelligence ----------------
    geo_engine = build_geospatial_engine(dataset, radius_km=DEFAULT_RADIUS_KM, relationship_index=rel_index)
    nearby_flat = geo_engine.all_nearby_relationships()
    duplicate_like = find_duplicate_like_matches(nearby_flat)
    clusters = build_geographic_clusters(geo_engine)

    geographic_output = {
        "disclaimer": GEOGRAPHIC_DISCLAIMER,
        "radius_km": DEFAULT_RADIUS_KM,
        "project_nearby_relationships": nearby_flat,
        "duplicate_like_matches": duplicate_like,
        "clusters": clusters,
    }

    geo_json_path = os.path.join(output_dir, "geographic_results.json")
    with open(geo_json_path, "w", encoding="utf-8") as f:
        json.dump(geographic_output, f, indent=2, default=str)

    geo_csv_path = os.path.join(output_dir, "geographic_results.csv")
    with open(geo_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source", "target", "distance_km", "same_work_type", "same_contractor",
            "description_similarity", "cost_similarity", "date_proximity", "relationship_strength",
        ])
        for r in nearby_flat:
            writer.writerow([
                r["source"], r["target"], r["distance_km"], r["same_work_type"], r["same_contractor"],
                r["description_similarity"], r["cost_similarity"], r["date_proximity"], r["relationship_strength"],
            ])

    print(f"Relationships generated: {len(project_relationships)} analytical + {len(direct_edges)} direct edges")
    print(f"Contractors profiled: {len(contractor_network)}")
    print(f"Multi-hop paths: {len(multi_hop_paths)}")
    print(f"Wrote {rel_json_path}")
    print(f"Wrote {rel_csv_path}")
    print()
    print(f"Geographic nearby pairs (<= {DEFAULT_RADIUS_KM} km): {len(nearby_flat)}")
    print(f"Potential duplicate-like matches: {len(duplicate_like)}")
    print(f"Geographic clusters: {len(clusters)}")
    print(f"Wrote {geo_json_path}")
    print(f"Wrote {geo_csv_path}")

    return {
        "relationship_output": relationship_output,
        "geographic_output": geographic_output,
    }


if __name__ == "__main__":
    run()
