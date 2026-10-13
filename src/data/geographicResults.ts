// Frontend data-access adapter for Stage 5A's geospatial intelligence output
// (intelligence/output/geographic_results.json).
//
// Performs NO geographic calculation of its own — no distance, similarity,
// or clustering logic lives here. Every value is exactly what Stage 5A
// (intelligence/geographic_intelligence.py) computed with a 2km radius.
// This module only indexes that output for O(1)/filtered lookups by
// project ID, the same pattern src/data/riskResults.ts uses for Stage 4.

import {
  NEARBY_PROJECT_RELATIONSHIPS,
  DUPLICATE_LIKE_MATCHES,
  GEOGRAPHIC_CLUSTERS,
  GEOGRAPHIC_DISCLAIMER,
  GEOGRAPHIC_RADIUS_KM,
} from "./generated/geographicResults";
import type {
  NearbyProjectRelationship,
  DuplicateLikeMatch,
  GeographicCluster,
} from "./generated/geographicResults";

export type { NearbyProjectRelationship, DuplicateLikeMatch, GeographicCluster };
export { GEOGRAPHIC_DISCLAIMER, GEOGRAPHIC_RADIUS_KM };

const nearbyByProjectId = new Map<string, NearbyProjectRelationship[]>();
for (const r of NEARBY_PROJECT_RELATIONSHIPS) {
  (nearbyByProjectId.get(r.source) ?? nearbyByProjectId.set(r.source, []).get(r.source)!).push(r);
  (nearbyByProjectId.get(r.target) ?? nearbyByProjectId.set(r.target, []).get(r.target)!).push(r);
}

const duplicateLikeByProjectId = new Map<string, DuplicateLikeMatch[]>();
for (const m of DUPLICATE_LIKE_MATCHES) {
  (duplicateLikeByProjectId.get(m.projectA) ?? duplicateLikeByProjectId.set(m.projectA, []).get(m.projectA)!).push(m);
  (duplicateLikeByProjectId.get(m.projectB) ?? duplicateLikeByProjectId.set(m.projectB, []).get(m.projectB)!).push(m);
}

const clustersByProjectId = new Map<string, GeographicCluster[]>();
for (const c of GEOGRAPHIC_CLUSTERS) {
  for (const pid of c.projectIds) {
    (clustersByProjectId.get(pid) ?? clustersByProjectId.set(pid, []).get(pid)!).push(c);
  }
}

export function getAllNearbyRelationships(): NearbyProjectRelationship[] {
  return NEARBY_PROJECT_RELATIONSHIPS;
}

/** Every nearby-project relationship (either direction) involving this project. */
export function getNearbyRelationshipsForProject(projectId: string): NearbyProjectRelationship[] {
  return nearbyByProjectId.get(projectId) ?? [];
}

/** Given a relationship and "this" project's ID, returns the other project's ID. */
export function otherProjectId(rel: { source: string; target: string }, projectId: string): string {
  return rel.source === projectId ? rel.target : rel.source;
}

export function getAllDuplicateLikeMatches(): DuplicateLikeMatch[] {
  return DUPLICATE_LIKE_MATCHES;
}

export function getDuplicateLikeMatchesForProject(projectId: string): DuplicateLikeMatch[] {
  return duplicateLikeByProjectId.get(projectId) ?? [];
}

export function getAllGeographicClusters(): GeographicCluster[] {
  return GEOGRAPHIC_CLUSTERS;
}

export function getClustersForProject(projectId: string): GeographicCluster[] {
  return clustersByProjectId.get(projectId) ?? [];
}

/** True if this project appears anywhere in Stage 5A's geographic output —
 * used only to visually distinguish markers with geographic context, never
 * as a risk indicator. */
export function hasGeographicContext(projectId: string): boolean {
  return (
    (nearbyByProjectId.get(projectId)?.length ?? 0) > 0 ||
    (clustersByProjectId.get(projectId)?.length ?? 0) > 0
  );
}
