// Frontend data-access adapter for Stage 5A's contractor network intelligence
// (the `contractors` and `multi_hop_paths` sections of
// intelligence/output/relationship_results.json).
//
// This performs NO relationship calculation of its own — every value here is
// exactly what Stage 5A (intelligence/relationship_analysis.py) computed.
// It does not touch relationship_strength beyond passing it through for
// display, and it never derives a contractor risk score from any of this.
//
// See src/data/generated/contractorNetwork.ts for why only the contractor
// summaries and multi-hop paths were converted to a frontend module, and not
// the full 9,407-relationship pairwise dataset.

import { CONTRACTOR_NETWORK_PROFILES, MULTI_HOP_PATHS } from "./generated/contractorNetwork";
import type { ContractorNetworkProfile, MultiHopPath } from "./generated/contractorNetwork";

export type { ContractorNetworkProfile, MultiHopPath, MultiHopNode, MultiHopHop, NetworkNodeType } from "./generated/contractorNetwork";

const profileByContractorId = new Map<string, ContractorNetworkProfile>(
  CONTRACTOR_NETWORK_PROFILES.map((p) => [p.contractorId, p])
);

/**
 * A contractor's Stage 5A network profile (work types, districts, states,
 * connected project IDs, internal project pairs). Undefined for contractors
 * with no current-dataset project — Stage 5A only profiles contractors that
 * have at least one project to build a network from.
 */
export function getContractorNetwork(contractorId: string): ContractorNetworkProfile | undefined {
  return profileByContractorId.get(contractorId);
}

/**
 * Every multi-hop path (PROJECT -> CONTRACTOR -> PROJECT[ -> LOCATION])
 * that passes through this contractor. Small list (146 total across all
 * contractors) — filtered here, not recomputed.
 */
export function getMultiHopPathsForContractor(contractorId: string): MultiHopPath[] {
  return MULTI_HOP_PATHS.filter((path) => path.nodes.some((n) => n.type === "CONTRACTOR" && n.id === contractorId));
}

/**
 * Every multi-hop path that passes through this project (as any PROJECT node
 * in the chain, e.g. PROJECT -> CONTRACTOR -> PROJECT[ -> LOCATION]). Same
 * pre-computed 146-path list as getMultiHopPathsForContractor, filtered
 * differently — added for Stage 5B.5's Project Investigation page.
 */
export function getMultiHopPathsForProject(projectId: string): MultiHopPath[] {
  return MULTI_HOP_PATHS.filter((path) => path.nodes.some((n) => n.type === "PROJECT" && n.id === projectId));
}
