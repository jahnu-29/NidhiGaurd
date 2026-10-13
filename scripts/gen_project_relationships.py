"""
One-off conversion script for Stage 5B.5.

Reads intelligence/output/relationship_results.json (Stage 5A, unmodified)
and writes a COMPACT frontend module containing only the PROJECT_PROJECT
analytical relationships needed by ProjectInvestigationPage: for each of the
200 projects, its top 5 strongest PROJECT_PROJECT relationships (by
relationship_strength), unioned and de-duplicated by pair.

This mirrors the existing convention in src/data/generated/contractorNetwork.ts
(only converting the slice a page actually needs, never the full ~9,407-row
pairwise array, to avoid bundling ~6MB of JSON nobody renders).

No relationship is recalculated, re-ranked by anything other than Stage 5A's
own relationship_strength, or invented. Every field is passed through
verbatim from Stage 5A's output.
"""
import json
from collections import defaultdict

SRC = "intelligence/output/relationship_results.json"
OUT = "src/data/generated/projectRelationships.ts"
TOP_K = 5

with open(SRC) as f:
    data = json.load(f)

rels = [r for r in data["relationships"] if r["relationship_type"] == "PROJECT_PROJECT"]

by_project = defaultdict(list)
for r in rels:
    by_project[r["source"]].append(r)
    by_project[r["target"]].append(r)

selected = {}
for pid, lst in by_project.items():
    top = sorted(lst, key=lambda r: -r["relationship_strength"])[:TOP_K]
    for r in top:
        key = tuple(sorted([r["source"], r["target"]]))
        # keep the highest-strength copy if seen twice (identical either way)
        if key not in selected:
            selected[key] = r

# Deterministic order: sort by strength desc, then by source/target id.
ordered = sorted(selected.values(), key=lambda r: (-r["relationship_strength"], r["source"], r["target"]))


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def num(v):
    if v is None:
        return "null"
    return json.dumps(v)


lines = []
lines.append("// AUTO-GENERATED from intelligence/output/relationship_results.json — DO NOT EDIT BY HAND.")
lines.append("// Regenerate via scripts/gen_project_relationships.py, the same way")
lines.append("// src/data/generated/riskResults.ts is produced from risk_results.json.")
lines.append("//")
lines.append("// This is a DELIBERATELY TRIMMED slice of Stage 5A's `relationships` array,")
lines.append("// filtered to relationship_type === \"PROJECT_PROJECT\" only (direct FK edges")
lines.append("// like PROJECT_CONTRACTOR/PROJECT_BILL/PROJECT_LOCATION are already available")
lines.append("// via src/data/access.ts and are not duplicated here). For each of the 200")
lines.append(f"// projects, only its top {TOP_K} strongest PROJECT_PROJECT relationships (by Stage")
lines.append("// 5A's own relationship_strength) are kept, unioned and de-duplicated by pair")
lines.append(f"// ({len(ordered)} unique relationships total, out of {len(rels)} Stage 5A computed).")
lines.append("// This mirrors why src/data/generated/contractorNetwork.ts excludes the full")
lines.append("// pairwise array: nothing on this page needs the complete ~9,407-row dataset,")
lines.append("// and importing it would bloat the bundle for data mostly unused.")
lines.append("//")
lines.append("// No relationship_strength value here is recalculated, re-weighted, or invented —")
lines.append("// every number and evidence field is exactly what Stage 5A")
lines.append("// (intelligence/relationship_analysis.py) computed. Selection by top-K per")
lines.append("// project only decides WHICH rows are shipped to the browser, not their values.")
lines.append("")
lines.append("export interface ProjectRelationshipEvidence {")
lines.append("  sameContractor: boolean;")
lines.append("  sameWorkType: boolean;")
lines.append("  sameDistrict: boolean;")
lines.append("  sameState: boolean;")
lines.append("  distanceKm: number | null;")
lines.append("  descriptionSimilarity: number | null;")
lines.append("  costSimilarity: number | null;")
lines.append("  dateProximity: number | null;")
lines.append("}")
lines.append("")
lines.append("export interface ProjectRelationship {")
lines.append("  source: string;")
lines.append("  target: string;")
lines.append("  relationshipStrength: number;")
lines.append("  evidence: ProjectRelationshipEvidence;")
lines.append("  explanation: string;")
lines.append("}")
lines.append("")
lines.append('export const PROJECT_RELATIONSHIP_DISCLAIMER =')
lines.append('  "Relationship strength is an analytical relationship measure, not a fraud probability or risk score.";')
lines.append("")
lines.append(f"// Top {TOP_K} PROJECT_PROJECT relationships per project, unioned across all 200")
lines.append("// projects and de-duplicated by pair. Not every project necessarily appears —")
lines.append("// only those Stage 5A found at least one PROJECT_PROJECT relationship for.")
lines.append("export const PROJECT_RELATIONSHIPS: ProjectRelationship[] = [")
for r in ordered:
    e = r["evidence"]
    ev = (
        "{ "
        f'sameContractor: {json.dumps(e["same_contractor"])}, '
        f'sameWorkType: {json.dumps(e["same_work_type"])}, '
        f'sameDistrict: {json.dumps(e["same_district"])}, '
        f'sameState: {json.dumps(e["same_state"])}, '
        f'distanceKm: {num(e.get("distance_km"))}, '
        f'descriptionSimilarity: {num(e.get("description_similarity"))}, '
        f'costSimilarity: {num(e.get("cost_similarity"))}, '
        f'dateProximity: {num(e.get("date_proximity"))} '
        "}"
    )
    lines.append(
        "  { "
        f'source: "{r["source"]}", target: "{r["target"]}", '
        f'relationshipStrength: {r["relationship_strength"]}, '
        f'evidence: {ev}, '
        f'explanation: "{esc(r["explanation"])}" '
        "},"
    )
lines.append("];")
lines.append("")

with open(OUT, "w") as f:
    f.write("\n".join(lines))

print(f"Wrote {OUT}: {len(ordered)} relationships covering {len(by_project)} projects")
