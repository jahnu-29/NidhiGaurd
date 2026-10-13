"""
Stage 6.4 API response models.

Every field here is either a real database column (see
backend/app/db/models.py / data-source/docs/DATA_SCHEMA.md) or a real field
already produced by the existing Stage 4/5A intelligence engine (see
intelligence/risk_engine.py's `components` dict, intelligence/relationship_analysis.py's
RelationshipEvidence, and intelligence/geographic_intelligence.py's nearby/cluster/
duplicate-match dicts). Nothing is invented. Where the Stage 6.4 brief named a
field that doesn't exist anywhere upstream (e.g. "recommended_date",
"sanction_amount"), the real underlying name is used instead and the
discrepancy is called out in the Stage 6.4 report rather than fabricated here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContractorBrief(BaseModel):
    contractor_id: str
    contractor_name: str


class LocationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: str
    state: str
    district: str
    constituency: str
    block: str
    village_or_ward: str
    latitude: float
    longitude: float
    pincode: str
    location_type: str


class BillBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bill_id: str
    bill_number: str
    bill_date: date
    bill_type: str
    claimed_amount: float
    approved_amount: float
    bill_status: str


class PaymentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    bill_id: str
    payment_date: date
    payment_reference: str
    payment_amount: float
    payment_mode: str
    payment_status: str


class ProjectSummary(BaseModel):
    """GET /api/projects list item."""

    project_id: str
    project_description: str
    work_type: str
    district: str
    state: str
    project_status: str
    sanctioned_amount: float
    expected_completion_date: date
    contractor_id: str
    location_id: str


class ProjectDetail(ProjectSummary):
    """
    GET /api/projects/{project_id}.

    Stage 6.5 addition: the remaining Project columns not needed by the
    Stage 6.4 list view (project_code, project_category, estimated_cost,
    approved_amount, actual_expenditure, sanction/work-order/start dates,
    actual_completion_date, completion_percentage) are added here, additive
    and non-breaking, so ProjectInvestigationPage's full Project Profile card
    doesn't need a second, differently-shaped request. `contractor` is now
    the full ContractorSummary (was the shorter ContractorBrief) for the same
    reason — also additive, since ContractorBrief's two fields are a subset.
    """

    project_code: str
    project_category: str
    estimated_cost: float
    approved_amount: float
    actual_expenditure: float
    sanction_date: date
    work_order_date: date
    start_date: date
    actual_completion_date: date | None
    completion_percentage: int

    contractor: ContractorSummary
    location: LocationBrief
    bills: list[BillBrief]
    payments: list[PaymentBrief]


# --------------------------------------------------------------------- risk --


class SimilarityMatch(BaseModel):
    project_id: str
    combined_score: float
    text_similarity: float
    reasons: list[str]


class CostAnomalyComponent(BaseModel):
    score: float
    max_score: float
    detected: bool
    benchmark_mean: float | None
    benchmark_median: float | None
    current_value: float | None
    percentage_difference: float | None
    comparable_count: int
    explanation: str


class ProjectSimilarityComponent(BaseModel):
    score: float
    max_score: float
    detected: bool
    matches: list[SimilarityMatch]
    explanation: str


class ContractorPatternComponent(BaseModel):
    score: float
    max_score: float
    detected: bool
    contractor_id: str | None
    portfolio_size: int | None
    cluster_size: int | None
    cost_premium_pct: float | None
    cluster_project_ids: list[str]
    explanation: str


class BillingAnomalyComponent(BaseModel):
    score: float
    max_score: float
    detected: bool
    evidence: list[str]
    explanation: str


class GeographicSignalComponent(BaseModel):
    score: float
    max_score: float
    detected: bool
    nearby_project_count: int
    attribute_sharing_count: int
    nearby_project_ids: list[str]
    explanation: str


class RiskComponents(BaseModel):
    cost_anomaly: CostAnomalyComponent
    project_similarity: ProjectSimilarityComponent
    contractor_pattern: ContractorPatternComponent
    billing_anomaly: BillingAnomalyComponent
    geographic_signal: GeographicSignalComponent


class RiskResultSummary(BaseModel):
    """
    GET /api/risk-results list item — Stage 6.5 addition.

    Stage 6.4 only exposed per-project risk (GET /api/projects/{id}/risk),
    which internally recomputes ALL 200 projects' scores via score_all() and
    returns one. Calling that 200 times to build a full risk register (as
    RiskAnalysisPage needs) would mean recomputing the whole engine 200
    times over. This lightweight bulk list reuses the exact same
    get_risk_results dependency/result set, computed once, so the page
    renders all 200 rows from a single request; the full per-project
    component breakdown is still only ever fetched from the existing
    GET /api/projects/{id}/risk, on demand, when a row is expanded.
    """

    project_id: str
    risk_score: float
    risk_level: str
    components_detected: int
    recommendation: str


class ProjectRiskResponse(BaseModel):
    """GET /api/projects/{project_id}/risk — Stage 4's result, verbatim."""

    project_id: str
    risk_score: float
    risk_level: str
    recommendation: str
    components: RiskComponents
    disclaimer: str


# ----------------------------------------------------------- relationships --


class RelationshipEvidence(BaseModel):
    same_contractor: bool
    same_work_type: bool
    same_district: bool
    same_state: bool
    distance_km: float | None
    description_similarity: float
    cost_similarity: float | None
    date_proximity: float | None


class ProjectRelationshipItem(BaseModel):
    related_project_id: str
    relationship_strength: float
    evidence: RelationshipEvidence
    explanation: str


class ProjectRelationshipsResponse(BaseModel):
    """GET /api/projects/{project_id}/relationships — Stage 5A, verbatim."""

    project_id: str
    relationships: list[ProjectRelationshipItem]
    disclaimer: str


# -------------------------------------------------------------- geography --


class NearbyProject(BaseModel):
    project_id: str
    distance_km: float
    same_work_type: bool
    same_contractor: bool
    relationship_strength: float
    explanation: str


class DuplicateLikeMatch(BaseModel):
    other_project_id: str
    distance_km: float
    description_similarity: float
    cost_similarity: float | None
    shared_attributes: list[str]
    relationship_strength: float
    explanation: str


class ProjectGeographyResponse(BaseModel):
    """GET /api/projects/{project_id}/geography — Stage 5A, verbatim."""

    project_id: str
    radius_km: float
    nearby_projects: list[NearbyProject]
    cluster_id: str | None
    duplicate_like_matches: list[DuplicateLikeMatch]
    disclaimer: str


# ----------------------------------------------- dataset-wide geography --


class NearbyRelationshipPair(BaseModel):
    """One row of GET /api/geography's nearby_relationships — a (source, target)
    pair, each reported once (source < target), same as the legacy
    all_nearby_relationships() the frontend used before Stage 6.5."""

    source: str
    target: str
    distance_km: float
    same_work_type: bool
    same_contractor: bool
    relationship_strength: float
    explanation: str


class GeographicClusterItem(BaseModel):
    cluster_id: str
    project_count: int
    project_ids: list[str]
    radius_km: float
    common_work_types: list[str]
    shared_contractors: list[str]


class DatasetDuplicateLikeMatch(BaseModel):
    project_a: str
    project_b: str
    distance_km: float
    description_similarity: float
    cost_similarity: float | None
    shared_attributes: list[str]
    relationship_strength: float
    explanation: str


class GeographyOverviewResponse(BaseModel):
    """
    GET /api/geography — Stage 6.5 addition (see the module docstring note
    on RiskResultSummary for the same reasoning): Stage 6.4 only exposed
    per-project geography. GeographicPage's overview map and dataset-wide
    tables need every nearby pair / cluster / duplicate-like match at once;
    calling the per-project endpoint 200 times to reassemble that would
    recompute the geospatial engine 200 times over. This reuses the exact
    same get_geospatial_engine / get_geographic_clusters /
    get_duplicate_like_matches dependencies as the per-project route.
    """

    radius_km: float
    nearby_relationships: list[NearbyRelationshipPair]
    clusters: list[GeographicClusterItem]
    duplicate_like_matches: list[DatasetDuplicateLikeMatch]
    disclaimer: str


# ------------------------------------------------------------- contractors --


class ContractorSummary(BaseModel):
    """GET /api/contractors list item, also nested in ProjectDetail (Stage 6.5
    addition: registration_number/registration_date, for
    ProjectInvestigationPage's Contractor card — additive, non-breaking).
    Portfolio size is context, never a risk signal."""

    contractor_id: str
    contractor_name: str
    contractor_type: str
    registration_number: str
    district: str
    state: str
    registration_date: date
    active_status: str
    total_projects: int
    total_project_value: float


class ContractorDetail(ContractorSummary):
    """GET /api/contractors/{contractor_id}"""

    projects: list[ProjectSummary]


# --------------------------------------------------- investigation queue --


class InvestigationQueueItem(BaseModel):
    rank: int
    project_id: str
    project_description: str
    work_type: str
    contractor_id: str
    risk_score: float
    risk_level: str
    components_detected: int
    recommendation: str


class InvestigationQueueResponse(BaseModel):
    """GET /api/investigation-queue — riskLevel != LOW, sorted by score desc (same filter the frontend already used)."""

    total: int
    items: list[InvestigationQueueItem]
    disclaimer: str


# -------------------------------------------------------- dashboard --


class RiskLevelDistribution(BaseModel):
    critical: int
    high: int
    medium: int
    low: int


class DashboardSummaryResponse(BaseModel):
    total_projects: int
    risk_level_distribution: RiskLevelDistribution
    investigation_queue_size: int
    disclaimer: str