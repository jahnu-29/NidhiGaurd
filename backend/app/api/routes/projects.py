"""
Stage 6.4 — project-facing endpoints.

Every route here either reads the database directly (list/detail) or calls
the existing, unmodified Stage 4/5A intelligence functions (risk,
relationships, geography) via backend/app/api/dependencies.py. No score,
relationship strength, or distance is computed in this file.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    GEOGRAPHIC_DISCLAIMER,
    RELATIONSHIP_DISCLAIMER,
    RISK_DISCLAIMER,
    get_db,
    get_duplicate_like_matches,
    get_geographic_clusters,
    get_geospatial_engine,
    get_project_or_404,
    get_project_relationships,
    get_risk_results,
)
from backend.app.auth.dependencies import INVESTIGATOR_UP, require_roles
from backend.app.api.schemas import (
    BillBrief,
    DuplicateLikeMatch,
    LocationBrief,
    NearbyProject,
    PaymentBrief,
    ProjectDetail,
    ProjectGeographyResponse,
    ProjectRelationshipItem,
    ProjectRelationshipsResponse,
    ProjectRiskResponse,
    ProjectSummary,
    RelationshipEvidence,
)
from backend.app.api.services import contractor_to_summary, project_to_summary
from backend.app.db.models import Project

from intelligence.geographic_intelligence import DEFAULT_RADIUS_KM, GeospatialEngine
from intelligence.risk_engine import ProjectRiskResult

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    projects = db.scalars(select(Project).order_by(Project.project_id)).all()
    return [project_to_summary(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectDetail, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
def get_project(project: Project = Depends(get_project_or_404)) -> ProjectDetail:
    summary = project_to_summary(project)
    return ProjectDetail(
        **summary.model_dump(),
        project_code=project.project_code,
        project_category=project.project_category,
        estimated_cost=project.estimated_cost,
        approved_amount=project.approved_amount,
        actual_expenditure=project.actual_expenditure,
        sanction_date=project.sanction_date,
        work_order_date=project.work_order_date,
        start_date=project.start_date,
        actual_completion_date=project.actual_completion_date,
        completion_percentage=project.completion_percentage,
        contractor=contractor_to_summary(project.contractor),
        location=LocationBrief.model_validate(project.location),
        bills=[BillBrief.model_validate(b) for b in project.bills],
        payments=[PaymentBrief.model_validate(p) for bill in project.bills for p in bill.payments],
    )


@router.get("/{project_id}/risk", response_model=ProjectRiskResponse)
def get_project_risk(
    project: Project = Depends(get_project_or_404),
    risk_results: dict[str, ProjectRiskResult] = Depends(get_risk_results),
) -> ProjectRiskResponse:
    result = risk_results[project.project_id]
    return ProjectRiskResponse(
        project_id=result.project_id,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        recommendation=result.recommendation,
        components=result.components,  # Pydantic validates the existing Stage 4 dict shape directly
        disclaimer=RISK_DISCLAIMER,
    )


@router.get("/{project_id}/relationships", response_model=ProjectRelationshipsResponse, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
def get_project_relationships_route(
    project: Project = Depends(get_project_or_404),
    all_relationships: list[dict] = Depends(get_project_relationships),
) -> ProjectRelationshipsResponse:
    pid = project.project_id
    related = [r for r in all_relationships if r["source"] == pid or r["target"] == pid]
    related.sort(key=lambda r: r["relationship_strength"], reverse=True)

    items = [
        ProjectRelationshipItem(
            related_project_id=r["target"] if r["source"] == pid else r["source"],
            relationship_strength=r["relationship_strength"],
            evidence=RelationshipEvidence(**r["evidence"]),
            explanation=r["explanation"],
        )
        for r in related
    ]
    return ProjectRelationshipsResponse(project_id=pid, relationships=items, disclaimer=RELATIONSHIP_DISCLAIMER)


@router.get("/{project_id}/geography", response_model=ProjectGeographyResponse, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
def get_project_geography(
    project: Project = Depends(get_project_or_404),
    geo: GeospatialEngine = Depends(get_geospatial_engine),
    duplicate_matches: list[dict] = Depends(get_duplicate_like_matches),
    clusters: list[dict] = Depends(get_geographic_clusters),
) -> ProjectGeographyResponse:
    pid = project.project_id

    nearby = [
        NearbyProject(
            project_id=entry["project_id"],
            distance_km=entry["distance_km"],
            same_work_type=entry["same_work_type"],
            same_contractor=entry["same_contractor"],
            relationship_strength=entry["relationship_strength"],
            explanation=entry["explanation"],
        )
        for entry in geo.nearby(pid)
    ]

    cluster_id = next((c["cluster_id"] for c in clusters if pid in c["project_ids"]), None)

    duplicates = [
        DuplicateLikeMatch(
            other_project_id=m["project_b"] if m["project_a"] == pid else m["project_a"],
            distance_km=m["distance_km"],
            description_similarity=m["description_similarity"],
            cost_similarity=m["cost_similarity"],
            shared_attributes=m["shared_attributes"],
            relationship_strength=m["relationship_strength"],
            explanation=m["explanation"],
        )
        for m in duplicate_matches
        if m["project_a"] == pid or m["project_b"] == pid
    ]

    return ProjectGeographyResponse(
        project_id=pid,
        radius_km=DEFAULT_RADIUS_KM,
        nearby_projects=nearby,
        cluster_id=cluster_id,
        duplicate_like_matches=duplicates,
        disclaimer=GEOGRAPHIC_DISCLAIMER,
    )
