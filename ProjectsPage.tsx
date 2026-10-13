import { useState } from "react";
import { getAllProjects, getContractorById, getLocationByProject, getSignalsByProject } from "@/data/access";
import { SIGNAL_TYPE_LABELS } from "@/data/types";

// Stage 2 note: this page no longer imports from src/data/synthetic.ts.
// All project, contractor, location, and signal data now comes from the
// Stage 1 relational dataset via src/data/access.ts. See that file for the
// join logic (contractor/location are resolved by ID, never by name).

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

interface Props {
  onViewProject: (id: string) => void;
}

type SignalFilter = "All" | "HasSignals" | "NoSignals";

// Real project_status values in this dataset (no "Sanctioned"/"Stalled" —
// those existed only in the old 14-record demo set).
const STATUS_OPTIONS = ["All", "Completed", "In Progress", "Delayed"] as const;

export default function ProjectsPage({ onViewProject }: Props) {
  const [search, setSearch] = useState("");
  const [filterSignals, setFilterSignals] = useState<SignalFilter>("All");
  const [filterStatus, setFilterStatus] = useState("All");

  const allProjects = getAllProjects();

  // Resolve each project's contractor/location/signals once via the access
  // layer, then filter/search over the resolved view. Joins are by ID
  // (contractorId, projectId), never by name.
  const enriched = allProjects.map((project) => ({
    project,
    contractor: getContractorById(project.contractorId),
    location: getLocationByProject(project.projectId),
    signals: getSignalsByProject(project.projectId),
  }));

  const filtered = enriched.filter(({ project: p, contractor, location, signals }) => {
    const q = search.toLowerCase();
    const matchSearch =
      !q ||
      p.projectId.toLowerCase().includes(q) ||
      p.projectDescription.toLowerCase().includes(q) ||
      (contractor?.contractorName.toLowerCase().includes(q) ?? false) ||
      (location?.constituency.toLowerCase().includes(q) ?? false);

    const matchSignals =
      filterSignals === "All" ||
      (filterSignals === "HasSignals" && signals.length > 0) ||
      (filterSignals === "NoSignals" && signals.length === 0);

    const matchStatus = filterStatus === "All" || p.projectStatus === filterStatus;

    return matchSearch && matchSignals && matchStatus;
  });

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Projects</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>All MPLADS projects currently monitored by NidhiGuard. {allProjects.length} records loaded from government data.</p>
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
              <th>Constituency</th>
              <th>Contractor</th>
              <th>Status</th>
              <th>Value</th>
              <th title="Ground-truth signals planted in the synthetic demonstration dataset — not output from an intelligence engine">Planted Signals</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(({ project: p, contractor, location, signals }) => (
              <tr key={p.projectId}>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{p.projectId}</span></td>
                <td style={{ maxWidth: 200 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.projectDescription}>{p.projectDescription}</span></td>
                <td style={{ whiteSpace: "nowrap" }}>{p.workType}</td>
                <td style={{ whiteSpace: "nowrap" }}>{location?.constituency ?? "—"}</td>
                <td style={{ maxWidth: 150 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={contractor?.contractorName ?? "Unknown contractor"}>{contractor?.contractorName ?? "Unknown"}</span></td>
                <td>
                  <span style={{
                    fontSize: "0.65rem", fontWeight: 600, padding: "2px 7px", borderRadius: 2,
                    background: p.projectStatus === "Completed" ? "#f0fdf4" : p.projectStatus === "In Progress" ? "#eff6ff" : p.projectStatus === "Delayed" ? "#fef2f2" : "#f9fafb",
                    color: p.projectStatus === "Completed" ? "#15803d" : p.projectStatus === "In Progress" ? "#1d4ed8" : p.projectStatus === "Delayed" ? "#b91c1c" : "#374151",
                    border: `1px solid ${p.projectStatus === "Completed" ? "#bbf7d0" : p.projectStatus === "In Progress" ? "#bfdbfe" : p.projectStatus === "Delayed" ? "#fecaca" : "#e5e7eb"}`,
                  }}>{p.projectStatus}</span>
                </td>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{formatINR(p.sanctionedAmount)}</span></td>
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
                  <button onClick={() => onViewProject(p.projectId)}
                    style={{ background: "#1c3557", color: "#fff", border: "none", borderRadius: 2, fontSize: "0.68rem", fontWeight: 600, padding: "3px 10px", cursor: "pointer", letterSpacing: "0.04em", fontFamily: "inherit" }}>
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
