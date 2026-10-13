"""
NidhiGuard backend ORM models (Stage 6.1 Project + Stage 6.2 full schema).

Every table and column below is taken from data-source/docs/DATA_SCHEMA.md,
and every foreign key from data-source/docs/RELATIONSHIPS.md ("Referential
integrity rules"). Nothing is invented. Column names keep the CSV's snake_case
so the ingestion layer can map headers to columns 1:1.

This database is NidhiGuard's internal, normalized working layer — it is NOT
the authoritative government record.

Notes on specific design choices:

* projects <-> locations reference each other (projects.location_id and
  locations.project_id, a documented 1:1). Both foreign keys are declared
  DEFERRABLE INITIALLY DEFERRED so the pair can be loaded inside a single
  transaction and is verified at commit time.
* contractors.total_projects / total_project_value are documented as
  "derived" fields in the source CSV. They are stored exactly as supplied and
  are not recomputed here.
* bills.contractor_id and payments.project_id / contractor_id are documented
  denormalized copies; they are real foreign keys, stored as supplied.
* historical_projects is documented as "not linked into the live bills /
  payments graph" — its only FK is contractor_id (documented "FK, may reuse
  contractors.csv IDs").
"""

from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.database import Base


def _fk(target: str, **kwargs) -> ForeignKey:
    """Foreign key, deferred to commit time (needed for the projects<->locations pair)."""
    return ForeignKey(target, deferrable=True, initially="DEFERRED", **kwargs)


class Contractor(Base):
    __tablename__ = "contractors"

    contractor_id: Mapped[str] = mapped_column(String, primary_key=True)
    contractor_name: Mapped[str] = mapped_column(String, nullable=False)
    registration_number: Mapped[str] = mapped_column(String, nullable=False)
    contractor_type: Mapped[str] = mapped_column(String, nullable=False)
    district: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    registration_date: Mapped[date] = mapped_column(Date, nullable=False)
    active_status: Mapped[str] = mapped_column(String, nullable=False)
    total_projects: Mapped[int] = mapped_column(Integer, nullable=False)
    total_project_value: Mapped[float] = mapped_column(Float, nullable=False)
    contact_reference: Mapped[str] = mapped_column(String, nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="contractor")


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, _fk("projects.project_id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    district: Mapped[str] = mapped_column(String, nullable=False)
    constituency: Mapped[str] = mapped_column(String, nullable=False)
    block: Mapped[str] = mapped_column(String, nullable=False)
    village_or_ward: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    pincode: Mapped[str] = mapped_column(String, nullable=False)  # string, never an int (leading zeros)
    location_type: Mapped[str] = mapped_column(String, nullable=False)

    # The owning project, via locations.project_id.
    project: Mapped["Project"] = relationship(foreign_keys=[project_id], back_populates="location_of_record")


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_code: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    project_description: Mapped[str] = mapped_column(Text, nullable=False)
    project_category: Mapped[str] = mapped_column(String, nullable=False)
    work_type: Mapped[str] = mapped_column(String, nullable=False)

    mp_id: Mapped[str] = mapped_column(String, nullable=False)
    constituency_id: Mapped[str] = mapped_column(String, nullable=False)
    district_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    implementing_agency_id: Mapped[str] = mapped_column(String, nullable=False)
    contractor_id: Mapped[str] = mapped_column(String, _fk("contractors.contractor_id"), nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String, _fk("locations.location_id"), nullable=False, index=True)

    sanctioned_amount: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False)
    approved_amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_expenditure: Mapped[float] = mapped_column(Float, nullable=False)

    project_status: Mapped[str] = mapped_column(String, nullable=False)

    sanction_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_order_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_completion_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_percentage: Mapped[int] = mapped_column(Integer, nullable=False)
    created_date: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        # Comparable-group lookups used by the intelligence layer's join keys
        # (RELATIONSHIPS.md: work_type + state/district).
        Index("ix_projects_work_type_state", "work_type", "state"),
    )

    contractor: Mapped[Contractor] = relationship(back_populates="projects")
    # The location this project points at, via projects.location_id.
    location: Mapped[Location] = relationship(foreign_keys=[location_id])
    # Reverse side of locations.project_id (documented 1:1 in this MVP).
    location_of_record: Mapped[list[Location]] = relationship(
        foreign_keys="Location.project_id", back_populates="project"
    )
    project_contractors: Mapped[list["ProjectContractor"]] = relationship(back_populates="project")
    bills: Mapped[list["Bill"]] = relationship(back_populates="project")
    anomaly_signals: Mapped[list["AnomalySignal"]] = relationship(back_populates="project")

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience only
        return f"<Project {self.project_id} status={self.project_status!r}>"


class ProjectContractor(Base):
    __tablename__ = "project_contractors"

    relationship_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, _fk("projects.project_id"), nullable=False, index=True)
    contractor_id: Mapped[str] = mapped_column(String, _fk("contractors.contractor_id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    contract_value: Mapped[float] = mapped_column(Float, nullable=False)
    award_date: Mapped[date] = mapped_column(Date, nullable=False)

    project: Mapped[Project] = relationship(back_populates="project_contractors")
    contractor: Mapped[Contractor] = relationship()


class Bill(Base):
    __tablename__ = "bills"

    bill_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, _fk("projects.project_id"), nullable=False, index=True)
    contractor_id: Mapped[str] = mapped_column(String, _fk("contractors.contractor_id"), nullable=False, index=True)
    bill_number: Mapped[str] = mapped_column(String, nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    bill_type: Mapped[str] = mapped_column(String, nullable=False)
    claimed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    approved_amount: Mapped[float] = mapped_column(Float, nullable=False)
    bill_status: Mapped[str] = mapped_column(String, nullable=False)
    work_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    work_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    submission_date: Mapped[date] = mapped_column(Date, nullable=False)
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # blank if not yet approved

    project: Mapped[Project] = relationship(back_populates="bills")
    contractor: Mapped[Contractor] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="bill")


class Payment(Base):
    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String, primary_key=True)
    bill_id: Mapped[str] = mapped_column(String, _fk("bills.bill_id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, _fk("projects.project_id"), nullable=False, index=True)
    contractor_id: Mapped[str] = mapped_column(String, _fk("contractors.contractor_id"), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_reference: Mapped[str] = mapped_column(String, nullable=False)
    payment_amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_mode: Mapped[str] = mapped_column(String, nullable=False)
    payment_status: Mapped[str] = mapped_column(String, nullable=False)
    approving_authority: Mapped[str] = mapped_column(String, nullable=False)

    bill: Mapped[Bill] = relationship(back_populates="payments")
    project: Mapped[Project] = relationship()
    contractor: Mapped[Contractor] = relationship()


class HistoricalProject(Base):
    __tablename__ = "historical_projects"

    historical_project_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_description: Mapped[str] = mapped_column(Text, nullable=False)
    project_category: Mapped[str] = mapped_column(String, nullable=False)
    work_type: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    district: Mapped[str] = mapped_column(String, nullable=False)
    constituency: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    sanctioned_amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_expenditure: Mapped[float] = mapped_column(Float, nullable=False)
    completion_date: Mapped[date] = mapped_column(Date, nullable=False)
    contractor_id: Mapped[str] = mapped_column(String, _fk("contractors.contractor_id"), nullable=False, index=True)
    implementing_agency_id: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        # Comparable-group lookups (RELATIONSHIPS.md: work_type + state/district).
        Index("ix_historical_projects_work_type_state", "work_type", "state"),
    )

    contractor: Mapped[Contractor] = relationship()


class AnomalySignal(Base):
    """
    Ground-truth planted signals — validation-only data. It is stored so the
    dataset is complete, but must never be used as an input to any scoring or
    relationship calculation (same rule as in Stages 4/5A).
    """

    __tablename__ = "anomaly_signals"

    signal_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, _fk("projects.project_id"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    expected_reason: Mapped[str] = mapped_column(String, nullable=False)
    related_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)  # blank in 1 source row
    planted_for_testing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[Project] = relationship(back_populates="anomaly_signals")