// Frontend data-access adapter for the Stage 4 explainable risk engine's
// output (intelligence/output/risk_results.json).
//
// This file exists so RiskAnalysisPage.tsx (and any future page) reads risk
// data through two small functions instead of importing the generated array
// directly in multiple places. It performs NO calculation of its own — every
// score, level, detected flag, and explanation here is exactly what Stage 4
// (intelligence/risk_engine.py) computed. See src/data/generated/riskResults.ts
// for how the raw JSON was converted into this typed module, following the
// same "no runtime parsing in the browser" approach Stage 1 uses for the CSV
// dataset.
//
// Do NOT recompute, normalize, or blend these values with anything from the
// Stage 5A relationship/geographic intelligence output — those answer a
// different question ("what's connected to this project?") and are out of
// scope here.

import { RISK_RESULTS, RISK_DISCLAIMER } from "./generated/riskResults";
import type { ProjectRiskResult, RiskComponentDetail, RiskLevel } from "./generated/riskResults";

export type { ProjectRiskResult, RiskComponentDetail, RiskLevel };
export { RISK_DISCLAIMER };

const riskResultByProjectId = new Map<string, ProjectRiskResult>(
  RISK_RESULTS.map((r) => [r.projectId, r])
);

/** Every project's Stage 4 risk result, in the order the engine produced them. */
export function getAllRiskResults(): ProjectRiskResult[] {
  return RISK_RESULTS;
}

/** A single project's Stage 4 risk result, or undefined if none was computed. */
export function getRiskResult(projectId: string): ProjectRiskResult | undefined {
  return riskResultByProjectId.get(projectId);
}
