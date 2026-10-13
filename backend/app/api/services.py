"""
Stage 6.4 — small shared helpers used by more than one route module.

Kept deliberately thin: this is conversion between ORM objects and API
schemas, not business/intelligence logic (that stays in intelligence/ and is
only ever called, never reimplemented, from backend/app/api/dependencies.py).
"""

from __future__ import annotations

from backend.app.api.schemas import ContractorSummary, ProjectSummary
from backend.app.db.models import Contractor, Project


def project_to_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        project_description=project.project_description,
        work_type=project.work_type,
        district=project.location.district,
        state=project.state,
        project_status=project.project_status,
        sanctioned_amount=project.sanctioned_amount,
        expected_completion_date=project.expected_completion_date,
        contractor_id=project.contractor_id,
        location_id=project.location_id,
    )


def contractor_to_summary(c: Contractor) -> ContractorSummary:
    return ContractorSummary(
        contractor_id=c.contractor_id,
        contractor_name=c.contractor_name,
        contractor_type=c.contractor_type,
        registration_number=c.registration_number,
        district=c.district,
        state=c.state,
        registration_date=c.registration_date,
        active_status=c.active_status,
        total_projects=c.total_projects,
        total_project_value=c.total_project_value,
    )
