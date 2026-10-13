// Frontend data-access adapter for Stage 5A's project-to-project analytical
// relationships (the PROJECT_PROJECT slice of
// intelligence/output/relationship_results.json — see
// src/data/generated/projectRelationships.ts for what was kept and why).
//
// Performs NO relationship calculation of its own. relationship_strength,
// distance, similarity, and every other value here is exactly what Stage 5A
// (intelligence/relationship_analysis.py) computed. This module only
// indexes that output for per-project lookups, the same pattern
// src/data/riskResults.ts and src/data/geographicResults.ts use.
//
// IMPORTANT: relationship strength answers "what is this project connected
// to?" — it is never a risk score and must never be blended with, or
// presented as, a Stage 4 risk value.

import {
  PROJECT_RELATIONSHIPS,
  PROJECT_RELATIONSHIP_DISCLAIMER,
} from "./generated/projectRelationships";
import type { ProjectRelationship, ProjectRelationshipEvidence } from "./generated/projectRelationships";

export type { ProjectRelationship, ProjectRelationshipEvidence };
export { PROJECT_RELATIONSHIP_DISCLAIMER };

const relationshipsByProjectId = new Map<string, ProjectRelationship[]>();
for (const r of PROJECT_RELATIONSHIPS) {
  (relationshipsByProjectId.get(r.source) ?? relationshipsByProjectId.set(r.source, []).get(r.source)!).push(r);
  (relationshipsByProjectId.get(r.target) ?? relationshipsByProjectId.set(r.target, []).get(r.target)!).push(r);
}
for (const list of relationshipsByProjectId.values()) {
  list.sort((a, b) => b.relationshipStrength - a.relationshipStrength);
}

/**
 * This project's strongest analytical PROJECT_PROJECT relationships (either
 * direction), already sorted by Stage 5A's relationship_strength descending.
 * Only the top 5 per project were shipped to the frontend (see the generated
 * module) — this is display data, not the full Stage 5A dataset.
 */
export function getRelationshipsForProject(projectId: string): ProjectRelationship[] {
  return relationshipsByProjectId.get(projectId) ?? [];
}

/** Given a relationship and "this" project's ID, returns the other project's ID. */
export function otherRelatedProjectId(rel: { source: string; target: string }, projectId: string): string {
  return rel.source === projectId ? rel.target : rel.source;
}
