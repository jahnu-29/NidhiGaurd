// Data-access layer for the NidhiGuard relational synthetic dataset.
//
// Pages should import from HERE, not from `src/data/generated/*` directly,
// and not (going forward) from the legacy `src/data/synthetic.ts`. This
// keeps the UI decoupled from the raw dataset shape so a future real
// backend, or a re-generated dataset, only requires changes in this file.
//
// All lookups are joined by stable IDs (projectId, contractorId, billId,
// locationId, ...) — never by name — per the integration brief. This is
// what makes future contractor entity-resolution possible without
// rewriting every page.
//
// IMPORTANT: everything returned by this file is descriptive/relational
// data or PLANTED GROUND-TRUTH signals — never a computed risk score. Risk
// scoring belongs in the not-yet-built src/intelligence/ layer.

import { PROJECTS } from "./generated/projects";
import { CONTRACTORS } from "./generated/contractors";
import { BILLS } from "./generated/bills";
import { PAYMENTS } from "./generated/payments";
import { LOCATIONS } from "./generated/locations";
import { HISTORICAL_PROJECTS } from "./generated/historicalProjects";
import { PROJECT_CONTRACTORS } from "./generated/projectContractors";
import { ANOMALY_SIGNALS } from "./generated/anomalySignals";
import type {
  Project,
  Contractor,
  Bill,
  Payment,
  Location,
  HistoricalProject,
  ProjectContractor,
  AnomalySignal,
} from "./types";

// ---- indexes, built once at module load -----------------------------------

const projectsById = new Map<string, Project>(PROJECTS.map((p) => [p.projectId, p]));
const contractorsById = new Map<string, Contractor>(CONTRACTORS.map((c) => [c.contractorId, c]));
const locationsById = new Map<string, Location>(LOCATIONS.map((l) => [l.locationId, l]));
const locationsByProjectId = new Map<string, Location>(LOCATIONS.map((l) => [l.projectId, l]));

const billsByProjectId = new Map<string, Bill[]>();
for (const b of BILLS) {
  const list = billsByProjectId.get(b.projectId) ?? [];
  list.push(b);
  billsByProjectId.set(b.projectId, list);
}

const paymentsByProjectId = new Map<string, Payment[]>();
const paymentsByBillId = new Map<string, Payment[]>();
for (const p of PAYMENTS) {
  const byProject = paymentsByProjectId.get(p.projectId) ?? [];
  byProject.push(p);
  paymentsByProjectId.set(p.projectId, byProject);

  const byBill = paymentsByBillId.get(p.billId) ?? [];
  byBill.push(p);
  paymentsByBillId.set(p.billId, byBill);
}

const projectsByContractorId = new Map<string, Project[]>();
for (const p of PROJECTS) {
  const list = projectsByContractorId.get(p.contractorId) ?? [];
  list.push(p);
  projectsByContractorId.set(p.contractorId, list);
}

const relationshipsByProjectId = new Map<string, ProjectContractor[]>();
for (const r of PROJECT_CONTRACTORS) {
  const list = relationshipsByProjectId.get(r.projectId) ?? [];
  list.push(r);
  relationshipsByProjectId.set(r.projectId, list);
}

const signalsByProjectId = new Map<string, AnomalySignal[]>();
for (const s of ANOMALY_SIGNALS) {
  const list = signalsByProjectId.get(s.projectId) ?? [];
  list.push(s);
  signalsByProjectId.set(s.projectId, list);
}

// ---- public API --------------------------------------------------------------

export function getAllProjects(): Project[] {
  return PROJECTS;
}

export function getProjectById(projectId: string): Project | undefined {
  return projectsById.get(projectId);
}

export function getAllContractors(): Contractor[] {
  return CONTRACTORS;
}

export function getContractorById(contractorId: string): Contractor | undefined {
  return contractorsById.get(contractorId);
}

export function getProjectsByContractor(contractorId: string): Project[] {
  return projectsByContractorId.get(contractorId) ?? [];
}

export function getBillsByProject(projectId: string): Bill[] {
  return billsByProjectId.get(projectId) ?? [];
}

export function getPaymentsByProject(projectId: string): Payment[] {
  return paymentsByProjectId.get(projectId) ?? [];
}

export function getPaymentsByBill(billId: string): Payment[] {
  return paymentsByBillId.get(billId) ?? [];
}

export function getAllLocations(): Location[] {
  return LOCATIONS;
}

export function getLocationByProject(projectId: string): Location | undefined {
  return locationsByProjectId.get(projectId);
}

export function getLocationById(locationId: string): Location | undefined {
  return locationsById.get(locationId);
}

export function getProjectContractorRelationships(projectId: string): ProjectContractor[] {
  return relationshipsByProjectId.get(projectId) ?? [];
}

/**
 * Ground-truth planted anomaly signals for a project. These come directly
 * from anomaly_signals.csv (the data generator's known-answer key) and are
 * NOT the output of any detection logic. Callers must present these as
 * demonstration/ground-truth signals, not as system-detected findings,
 * until a real intelligence layer exists.
 */
export function getSignalsByProject(projectId: string): AnomalySignal[] {
  return signalsByProjectId.get(projectId) ?? [];
}

/**
 * Historical comparable projects for cost-anomaly-style comparison, matched
 * on work type + state per docs/RELATIONSHIPS.md.
 *
 * Note: `projects.csv` only carries an abstract `district_id` (e.g.
 * "DIST-04"), while `historical_projects.csv` carries a human-readable
 * `district` name (e.g. "Mysuru") drawn from an independently-sampled
 * district pool — the two never share a join key, and real-world district
 * names only coincidentally overlap. `state` is the reliable shared
 * attribute, so comparables are matched on work type + state. This
 * performs a plain attribute join (no shared ID exists by design) and
 * returns the matches for the caller to use however's appropriate — it
 * does not itself compute a deviation or flag an anomaly.
 */
export function getHistoricalComparables(project: Project): HistoricalProject[] {
  return HISTORICAL_PROJECTS.filter(
    (h) => h.workType === project.workType && h.state === project.state
  );
}

/**
 * "Related" current projects sharing work type + district as a starting
 * point for geographic/similarity exploration — this is a coarse attribute
 * match, not a distance calculation or text-similarity score. A future
 * src/intelligence/similarProject.ts should replace/refine this.
 */
export function getRelatedProjects(projectId: string): Project[] {
  const project = getProjectById(projectId);
  if (!project) return [];
  return PROJECTS.filter(
    (p) =>
      p.projectId !== projectId &&
      p.workType === project.workType &&
      p.districtId === project.districtId
  );
}

export function getAllHistoricalProjects(): HistoricalProject[] {
  return HISTORICAL_PROJECTS;
}

export function getAllAnomalySignals(): AnomalySignal[] {
  return ANOMALY_SIGNALS;
}
