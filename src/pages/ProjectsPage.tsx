import { useState } from "react";
import { getSignalsByProject } from "@/data/access";
import { SIGNAL_TYPE_LABELS } from "@/data/types";
import { getProjects, getContractors } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { useAuth } from "@/auth/AuthContext";
import { canInvestigate } from "@/auth/permissions";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { ProjectSummary, ContractorSummary } from "@/api/types";

// Stage 6.5 note: project list data now comes from GET /api/projects
// (database-backed, Stage 6.2/6.3), with contractor names resolved from a
// separate GET /api/contractors call and joined by contractor_id client-side
// (two small API responses merged in the browser, not a database query
// reimplemented in React). "Planted Signals" has no Stage 6.4 endpoint yet,
// so that one column still reads the legacy Stage 1 access layer — see the
// Stage 6.5 report for why.

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

interface Props {
  onViewProject: (id: string) => void;
}

type SignalFilter = "All" | "HasSignals" | "NoSignals";

const STATUS_OPTIONS = ["All", "Completed", "In Progress", "Delayed"] as const;

export default function ProjectsPage({ onViewProject }: Props) {
  const [search, setSearch] = useState("");
  const [filterSignals, setFilterSignals] = useState<SignalFilter>("All");
  const [filterStatus, setFilterStatus] = useState("All");

  const projects = useApiData<ProjectSummary[]>(getProjects, []);
  // Stage 6.6: contractor records are Investigator/Administrator data (backend
  // answers 403 to a Viewer). A Viewer sees the contractor ID instead of the
  // name, and has no "View" action because project investigation is not a
  // Viewer capability.
  const { user } = useAuth();
  const mayInvestigate = !!user && canInvestigate(user.role);
  const contractors = useApiData<ContractorSummary[]>(
    () => (mayInvestigate ? getContractors() : Promise.resolve([])),
    [mayInvestigate]
  );

  const loading = projects.loading || contractors.loading;
  const error = projects.error || contractors.error;

  if (error) return <ErrorBlock message={error} />;
  if (loading || !projects.data || !contractors.data) return <LoadingBlock label="Loading projects…" />;

  const contractorNameById = new Map(contractors.data.map((c) => [c.contractor_id, c.contractor_name]));

  const enriched = projects.data.map((project) => ({
    project,
    contractorName: contractorNameById.get(project.contractor_id) ?? (mayInvestigate ? "Unknown" : project.contractor_id),
    signals: getSignalsByProject(project.project_id),
  }));

  const filtered = enriched.filter(({ project: p, contractorName, signals }) => {
    const q = search.toLowerCase();
    const matchSearch =
      !q ||
      p.project_id.toLowerCase().includes(q) ||
      p.project_description.toLowerCase().includes(q) ||
      contractorName.toLowerCase().includes(q) ||
      p.district.toLowerCase().includes(q);

    const matchSignals =
      filterSignals === "All" ||
      (filterSignals === "HasSignals" && signals.length > 0) ||
      (filterSignals === "NoSignals" && signals.length === 0);

    const matchStatus = filterStatus === "All" || p.project_status === filterStatus;

    return matchSearch && matchSignals && matchStatus;
  });

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Projects</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>All MPLADS projects currently monitored by NidhiGuard. {projects.data.length} records loaded from the backend.</p>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by ID, description, contractor..."
          style={{
            padding: "0.45rem 0.75rem", fontSize: "0.8rem", border: "1px solid #d1d5db",
            borderRadius: 3, outline: "none", fontFamily: "inherit", width: 280, background: "#fff",
          }}
        />
        <select value={filterSignals} onChange={(e) => setFilterSignals(e.target.value as SignalFilter)}
          style={{ padding: "0.45rem 0.6rem", fontSize: "0.8rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
          <option value="All">All Projects</option>
          <option value="HasSignals">Has Planted Signals</option>
          <option value="NoSignals">No Signals Planted</option>
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          style={{ padding: "0.45rem 0.6rem", fontSize: "0.8rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s === "All" ? "All Statuses" : s}</option>
          ))}
        </select>
        <span style={{ fontSize: "0.72rem", color: "#9ca3af", marginLeft: "auto" }}>{filtered.length} records</span>
      </div>

      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
        <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Project ID</th>
              <th>Description</th>
              <th>Type</th>
              <th>District</th>
              <th>Contractor</th>
              <th>Status</th>
              <th>Value</th>
              <th title="Ground-truth signals planted in the synthetic demonstration dataset — not output from an intelligence engine">Planted Signals</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(({ project: p, contractorName, signals }) => (
              <tr key={p.project_id}>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{p.project_id}</span></td>
                <td style={{ maxWidth: 200 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.project_description}>{p.project_description}</span></td>
                <td style={{ whiteSpace: "nowrap" }}>{p.work_type}</td>
                <td style={{ whiteSpace: "nowrap" }}>{p.district}</td>
                <td style={{ maxWidth: 150 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={contractorName}>{contractorName}</span></td>
                <td>
                  <span style={{
                    fontSize: "0.65rem", fontWeight: 600, padding: "2px 7px", borderRadius: 2,
                    background: p.project_status === "Completed" ? "#f0fdf4" : p.project_status === "In Progress" ? "#eff6ff" : p.project_status === "Delayed" ? "#fef2f2" : "#f9fafb",
                    color: p.project_status === "Completed" ? "#15803d" : p.project_status === "In Progress" ? "#1d4ed8" : p.project_status === "Delayed" ? "#b91c1c" : "#374151",
                    border: `1px solid ${p.project_status === "Completed" ? "#bbf7d0" : p.project_status === "In Progress" ? "#bfdbfe" : p.project_status === "Delayed" ? "#fecaca" : "#e5e7eb"}`,
                  }}>{p.project_status}</span>
                </td>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{formatINR(p.sanctioned_amount)}</span></td>
                <td>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                    {signals.length === 0 && <span style={{ fontSize: "0.65rem", color: "#9ca3af" }}>—</span>}
                    {signals.slice(0, 2).map((s) => (
                      <span key={s.signalId} className="signal-tag" style={{ background: "#eef0f3", color: "#374151" }}>{SIGNAL_TYPE_LABELS[s.signalType].split(" ")[0]}</span>
                    ))}
                    {signals.length > 2 && <span className="signal-tag" style={{ background: "#eef0f3", color: "#6b7280" }}>+{signals.length - 2}</span>}
                  </div>
                </td>
                <td>
                  {mayInvestigate ? (
                    <button onClick={() => onViewProject(p.project_id)}
                      style={{ background: "#1c3557", color: "#fff", border: "none", borderRadius: 2, fontSize: "0.68rem", fontWeight: 600, padding: "3px 10px", cursor: "pointer", letterSpacing: "0.04em", fontFamily: "inherit" }}>
                      View
                    </button>
                  ) : (
                    <span style={{ fontSize: "0.65rem", color: "#9ca3af" }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}