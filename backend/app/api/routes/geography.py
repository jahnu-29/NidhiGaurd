"""Stage 6.5 addition — see schemas.GeographyOverviewResponse for why this exists."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import (
    GEOGRAPHIC_DISCLAIMER,
    get_duplicate_like_matches,
    get_geographic_clusters,
    get_geospatial_engine,
)
from backend.app.api.schemas import (
    DatasetDuplicateLikeMatch,
    GeographicClusterItem,
    GeographyOverviewResponse,
    NearbyRelationshipPair,
)

from intelligence.geographic_intelligence import DEFAULT_RADIUS_KM, GeospatialEngine

router = APIRouter(prefix="/api/geography", tags=["geography"])


@router.get("", response_model=GeographyOverviewResponse)
def get_geography_overview(
    geo: GeospatialEngine = Depends(get_geospatial_engine),
    clusters: list[dict] = Depends(get_geographic_clusters),
    duplicate_matches: list[dict] = Depends(get_duplicate_like_matches),
) -> GeographyOverviewResponse:
    nearby = [
        NearbyRelationshipPair(
            source=r["source"],
            target=r["target"],
            distance_km=r["distance_km"],
            same_work_type=r["same_work_type"],
            same_contractor=r["same_contractor"],
            relationship_strength=r["relationship_strength"],
            explanation=r["explanation"],
        )
        for r in geo.all_nearby_relationships()
    ]
    cluster_items = [
        GeographicClusterItem(
            cluster_id=c["cluster_id"],
            project_count=c["project_count"],
            project_ids=c["project_ids"],
            radius_km=c["radius_km"],
            common_work_types=c["common_work_types"],
            shared_contractors=c["shared_contractors"],
        )
        for c in clusters
    ]
    duplicates = [
        DatasetDuplicateLikeMatch(
            project_a=m["project_a"],
            project_b=m["project_b"],
            distance_km=m["distance_km"],
            description_similarity=m["description_similarity"],
            cost_similarity=m["cost_similarity"],
            shared_attributes=m["shared_attributes"],
            relationship_strength=m["relationship_strength"],
            explanation=m["explanation"],
        )
        for m in duplicate_matches
    ]
    return GeographyOverviewResponse(
        radius_km=DEFAULT_RADIUS_KM,
        nearby_relationships=nearby,
        clusters=cluster_items,
        duplicate_like_matches=duplicates,
        disclaimer=GEOGRAPHIC_DISCLAIMER,
    )
