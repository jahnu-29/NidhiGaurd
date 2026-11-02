import { useState, type ReactNode, type CSSProperties } from "react";
import {
  getProjectById,
  getSignalsByProject,
  getHistoricalComparables,
  getRelatedProjects,
} from "@/data/access";
import { SIGNAL_TYPE_LABELS, type AnomalySeverity } from "@/data/types";
import { getContractorNetwork, getMultiHopPathsForProject } from "@/data/contractorNetwork";
import {
  getProject, getProjectRisk, getProjectRelationships, getProjectGeography,
  getContractor, getRiskResults,
} from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import InvestigationWorkflow, { StatusBadge } from "@/components/InvestigationWorkflow";
import { useAuth } from "@/auth/AuthContext";
import { canInvestigate } from "@/auth/permissions";
import type {
  ProjectDetail, ProjectRiskResponse, ProjectRelationshipsResponse,
  ProjectGeographyResponse, ContractorDetail, RiskResultSummary, RiskComponents, InvestigationStatus,
} from "@/api/types";

// Stage 6.5 note: this page is the central investigator-facing screen. Core
// project/contractor/location/bill/payment data (GET /api/projects/{id}),
// Stage 4's risk result (GET /api/projects/{id}/risk), Stage 5A's
// relationship intelligence (GET /api/projects/{id}/relationships), and
// Stage 5A's geographic intelligence (GET /api/projects/{id}/geography) all
// now come from the FastAPI backend — nothing is computed here.
//
// Four sections have no Stage 6.4/6.5 endpoint yet and still read the
// legacy Stage 1 local adapter (same seed data, just not over HTTP):
// Historical Comparables, Planted Signals, Related Projects (attribute
// match), and Contractor Network/Multi-Hop Context. See the Stage 6.5
// report for why each was left as-is rather than adding yet another
// bespoke endpoint.

interface Props {
  projectId: string;
  onBack: () => void;
}

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(2)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(2)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

function pct(v: number | null): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

const RISK_DISCLAIMER = "Risk score indicates anomaly signals and does not constitute a finding of fraud.";

const STATUS_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  Completed: { bg: "#f0fdf4", fg: "#15803d", border: "#bbf7d0" },
  "In Progress": { bg: "#eff6ff", fg: "#1d4ed8", border: "#bfdbfe" },
  Delayed: { bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca" },
};

const SEVERITY_COLORS: Record<AnomalySeverity, { bg: string; fg: string; border: string }> = {
  HIGH: { bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca" },
  MEDIUM: { bg: "#fffbeb", fg: "#b45309", border: "#fde68a" },
  LOW: { bg: "#eff6ff", fg: "#1d4ed8", border: "#bfdbfe" },
};

const BILL_STATUS_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  Approved: { bg: "#f0fdf4", fg: "#15803d", border: "#bbf7d0" },
  Pending: { bg: "#fffbeb", fg: "#b45309", border: "#fde68a" },
  Rejected: { bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca" },
};

type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

const LEVEL_COLOR: Record<RiskLevel, string> = {
  CRITICAL: "#7f1d1d",
  HIGH: "#dc2626",
  MEDIUM: "#d97706",
  LOW: "#16a34a",
};

const LEVEL_BADGE_STYLE: Record<RiskLevel, { background: string; color: string; border: string }> = {
  CRITICAL: { background: "#fee2e2", color: "#7f1d1d", border: "1px solid #fecaca" },
  HIGH: { background: "#fef2f2", color: "#b91c1c", border: "1px solid #fecaca" },
  MEDIUM: { background: "#fffbeb", color: "#b45309", border: "1px solid #fde68a" },
  LOW: { background: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0" },
};

const COMPONENT_LABELS: { key: keyof RiskComponents; label: string }[] = [
  { key: "cost_anomaly", label: "Cost Anomaly" },
  { key: "project_similarity", label: "Project Similarity" },
  { key: "contractor_pattern", label: "Contractor Pattern" },
  { key: "billing_anomaly", label: "Billing Anomaly" },
  { key: "geographic_signal", label: "Geographic Signal" },
];

function detectedCount(components: RiskComponents): number {
  return COMPONENT_LABELS.reduce((n, { key }) => n + (components[key].detected ? 1 : 0), 0);
}

function SectionLabel({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <div
      title={title}
      style={{
        fontSize: "0.68rem",
        fontWeight: 700,
        color: "#1c3557",
        letterSpacing: "0.07em",
        textTransform: "uppercase",
        marginBottom: "0.75rem",
        borderBottom: "1px solid #eef0f3",
        paddingBottom: "0.5rem",
      }}
    >
      {children}
    </div>
  );
}

function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", ...style }}>
      {children}
    </div>
  );
}

function StatBadge(label: string, value: string, mono = true) {
  return (
    <tr key={label} style={{ borderBottom: "1px solid #f3f4f6" }}>
      <td style={{ padding: "0.3rem 0", fontSize: "0.68rem", color: "#6b7280", fontWeight: 500, verticalAlign: "top", paddingRight: "0.75rem", whiteSpace: "nowrap" }}>{label}</td>
      <td style={{ padding: "0.3rem 0", fontSize: "0.78rem", color: "#1f2937", fontFamily: mono ? "'JetBrains Mono', monospace" : "inherit", fontWeight: 500 }}>{value}</td>
    </tr>
  );
}

function EvidenceChip({ children }: { children: ReactNode }) {
  return (
    <span style={{ fontSize: "0.62rem", fontWeight: 600, color: "#374151", background: "#f4f6fa", border: "1px solid #dde1e7", padding: "1px 7px", borderRadius: 2, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

export default function ProjectInvestigationPage({ projectId, onBack }: Props) {
  const projectQ = useApiData<ProjectDetail>(() => getProject(projectId), [projectId]);
  const riskQ = useApiData<ProjectRiskResponse>(() => getProjectRisk(projectId), [projectId]);
  const relationshipsQ = useApiData<ProjectRelationshipsResponse>(() => getProjectRelationships(projectId), [projectId]);
  const geographyQ = useApiData<ProjectGeographyResponse>(() => getProjectGeography(projectId), [projectId]);
  const riskResultsQ = useApiData<RiskResultSummary[]>(getRiskResults, []);
  // V2.6 — workflow status is fetched by <InvestigationWorkflow/>; it reports it here so the header can mirror it.
  const [workflowStatus, setWorkflowStatus] = useState<InvestigationStatus | null>(null);
  const { user } = useAuth();
  const canWrite = !!user && canInvestigate(user.role);

  const contractorId = projectQ.data?.contractor_id ?? null;
  const contractorQ = useApiData<ContractorDetail | null>(
    () => (contractorId ? getContractor(contractorId) : Promise.resolve(null)),
    [contractorId]
  );

  const loading = projectQ.loading || riskQ.loading || relationshipsQ.loading || geographyQ.loading || riskResultsQ.loading;
  const error = projectQ.error || riskQ.error || relationshipsQ.error || geographyQ.error || riskResultsQ.error;

  if (error) {
    return (
      <div>
        <button onClick={onBack} style={{ background: "none", border: "none", color: "#1c3557", cursor: "pointer", fontFamily: "inherit", fontWeight: 600, fontSize: "0.7rem", padding: 0, marginBottom: "1rem" }}>
          ← Projects
        </button>
        <ErrorBlock message={error} />
      </div>
    );
  }

  if (loading || !projectQ.data || !riskQ.data || !relationshipsQ.data || !geographyQ.data || !riskResultsQ.data) {
    return <LoadingBlock label="Loading project investigation…" />;
  }

  const project = projectQ.data;
  const risk = riskQ.data;
  const relationships = relationshipsQ.data.relationships;
  const geography = geographyQ.data;
  const riskByProjectId = new Map(riskResultsQ.data.map((r) => [r.project_id, r]));

  // Legacy Stage 1 local adapter — see file header for why these four
  // sections aren't backend-fetched yet. Same seed data either way.
  const legacyProject = getProjectById(project.project_id);
  const signals = getSignalsByProject(project.project_id);
  const relatedProjects = getRelatedProjects(project.project_id);
  const historicalComparables = legacyProject ? getHistoricalComparables(legacyProject) : [];
  const contractorNetwork = getContractorNetwork(project.contractor_id);
  const multiHopPaths = getMultiHopPathsForProject(project.project_id);

  const contractorOtherProjects = (contractorQ.data?.projects ?? []).filter((p) => p.project_id !== project.project_id);

  const comparableAvgExpenditure =
    historicalComparables.length > 0
      ? historicalComparables.reduce((sum, h) => sum + h.actualExpenditure, 0) / historicalComparables.length
      : null;

  const statusColor = STATUS_COLORS[project.project_status] ?? { bg: "#f9fafb", fg: "#374151", border: "#e5e7eb" };

  return (
    <div>
      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.7rem", color: "#6b7280", marginBottom: "1rem" }}>
        <button onClick={onBack} style={{ background: "none", border: "none", color: "#1c3557", cursor: "pointer", fontFamily: "inherit", fontWeight: 600, fontSize: "0.7rem", padding: 0 }}>← Projects</button>
        <span>/</span>
        <span>Project Investigation</span>
        <span>/</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{project.project_id}</span>
      </div>

      {/* Header */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "1.5rem", marginBottom: "1.25rem", alignItems: "start" }}>
        <div>
          <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.25rem" }}>
            Project Investigation — {project.project_id}
          </div>
          <h1 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>{project.project_description}</h1>
          <div style={{ display: "flex", gap: "1rem", marginTop: "0.4rem", fontSize: "0.75rem", color: "#6b7280", flexWrap: "wrap" }}>
            <span>Work Type: <strong style={{ color: "#374151" }}>{project.work_type}</strong></span>
            <span>Constituency: <strong style={{ color: "#374151" }}>{project.location.constituency}</strong></span>
            <span>District: <strong style={{ color: "#374151" }}>{project.location.district}</strong></span>
            <span>State: <strong style={{ color: "#374151" }}>{project.state}</strong></span>
            <span>Contractor: <strong style={{ color: "#374151" }}>{project.contractor.contractor_name}</strong></span>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <span style={{
            fontSize: "0.68rem", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase",
            padding: "4px 12px", borderRadius: 2, display: "inline-block",
            background: statusColor.bg, color: statusColor.fg, border: `1px solid ${statusColor.border}`,
          }}>{project.project_status}</span>
          <div style={{ marginTop: "0.5rem" }}>
            <span style={{ ...LEVEL_BADGE_STYLE[risk.risk_level], fontSize: "0.68rem", fontWeight: 700, padding: "3px 10px", borderRadius: 2 }}>
              {risk.risk_level} · {risk.risk_score.toFixed(1)}/100
            </span>
          </div>
          {workflowStatus && (
            <div style={{ marginTop: "0.4rem", fontSize: "0.62rem", color: "#6b7280" }}>
              Investigation status: <StatusBadge status={workflowStatus} />
            </div>
          )}
        </div>
      </div>

      {/* SECTION 2 — Risk Assessment (Stage 4, verbatim via API) */}
      <Card style={{ marginBottom: "1.25rem", borderTop: `3px solid ${LEVEL_COLOR[risk.risk_level]}` }}>
        <SectionLabel>Risk Assessment — Stage 4 Explainable Risk Engine</SectionLabel>
        <div style={{ display: "grid", gridTemplateColumns: "auto auto 1fr auto", gap: "1.75rem", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em" }}>Risk Score</div>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: LEVEL_COLOR[risk.risk_level], fontFamily: "'JetBrains Mono', monospace" }}>{risk.risk_score.toFixed(1)}<span style={{ fontSize: "0.8rem", color: "#9ca3af" }}>/100</span></div>
          </div>
          <div>
            <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em" }}>Risk Level</div>
            <span style={{ ...LEVEL_BADGE_STYLE[risk.risk_level], fontSize: "0.75rem", fontWeight: 700, padding: "3px 10px", borderRadius: 2, display: "inline-block", marginTop: "0.2rem" }}>{risk.risk_level}</span>
          </div>
          <div>
            <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em" }}>Recommendation</div>
            <div style={{ fontSize: "0.85rem", color: "#1f2937", fontWeight: 600, marginTop: "0.15rem" }}>{risk.recommendation}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em" }}>Components Detected</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: "#1c3557", fontFamily: "'JetBrains Mono', monospace" }}>{detectedCount(risk.components)} / 5</div>
          </div>
        </div>
        <div style={{ background: "#f8faff", border: "1px solid #dde8f5", borderRadius: 3, padding: "0.6rem 0.85rem", fontSize: "0.68rem", color: "#4b6c8e", marginTop: "0.85rem" }}>
          <strong>{risk.disclaimer || RISK_DISCLAIMER}</strong> Final determination remains with the authorized investigator.
        </div>
      </Card>

      {/* SECTION 3 — Why was this project flagged? */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel title="The five independent Stage 4 detectors and their scores for this project">Why Was This Project Flagged?</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {COMPONENT_LABELS.map(({ key, label }) => {
            const c = risk.components[key];
            return (
              <div key={key} style={{ border: "1px solid #eef0f3", borderRadius: 3, padding: "0.6rem 0.8rem", background: c.detected ? "#fffdf7" : "#fafbfc" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.3rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "#1c3557" }}>{label}</span>
                    {c.detected ? (
                      <span style={{ fontSize: "0.6rem", fontWeight: 700, color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", padding: "1px 7px", borderRadius: 2 }}>Anomaly Detected</span>
                    ) : (
                      <span style={{ fontSize: "0.6rem", fontWeight: 600, color: "#6b7280", background: "#f4f6fa", border: "1px solid #e5e7eb", padding: "1px 7px", borderRadius: 2 }}>Not Detected</span>
                    )}
                  </div>
                  <span style={{ fontSize: "0.78rem", fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: "#1f2937" }}>{c.score.toFixed(1)} / {c.max_score}</span>
                </div>
                <div style={{ height: 5, background: "#eef0f3", borderRadius: 3, overflow: "hidden", marginBottom: "0.4rem" }}>
                  <div style={{ height: "100%", width: `${(c.score / c.max_score) * 100}%`, background: c.detected ? "#d97706" : "#c7cdd6" }} />
                </div>
                <div style={{ fontSize: "0.74rem", color: "#374151" }}>{c.explanation}</div>
              </div>
            );
          })}
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {/* Project profile */}
        <Card>
          <SectionLabel>Project Profile</SectionLabel>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {[
                StatBadge("Project ID", project.project_id),
                StatBadge("Project Code", project.project_code),
                StatBadge("Category", project.project_category, false),
                StatBadge("Work Type", project.work_type, false),
                StatBadge("Sanctioned", formatINR(project.sanctioned_amount)),
                StatBadge("Estimated Cost", formatINR(project.estimated_cost)),
                StatBadge("Approved", formatINR(project.approved_amount)),
                StatBadge("Actual Expenditure", formatINR(project.actual_expenditure)),
                StatBadge("Sanction Date", project.sanction_date),
                StatBadge("Start Date", project.start_date),
                StatBadge("Expected Completion", project.expected_completion_date),
                StatBadge("Actual Completion", project.actual_completion_date ?? "—"),
                StatBadge("Completion %", `${project.completion_percentage}%`),
              ]}
            </tbody>
          </table>
        </Card>

        {/* Contractor profile */}
        <Card>
          <SectionLabel>Contractor</SectionLabel>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {[
                StatBadge("Contractor ID", project.contractor.contractor_id),
                StatBadge("Name", project.contractor.contractor_name, false),
                StatBadge("Type", project.contractor.contractor_type, false),
                StatBadge("Registration No.", project.contractor.registration_number),
                StatBadge("District / State", `${project.contractor.district}, ${project.contractor.state}`, false),
                StatBadge("Registered", project.contractor.registration_date),
                StatBadge("Status", project.contractor.active_status, false),
                StatBadge("Total Projects (dataset)", String(project.contractor.total_projects)),
                StatBadge("Projects Linked Here", String((contractorQ.data?.projects ?? []).length || "…")),
                StatBadge("Total Project Value", formatINR(project.contractor.total_project_value)),
              ]}
            </tbody>
          </table>
        </Card>

        {/* Location */}
        <Card>
          <SectionLabel>Location</SectionLabel>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {[
                StatBadge("Location ID", project.location.location_id),
                StatBadge("Type", project.location.location_type, false),
                StatBadge("State", project.location.state, false),
                StatBadge("District", project.location.district, false),
                StatBadge("Constituency", project.location.constituency, false),
                StatBadge("Block", project.location.block, false),
                StatBadge("Village / Ward", project.location.village_or_ward, false),
                StatBadge("Pincode", project.location.pincode),
                StatBadge("Latitude", `${project.location.latitude}°N`),
                StatBadge("Longitude", `${project.location.longitude}°E`),
              ]}
            </tbody>
          </table>
        </Card>
      </div>

      {/* SECTION 5 — Contractor context: other projects linked to this contractor,
          each shown with its OWN separate Stage 4 risk — never aggregated into
          a contractor-level score, and portfolio size is never itself a signal. */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel title="Descriptive context only — portfolio size is never treated as suspicious">
          Contractor Context — Other Projects Linked to {project.contractor.contractor_name} ({contractorOtherProjects.length})
        </SectionLabel>
        <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
          Contractor {project.contractor.contractor_id} is associated with {project.contractor.total_projects} project(s) in the dataset. This is descriptive information, not a fraud conclusion — each linked project's risk result is shown separately below and never combined into a contractor score.
        </div>
        {contractorQ.loading ? (
          <LoadingBlock label="Loading contractor portfolio…" />
        ) : contractorQ.error ? (
          <ErrorBlock message={contractorQ.error} />
        ) : contractorOtherProjects.length === 0 ? (
          <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No other projects are linked to this contractor in the current dataset.</div>
        ) : (
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Project ID</th>
                <th>Description</th>
                <th>Work Type</th>
                <th>State</th>
                <th>This Project's Risk (Stage 4)</th>
              </tr>
            </thead>
            <tbody>
              {contractorOtherProjects.map((p) => {
                const r = riskByProjectId.get(p.project_id);
                return (
                  <tr key={p.project_id}>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{p.project_id}</td>
                    <td style={{ maxWidth: 220 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.project_description}>{p.project_description}</span></td>
                    <td style={{ fontSize: "0.72rem" }}>{p.work_type}</td>
                    <td style={{ fontSize: "0.72rem" }}>{p.state}</td>
                    <td>
                      {r ? (
                        <span style={{ ...LEVEL_BADGE_STYLE[r.risk_level], fontSize: "0.62rem", fontWeight: 700, padding: "2px 7px", borderRadius: 2 }}>{r.risk_level} · {r.risk_score.toFixed(1)}</span>
                      ) : (
                        <span style={{ fontSize: "0.68rem", color: "#9ca3af" }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {/* Bills */}
        <Card>
          <SectionLabel>Bills ({project.bills.length})</SectionLabel>
          {project.bills.length === 0 ? (
            <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No bills recorded for this project.</div>
          ) : (
            <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th>Bill No.</th>
                  <th>Type</th>
                  <th>Bill Date</th>
                  <th>Claimed</th>
                  <th>Approved</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {project.bills.map((b) => {
                  const c = BILL_STATUS_COLORS[b.bill_status] ?? { bg: "#f9fafb", fg: "#374151", border: "#e5e7eb" };
                  return (
                    <tr key={b.bill_id}>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{b.bill_number}</td>
                      <td style={{ fontSize: "0.72rem" }}>{b.bill_type}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{b.bill_date}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{formatINR(b.claimed_amount)}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{formatINR(b.approved_amount)}</td>
                      <td><span style={{ fontSize: "0.62rem", fontWeight: 600, color: c.fg, background: c.bg, border: `1px solid ${c.border}`, padding: "1px 6px", borderRadius: 2 }}>{b.bill_status}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>

        {/* Payments — already grouped per bill by the API, never matched by amount/name */}
        <Card>
          <SectionLabel>Payments</SectionLabel>
          {project.payments.length === 0 ? (
            <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No payments recorded for this project.</div>
          ) : (
            <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th>Bill No.</th>
                  <th>Payment Ref.</th>
                  <th>Date</th>
                  <th>Amount</th>
                  <th>Mode</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {project.payments.map((p) => {
                  const bill = project.bills.find((b) => b.bill_id === p.bill_id);
                  return (
                    <tr key={p.payment_id}>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{bill?.bill_number ?? p.bill_id}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{p.payment_reference}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{p.payment_date}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{formatINR(p.payment_amount)}</td>
                      <td style={{ fontSize: "0.72rem" }}>{p.payment_mode}</td>
                      <td>
                        <span style={{
                          fontSize: "0.62rem", fontWeight: 600, padding: "1px 6px", borderRadius: 2,
                          color: p.payment_status === "Success" ? "#15803d" : "#b45309",
                          background: p.payment_status === "Success" ? "#f0fdf4" : "#fffbeb",
                          border: `1px solid ${p.payment_status === "Success" ? "#bbf7d0" : "#fde68a"}`,
                        }}>{p.payment_status}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {/* Historical comparables — legacy local adapter, no Stage 6.4 endpoint yet */}
        <Card>
          <SectionLabel title="No Stage 6.4 endpoint exposes historical_projects yet — read from the legacy local adapter (same seed data)">Historical Comparables ({historicalComparables.length})</SectionLabel>
          <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
            Completed projects of the same work type ({project.work_type}) in {project.state} — the same comparable group Stage 4's cost-anomaly detector benchmarks against (median expenditure, requires ≥5 comparables). No cost-anomaly score is recalculated on this page; see the Cost Anomaly row above for Stage 4's own result.
          </div>
          {historicalComparables.length === 0 ? (
            <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No historical comparables found for this work type and state.</div>
          ) : (
            <>
              {comparableAvgExpenditure !== null && (
                <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.78rem", fontFamily: "'JetBrains Mono', monospace", marginBottom: "0.6rem" }}>
                  <div>
                    <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em", fontFamily: "inherit" }}>This Project — Actual Expenditure</div>
                    <div style={{ color: "#1c3557", fontWeight: 600 }}>{formatINR(project.actual_expenditure)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em", fontFamily: "inherit" }}>Comparable Avg. Expenditure</div>
                    <div style={{ color: "#374151", fontWeight: 600 }}>{formatINR(comparableAvgExpenditure)}</div>
                  </div>
                </div>
              )}
              <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th>Historical ID</th>
                    <th>Description</th>
                    <th>District</th>
                    <th>Expenditure</th>
                    <th>Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {historicalComparables.slice(0, 6).map((h) => (
                    <tr key={h.historicalProjectId}>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{h.historicalProjectId}</td>
                      <td style={{ maxWidth: 160 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={h.projectDescription}>{h.projectDescription}</span></td>
                      <td style={{ fontSize: "0.72rem" }}>{h.district}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{formatINR(h.actualExpenditure)}</td>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{h.completionDate}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {historicalComparables.length > 6 && (
                <div style={{ fontSize: "0.65rem", color: "#9ca3af", marginTop: "0.4rem" }}>+{historicalComparables.length - 6} more comparable projects not shown.</div>
              )}
            </>
          )}
        </Card>

        {/* Planted signals — legacy local adapter, no Stage 6.4 endpoint yet */}
        <Card>
          <SectionLabel title="Ground-truth signals planted in the synthetic demonstration dataset — not output from an intelligence engine, and no Stage 6.4 endpoint exposes anomaly_signals yet">Planted Signals ({signals.length})</SectionLabel>
          <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
            These are synthetic scenario signals planted directly in the demonstration dataset. They are ground truth for testing, not the output of any detection logic, and are not a fraud finding.
          </div>
          {signals.length === 0 ? (
            <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No planted signals for this project.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {signals.map((s) => {
                const c = SEVERITY_COLORS[s.severity];
                return (
                  <div key={s.signalId} style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: 3, padding: "0.6rem 0.75rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: "0.75rem" }}>
                      <div>
                        <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.04em", textTransform: "uppercase" }}>
                          {SIGNAL_TYPE_LABELS[s.signalType]}
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "#374151", marginTop: "0.15rem" }}>{s.explanation}</div>
                        {s.relatedEntityId && (
                          <div style={{ fontSize: "0.65rem", color: "#6b7280", marginTop: "0.2rem", fontFamily: "'JetBrains Mono', monospace" }}>
                            Related entity: {s.relatedEntityId}
                          </div>
                        )}
                      </div>
                      <span style={{ fontSize: "0.62rem", fontWeight: 700, color: c.fg, background: "#fff", border: `1px solid ${c.border}`, padding: "2px 8px", borderRadius: 2, whiteSpace: "nowrap" }}>{s.severity}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* SECTION 7 — Relationship Intelligence (Stage 5A, via API) */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel>Relationship Intelligence — Strongest Related Projects ({relationships.length})</SectionLabel>
        <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
          {relationshipsQ.data.disclaimer}
        </div>
        {relationships.length === 0 ? (
          <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No analytical relationships were computed for this project by Stage 5A.</div>
        ) : (
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Related Project</th>
                <th>Relationship Strength</th>
                <th>Evidence</th>
                <th>Explanation</th>
              </tr>
            </thead>
            <tbody>
              {relationships.map((r) => {
                const chips: string[] = [];
                if (r.evidence.same_contractor) chips.push("Same Contractor");
                if (r.evidence.same_work_type) chips.push("Same Work Type");
                if (r.evidence.same_district) chips.push("Same District");
                else if (r.evidence.same_state) chips.push("Same State");
                if (r.evidence.distance_km !== null) chips.push(`${r.evidence.distance_km.toFixed(2)} km apart`);
                if (r.evidence.description_similarity !== null) chips.push(`Description ${pct(r.evidence.description_similarity)} similar`);
                if (r.evidence.cost_similarity !== null) chips.push(`Cost ${pct(r.evidence.cost_similarity)} similar`);
                return (
                  <tr key={r.related_project_id}>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600, color: "#1c3557" }}>{r.related_project_id}</td>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{r.relationship_strength.toFixed(1)}</td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                        {chips.map((chip) => <EvidenceChip key={chip}>{chip}</EvidenceChip>)}
                      </div>
                    </td>
                    <td style={{ fontSize: "0.7rem", color: "#374151", maxWidth: 280 }}>{r.explanation}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      {/* SECTION 8 — Contractor network / multi-hop context — legacy local adapter, no Stage 6.4 endpoint yet */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel title="PROJECT -> CONTRACTOR -> PROJECT[ -> LOCATION] chains from Stage 5A. No Stage 6.4 endpoint exposes this yet — read from the legacy local adapter.">Contractor Network &amp; Multi-Hop Context ({multiHopPaths.length})</SectionLabel>
        <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
          Relationship chains connecting this project to others through a shared contractor (and location, where applicable). These are direct/derived Stage 5A relationships joined together for readability — no new relationship is calculated here.
        </div>
        {contractorNetwork && (
          <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.72rem", color: "#374151", marginBottom: "0.75rem", flexWrap: "wrap" }}>
            <span>Contractor network spans <strong>{contractorNetwork.workTypes.length}</strong> work type(s), <strong>{contractorNetwork.districts.length}</strong> district(s), <strong>{contractorNetwork.states.length}</strong> state(s).</span>
          </div>
        )}
        {multiHopPaths.length === 0 ? (
          <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No multi-hop relationship paths through this project were found by Stage 5A.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {multiHopPaths.map((path, i) => (
              <div key={i} style={{ border: "1px solid #eef0f3", borderRadius: 3, padding: "0.55rem 0.75rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>
                  {path.nodes.map((n, idx) => (
                    <span key={idx} style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span style={{
                        color: n.type === "PROJECT" ? "#1c3557" : n.type === "CONTRACTOR" ? "#b45309" : "#4b6c8e",
                        fontWeight: n.id === project.project_id ? 700 : 500,
                        background: n.id === project.project_id ? "#f4f6fa" : "transparent",
                        padding: n.id === project.project_id ? "1px 5px" : 0,
                        borderRadius: 2,
                      }}>{n.id}</span>
                      {idx < path.nodes.length - 1 && <span style={{ color: "#9ca3af" }}>→</span>}
                    </span>
                  ))}
                  <span style={{ marginLeft: "auto", color: "#6b7280", fontWeight: 700 }}>{path.relationshipStrength.toFixed(1)}</span>
                </div>
                <div style={{ fontSize: "0.7rem", color: "#374151", marginTop: "0.3rem" }}>{path.explanation}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* SECTION 9 — Geographic context (Stage 5A, via API) */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel>Geographic Context ({geography.radius_km} km radius) — {geography.nearby_projects.length} Nearby Project(s)</SectionLabel>
        <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>{geography.disclaimer}</div>
        {geography.nearby_projects.length === 0 ? (
          <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>No other current projects lie within {geography.radius_km} km of this project.</div>
        ) : (
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse", marginBottom: geography.cluster_id ? "0.85rem" : 0 }}>
            <thead>
              <tr>
                <th>Nearby Project</th>
                <th>Distance</th>
                <th>Same Work Type</th>
                <th>Same Contractor</th>
                <th>Relationship Strength</th>
              </tr>
            </thead>
            <tbody>
              {geography.nearby_projects.map((r) => (
                <tr key={r.project_id}>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600, color: "#1c3557" }}>{r.project_id}</td>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{r.distance_km.toFixed(2)} km</td>
                  <td style={{ fontSize: "0.72rem" }}>{r.same_work_type ? "Yes" : "No"}</td>
                  <td style={{ fontSize: "0.72rem" }}>{r.same_contractor ? "Yes" : "No"}</td>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{r.relationship_strength.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {geography.cluster_id && (
          <div>
            <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", marginBottom: "0.4rem" }}>Shared Spatial Pattern</div>
            <div style={{ fontSize: "0.72rem", color: "#374151" }}>
              Part of cluster <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{geography.cluster_id}</span>. This reflects a shared spatial pattern and requires contextual review — it does not itself indicate wrongdoing.
            </div>
          </div>
        )}
      </Card>

      {/* SECTION 10 — Potential duplicate-like matches (via API) */}
      {geography.duplicate_like_matches.length > 0 && (
        <Card style={{ marginBottom: "1.25rem" }}>
          <SectionLabel title="distance <= 2km AND description similarity >= 0.5 AND same work type AND cost similarity >= 0.7">Potential Duplicate-Like Matches ({geography.duplicate_like_matches.length})</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {geography.duplicate_like_matches.map((m) => (
              <div key={m.other_project_id} style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 3, padding: "0.6rem 0.8rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "#92400e" }}>Potential duplicate-like relationship with <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{m.other_project_id}</span></span>
                  <span style={{ fontSize: "0.65rem", color: "#b45309", fontWeight: 700 }}>{m.distance_km.toFixed(2)} km</span>
                </div>
                <div style={{ display: "flex", gap: "1rem", fontSize: "0.7rem", color: "#78350f", marginTop: "0.3rem" }}>
                  <span>Description similarity: {pct(m.description_similarity)}</span>
                  <span>Cost similarity: {pct(m.cost_similarity)}</span>
                  <span>Shared: {m.shared_attributes.join(", ")}</span>
                </div>
                <div style={{ fontSize: "0.7rem", color: "#374151", marginTop: "0.3rem" }}>{m.explanation}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Related projects (attribute match on work type + district; legacy local adapter, no Stage 6.4 endpoint yet) */}
      {relatedProjects.length > 0 && (
        <Card style={{ marginBottom: "1.25rem" }}>
          <SectionLabel>Related Projects — Same Work Type &amp; District ({relatedProjects.length})</SectionLabel>
          <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.6rem" }}>
            Other current projects sharing this project's work type and district. This is a plain attribute match, not a similarity score or a flag of any kind.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {relatedProjects.map((rp) => (
              <span key={rp.projectId} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.7rem", color: "#1c3557", background: "#f4f6fa", border: "1px solid #dde1e7", padding: "3px 9px", borderRadius: 2 }}>
                {rp.projectId}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* SECTION 11 — Investigation recommendation, verbatim from Stage 4 via API */}
      <Card style={{ marginBottom: "1.25rem", borderTop: `3px solid ${LEVEL_COLOR[risk.risk_level]}` }}>
        <SectionLabel>Investigation Recommendation</SectionLabel>
        <div style={{ fontSize: "0.85rem", color: "#1f2937", fontWeight: 600, marginBottom: "0.5rem" }}>{risk.recommendation}</div>
        <div style={{ fontSize: "0.72rem", color: "#6b7280" }}>
          This recommendation reflects Stage 4's own classification of this project's risk score ({risk.risk_score.toFixed(1)}/100, {risk.risk_level}) and is not independently generated on this page. Final determination remains with the authorized investigator.
        </div>
      </Card>

      {/* V2.6 — human investigator review: status, notes, audit history. Separate from the risk signal above. */}
      <InvestigationWorkflow
        projectId={project.project_id}
        riskScore={risk.risk_score}
        riskLevel={risk.risk_level}
        canWrite={canWrite}
        onStatusKnown={setWorkflowStatus}
      />

      {/* Disclaimer */}
      <div style={{ background: "#f8faff", border: "1px solid #dde8f5", borderRadius: 3, padding: "0.75rem 1rem", fontSize: "0.7rem", color: "#4b6c8e" }}>
        <strong>Important: </strong>The information above is drawn directly from government project, billing, and payment records, Stage 4's explainable risk engine, Stage 5A's relationship and geographic intelligence, and synthetic scenario signals planted for demonstration purposes. It does not constitute an allegation, finding, or determination of fraud, misconduct, or illegality. All investigation decisions are the exclusive responsibility of authorised officers.
      </div>
    </div>
  );
}
