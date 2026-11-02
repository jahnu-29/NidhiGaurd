from fastapi import APIRouter, Depends

from backend.app.api.routes import (
    contractors,
    dashboard,
    geography,
    investigation,
    investigation_queue,
    projects,
    risk_results,
)
from backend.app.auth.dependencies import ALL_ROLES, INVESTIGATOR_UP, require_roles

# Stage 6.6 — the permission table, in one place. Every data route requires a
# signed-in, active user (401 otherwise); the role lists below decide who gets
# through (403 otherwise). Role checks run before the route's own work.
#
#   Viewer-visible:        dashboard summary, project list, per-project risk,
#                          bulk risk results           (all three roles)
#   Investigator + Admin:  project detail / relationships / geography
#                          (see projects.py), contractors, geography overview,
#                          investigation queue
#   Administrator only:    /api/users (backend/app/auth/routes.py)
#
#   V2.6 investigation workflow (see investigation.py): GETs for all roles;
#   status / note writes for Investigator + Administrator only (per-route).
api_router = APIRouter()
api_router.include_router(projects.router, dependencies=[Depends(require_roles(*ALL_ROLES))])
api_router.include_router(contractors.router, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
api_router.include_router(investigation_queue.router, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
api_router.include_router(dashboard.router, dependencies=[Depends(require_roles(*ALL_ROLES))])
api_router.include_router(risk_results.router, dependencies=[Depends(require_roles(*ALL_ROLES))])
api_router.include_router(geography.router, dependencies=[Depends(require_roles(*INVESTIGATOR_UP))])
# V2.6 — workflow reads/writes; role checks are declared per route in investigation.py.
api_router.include_router(investigation.router)
