// Shared type definitions for the NidhiGuard relational synthetic dataset.
// These mirror data-source/docs/DATA_SCHEMA.md field-for-field.
//
// IMPORTANT: this dataset is ground-truth/planted demonstration data only.
// `AnomalySignal` rows are signals the data GENERATOR planted for testing —
// they are NOT the output of an intelligence engine. Nothing in this file
// computes, infers, or asserts a risk score. See src/data/access.ts for the
// read-only data-access layer built on top of these types, and the (not yet
// built) src/intelligence/ layer for actual scoring logic.

export type ProjectStatus = "Completed" | "In Progress" | "Delayed";

export interface Project {
  projectId: string;
  projectCode: string;
  projectName: string;
  projectDescription: string;
  projectCategory: string;
  workType: string;
  mpId: string;
  constituencyId: string;
  districtId: string;
  state: string;
  implementingAgencyId: string;
  contractorId: string;
  locationId: string;
  sanctionedAmount: number;
  estimatedCost: number;
  approvedAmount: number;
  actualExpenditure: number;
  projectStatus: ProjectStatus;
  sanctionDate: string;
  workOrderDate: string;
  startDate: string;
  expectedCompletionDate: string;
  actualCompletionDate: string | null;
  completionPercentage: number;
  createdDate: string;
}

export type ContractorType =
  | "Individual Proprietor"
  | "Partnership Firm"
  | "Pvt Ltd"
  | "Public Works Cooperative"
  | string; // dataset uses a few additional free-form variants (e.g. "Private Limited")

export interface Contractor {
  contractorId: string;
  contractorName: string;
  registrationNumber: string;
  contractorType: ContractorType;
  district: string;
  state: string;
  registrationDate: string;
  activeStatus: "Active" | "Inactive";
  totalProjects: number;
  totalProjectValue: number;
  contactReference: string;
}

export type BillType = "Advance" | "Running Account (RA)" | "Final";
export type BillStatus = "Approved" | "Pending" | "Rejected";

export interface Bill {
  billId: string;
  projectId: string;
  contractorId: string;
  billNumber: string;
  billDate: string;
  billType: BillType;
  claimedAmount: number;
  approvedAmount: number;
  billStatus: BillStatus;
  workPeriodStart: string;
  workPeriodEnd: string;
  submissionDate: string;
  approvalDate: string | null;
}

export type PaymentMode = "PFMS Transfer" | "RTGS" | "Cheque";
export type PaymentStatus = "Success" | "Processing";

export interface Payment {
  paymentId: string;
  billId: string;
  projectId: string;
  contractorId: string;
  paymentDate: string;
  paymentReference: string;
  paymentAmount: number;
  paymentMode: PaymentMode;
  paymentStatus: PaymentStatus;
  approvingAuthority: string;
}

export type LocationType = "Urban Ward" | "Rural Village" | "Panchayat";

export interface Location {
  locationId: string;
  projectId: string;
  state: string;
  district: string;
  constituency: string;
  block: string;
  villageOrWard: string;
  latitude: number;
  longitude: number;
  pincode: string;
  locationType: LocationType;
}

export interface HistoricalProject {
  historicalProjectId: string;
  projectDescription: string;
  projectCategory: string;
  workType: string;
  state: string;
  district: string;
  constituency: string;
  latitude: number;
  longitude: number;
  sanctionedAmount: number;
  actualExpenditure: number;
  completionDate: string;
  contractorId: string;
  implementingAgencyId: string;
}

export interface ProjectContractor {
  relationshipId: string;
  projectId: string;
  contractorId: string;
  role: "Primary Contractor";
  contractValue: number;
  awardDate: string;
}

// Ground-truth signal types planted by the data generator. Distinct from
// (and a superset of) the five friendly signal labels the current UI shows —
// see SIGNAL_TYPE_LABELS below for the mapping used when displaying these.
export type AnomalySignalType =
  | "COST_ANOMALY"
  | "SIMILAR_PROJECT"
  | "CONTRACTOR_PATTERN"
  | "BILLING_ANOMALY"
  | "PAYMENT_ANOMALY"
  | "GEOGRAPHIC_SIGNAL"
  | "MULTI_SIGNAL";

export type AnomalySeverity = "LOW" | "MEDIUM" | "HIGH";

export interface AnomalySignal {
  signalId: string;
  projectId: string;
  signalType: AnomalySignalType;
  severity: AnomalySeverity;
  expectedReason: string;
  relatedEntityId: string | null;
  plantedForTesting: true; // always true in this dataset — ground truth only
  explanation: string;
}

// Display label mapping, matching the wording already used in the existing
// (pre-integration) UI. Kept here so pages don't hardcode this mapping
// independently.
export const SIGNAL_TYPE_LABELS: Record<AnomalySignalType, string> = {
  COST_ANOMALY: "Cost Anomaly",
  SIMILAR_PROJECT: "Similar Project",
  CONTRACTOR_PATTERN: "Contractor Pattern",
  BILLING_ANOMALY: "Billing Pattern",
  PAYMENT_ANOMALY: "Payment Pattern",
  GEOGRAPHIC_SIGNAL: "Geographic Pattern",
  MULTI_SIGNAL: "Multi-Signal",
};
