// Stage 6.5 — frontend types for the Stage 6.4 FastAPI response models.
//
// Each interface here mirrors one Pydantic model in
// backend/app/api/schemas.py field-for-field. Where the existing UI expects
// different naming (e.g. camelCase, or a field nested differently), that
// conversion happens explicitly in the page that consumes it — never by
// silently renaming a field here.
//
// Dates are plain ISO strings ("YYYY-MM-DD"), exactly as FastAPI serializes
// them — not Date objects, matching how the legacy generated/*.ts data also
// represented dates.

export interface ContractorBrief {
  contractor_id: string;
  contractor_name: string;
}

export interface LocationBrief {
  location_id: string;
  state: string;
  district: string;
  constituency: string;
  block: string;
  village_or_ward: string;
  latitude: number;
  longitude: number;
  pincode: string;
  location_type: string;
}

export interface BillBrief {
  bill_id: string;
  bill_number: string;
  bill_date: string;
  bill_type: string;
  claimed_amount: number;
  approved_amount: number;
  bill_status: string;
}

export interface PaymentBrief {
  payment_id: string;
  bill_id: string;
  payment_date: string;
  payment_reference: string;
  payment_amount: number;
  payment_mode: string;
  payment_status: string;
}

export interface ProjectSummary {
  project_id: string;
  project_description: string;
  work_type: string;
  district: string;
  state: string;
  project_status: string;
  sanctioned_amount: number;
  expected_completion_date: string;
  contractor_id: string;
  location_id: string;
}

export interface ProjectDetail extends ProjectSummary {
  // Stage 6.5 addition — the rest of the Project record, for
  // ProjectInvestigationPage's full Project Profile card.
  project_code: string;
  project_category: string;
  estimated_cost: number;
  approved_amount: number;
  actual_expenditure: number;
  sanction_date: string;
  work_order_date: string;
  start_date: string;
  actual_completion_date: string | null;
  completion_percentage: number;

  contractor: ContractorSummary;
  location: LocationBrief;
  bills: BillBrief[];
  payments: PaymentBrief[];
}

// --------------------------------------------------------------------- risk --

export interface SimilarityMatch {
  project_id: string;
  combined_score: number;
  text_similarity: number;
  reasons: string[];
}

export interface CostAnomalyComponent {
  score: number;
  max_score: number;
  detected: boolean;
  benchmark_mean: number | null;
  benchmark_median: number | null;
  current_value: number | null;
  percentage_difference: number | null;
  comparable_count: number;
  explanation: string;
}

export interface ProjectSimilarityComponent {
  score: number;
  max_score: number;
  detected: boolean;
  matches: SimilarityMatch[];
  explanation: string;
}

export interface ContractorPatternComponent {
  score: number;
  max_score: number;
  detected: boolean;
  contractor_id: string | null;
  portfolio_size: number | null;
  cluster_size: number | null;
  cost_premium_pct: number | null;
  cluster_project_ids: string[];
  explanation: string;
}

export interface BillingAnomalyComponent {
  score: number;
  max_score: number;
  detected: boolean;
  evidence: string[];
  explanation: string;
}

export interface GeographicSignalComponent {
  score: number;
  max_score: number;
  detected: boolean;
  nearby_project_count: number;
  attribute_sharing_count: number;
  nearby_project_ids: string[];
  explanation: string;
}

export interface RiskComponents {
  cost_anomaly: CostAnomalyComponent;
  project_similarity: ProjectSimilarityComponent;
  contractor_pattern: ContractorPatternComponent;
  billing_anomaly: BillingAnomalyComponent;
  geographic_signal: GeographicSignalComponent;
}

/** GET /api/risk-results list item (Stage 6.5 addition — see backend/app/api/schemas.py). */
export interface RiskResultSummary {
  project_id: string;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  components_detected: number;
  recommendation: string;
}

export interface ProjectRiskResponse {
  project_id: string;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  recommendation: string;
  components: RiskComponents;
  disclaimer: string;
}

// ----------------------------------------------------------- relationships --

export interface RelationshipEvidence {
  same_contractor: boolean;
  same_work_type: boolean;
  same_district: boolean;
  same_state: boolean;
  distance_km: number | null;
  description_similarity: number;
  cost_similarity: number | null;
  date_proximity: number | null;
}

export interface ProjectRelationshipItem {
  related_project_id: string;
  relationship_strength: number;
  evidence: RelationshipEvidence;
  explanation: string;
}

export interface ProjectRelationshipsResponse {
  project_id: string;
  relationships: ProjectRelationshipItem[];
  disclaimer: string;
}

// -------------------------------------------------------------- geography --

export interface NearbyProject {
  project_id: string;
  distance_km: number;
  same_work_type: boolean;
  same_contractor: boolean;
  relationship_strength: number;
  explanation: string;
}

export interface DuplicateLikeMatch {
  other_project_id: string;
  distance_km: number;
  description_similarity: number;
  cost_similarity: number | null;
  shared_attributes: string[];
  relationship_strength: number;
  explanation: string;
}

export interface ProjectGeographyResponse {
  project_id: string;
  radius_km: number;
  nearby_projects: NearbyProject[];
  cluster_id: string | null;
  duplicate_like_matches: DuplicateLikeMatch[];
  disclaimer: string;
}

// ----------------------------------------------- dataset-wide geography --
// GET /api/geography (Stage 6.5 addition — see backend/app/api/schemas.py).

export interface NearbyRelationshipPair {
  source: string;
  target: string;
  distance_km: number;
  same_work_type: boolean;
  same_contractor: boolean;
  relationship_strength: number;
  explanation: string;
}

export interface GeographicClusterItem {
  cluster_id: string;
  project_count: number;
  project_ids: string[];
  radius_km: number;
  common_work_types: string[];
  shared_contractors: string[];
}

export interface DatasetDuplicateLikeMatch {
  project_a: string;
  project_b: string;
  distance_km: number;
  description_similarity: number;
  cost_similarity: number | null;
  shared_attributes: string[];
  relationship_strength: number;
  explanation: string;
}

export interface GeographyOverviewResponse {
  radius_km: number;
  nearby_relationships: NearbyRelationshipPair[];
  clusters: GeographicClusterItem[];
  duplicate_like_matches: DatasetDuplicateLikeMatch[];
  disclaimer: string;
}

// ------------------------------------------------------------- contractors --

export interface ContractorSummary {
  contractor_id: string;
  contractor_name: string;
  contractor_type: string;
  registration_number: string;
  district: string;
  state: string;
  registration_date: string;
  active_status: string;
  total_projects: number;
  total_project_value: number;
}

export interface ContractorDetail extends ContractorSummary {
  projects: ProjectSummary[];
}

// --------------------------------------------------- investigation queue --

export interface InvestigationQueueItem {
  rank: number;
  project_id: string;
  project_description: string;
  work_type: string;
  contractor_id: string;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  components_detected: number;
  recommendation: string;
}

export interface InvestigationQueueResponse {
  total: number;
  items: InvestigationQueueItem[];
  disclaimer: string;
}

// -------------------------------------------------------------- dashboard --

export interface RiskLevelDistribution {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface DashboardSummaryResponse {
  total_projects: number;
  risk_level_distribution: RiskLevelDistribution;
  investigation_queue_size: number;
  disclaimer: string;
}


// ---------------------------------------------------------- Stage 6.6 auth --

export type Role = "Administrator" | "Investigator" | "Viewer";

export interface AuthUser {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export type UserRecord = AuthUser;

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: number;
  user: AuthUser;
}
