import { useState } from "react";
import { getContractorNetwork, getMultiHopPathsForContractor } from "@/data/contractorNetwork";
import { getContractors, getContractor, getRiskResults } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { ContractorSummary, ContractorDetail, RiskResultSummary } from "@/api/types";

// Stage 6.5: contractor identity, portfolio counts, and linked projects now
// come from GET /api/contractors / GET /api/contractors/{id} (Stage 6.2/6.3
// database-backed). Per-project risk badges come from the bulk
// GET /api/risk-results (Stage 6.5 addition — see RiskAnalysisPage).
//
// Stage 5A "Network Context" (work-type/district footprint, internal
// project pairs, multi-hop paths) has NO Stage 6.4 endpoint yet — the API's
// contractor-detail route only returns database relationships, not Stage 5A
// network analysis — so that section still reads the legacy local
// src/data/contractorNetwork.ts adapter. See the Stage 6.5 report.
//
// Portfolio size is never treated as a suspicion signal on this page, per
// Stage 5A's own explicit rule: a contractor with many legitimate projects
// is not itself an anomaly.

const RISK_LEVEL_COLOR: Record<string, string> = {
  CRITICAL: "#7f1d1d",
  HIGH: "#dc2626",
  MEDIUM: "#d97706",
  LOW: "#16a34a",
};

const RISK_DISCLAIMER = "Risk score indicates anomaly signals and does not constitute a finding of fraud.";

type SortKey = "totalValue" | "totalProjects" | "name";

const SORT_LABEL: Record<SortKey, string> = {
  totalValue: "Total Value",
  totalProjects: "Project Count",
  name: "Contractor Name",
};

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export default function ContractorsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("totalValue");

  const contractors = useApiData<ContractorSummary[]>(getContractors, []);
  const riskResults = useApiData<RiskResultSummary[]>(getRiskResults, []);
  // Detail is fetched only once a contractor is selected, not for all 75 up front.
  const selectedDetail = useApiData<ContractorDetail | null>(
    () => (selectedId ? getContractor(selectedId) : Promise.resolve(null)),
    [selectedId]
  );

  const loading = contractors.loading || riskResults.loading;
  const error = contractors.error || riskResults.error;

  if (error) return <ErrorBlock message={error} />;
  if (loading || !contractors.data || !riskResults.data) return <LoadingBlock label="Loading contractors…" />;

  const riskByProjectId = new Map(riskResults.data.map((r) => [r.project_id, r]));

  const filtered = contractors.data.filter((c) => {
    const q = search.toLowerCase();
    return !q || c.contractor_name.toLowerCase().includes(q) || c.contractor_id.toLowerCase().includes(q);
  });

  // Neutral descriptive ordering only — never a risk/suspicion ranking.
  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === "totalValue") return b.total_project_value - a.total_project_value;
    if (sortKey === "totalProjects") return b.total_projects - a.total_projects;
    return a.contractor_name.localeCompare(b.contractor_name);
  });

  const selected = selectedId ? contractors.data.find((c) => c.contractor_id === selectedId) : undefined;
  const selectedNetwork = selectedId ? getContractorNetwork(selectedId) : undefined;
  const selectedPaths = selectedId ? getMultiHopPathsForContractor(selectedId) : [];

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Contractor Intelligence</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>
          {contractors.data.length} contractors in the government dataset. Select a contractor to view portfolio and network context.
        </p>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by contractor name or ID..."
          style={{
            padding: "0.45rem 0.75rem", fontSize: "0.8rem", border: "1px solid #d1d5db",
            borderRadius: 3, outline: "none", fontFamily: "inherit", width: 280, background: "#fff",
          }}
        />
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}
          style={{ padding: "0.45rem 0.6rem", fontSize: "0.8rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
          {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => <option key={k} value={k}>Sort: {SORT_LABEL[k]}</option>)}
        </select>
        <span style={{ fontSize: "0.72rem", color: "#9ca3af", marginLeft: "auto" }}>{filtered.length} of {contractors.data.length} contractors</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selectedId ? "1.15fr 1fr" : "1fr", gap: "0.75rem" }}>
        {/* Table */}
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Contractor</th>
                <th>Type</th>
                <th>State</th>
                <th>Projects</th>
                <th>Total Value</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.contractor_id} onClick={() => setSelectedId(selectedId === c.contractor_id ? null : c.contractor_id)}
                  style={{ cursor: "pointer", background: selectedId === c.contractor_id ? "#eef3fb" : undefined }}>
                  <td>
                    <div style={{ fontWeight: 600, color: "#1c3557" }}>{c.contractor_name}</div>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.65rem", color: "#9ca3af" }}>{c.contractor_id}</div>
                  </td>
                  <td style={{ fontSize: "0.75rem", color: "#4b5563" }}>{c.contractor_type}</td>
                  <td style={{ fontSize: "0.75rem" }}>{c.state}</td>
                  <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{c.total_projects}</span></td>
                  <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{formatINR(c.total_project_value)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Side panel */}
        {selected && (
          <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", maxHeight: "82vh", overflowY: "auto" }}>
            <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.6rem" }}>
              Contractor Profile
            </div>
            <div style={{ fontSize: "0.9rem", fontWeight: 700, color: "#1c3557", marginBottom: "0.15rem" }}>{selected.contractor_name}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", color: "#9ca3af", marginBottom: "0.3rem" }}>{selected.contractor_id}</div>
            <div style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "1rem" }}>
              {selected.contractor_type} | {selected.state} | {selected.active_status}
            </div>

            {/* Portfolio (database) */}
            <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.4rem" }}>Portfolio</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", marginBottom: "1rem" }}>
              {[
                { label: "Total Projects", value: String(selected.total_projects) },
                { label: "Total Value", value: formatINR(selected.total_project_value) },
                { label: "Work Types", value: selectedNetwork ? String(selectedNetwork.workTypes.length) : "—" },
                { label: "Districts", value: selectedNetwork ? String(selectedNetwork.districts.length) : "—" },
              ].map((i) => (
                <div key={i.label} style={{ padding: "0.5rem 0.75rem", background: "#f8fafc", border: "1px solid #eef0f3", borderRadius: 3 }}>
                  <div style={{ fontSize: "0.62rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "0.2rem" }}>{i.label}</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: "0.9rem", color: "#1c3557" }}>{i.value}</div>
                </div>
              ))}
            </div>
            {selectedNetwork && (
              <div style={{ fontSize: "0.72rem", color: "#4b5563", marginBottom: "1rem" }}>
                <strong style={{ color: "#374151" }}>Work types:</strong> {selectedNetwork.workTypes.join(", ")}
                <br />
                <strong style={{ color: "#374151" }}>States:</strong> {selectedNetwork.states.join(", ")}
              </div>
            )}

            {/* Network (Stage 5A — legacy local adapter, no Stage 6.4 endpoint yet) */}
            <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.4rem", borderTop: "1px solid #eef0f3", paddingTop: "0.75rem" }}>
              Network Context
            </div>
            {!selectedNetwork ? (
              <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginBottom: "1rem" }}>No current-dataset project network for this contractor.</div>
            ) : (
              <div style={{ marginBottom: "1rem" }}>
                <div style={{ fontSize: "0.72rem", color: "#4b5563", marginBottom: "0.4rem" }}>
                  {selectedNetwork.connectedProjects.length} connected project{selectedNetwork.connectedProjects.length !== 1 ? "s" : ""}, {selectedNetwork.projectPairs.length} internal project pair{selectedNetwork.projectPairs.length !== 1 ? "s" : ""} within this portfolio.
                </div>
                {selectedPaths.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                    {selectedPaths.slice(0, 5).map((path, i) => (
                      <div key={i} style={{ padding: "0.4rem 0.6rem", background: "#f8fafc", borderRadius: 3, border: "1px solid #eef0f3", fontSize: "0.68rem", color: "#4b5563" }}>
                        {path.explanation}
                      </div>
                    ))}
                    {selectedPaths.length > 5 && (
                      <div style={{ fontSize: "0.66rem", color: "#9ca3af" }}>+ {selectedPaths.length - 5} more relationship path(s) not shown.</div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Linked projects (database), with per-project Stage 4 risk context */}
            <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.4rem", borderTop: "1px solid #eef0f3", paddingTop: "0.75rem" }}>
              Linked Projects
            </div>
            {selectedDetail.loading ? (
              <LoadingBlock label="Loading linked projects…" />
            ) : selectedDetail.error ? (
              <ErrorBlock message={selectedDetail.error} />
            ) : !selectedDetail.data || selectedDetail.data.projects.length === 0 ? (
              <div style={{ fontSize: "0.72rem", color: "#9ca3af" }}>No projects in current dataset.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                {selectedDetail.data.projects.map((p) => {
                  const risk = riskByProjectId.get(p.project_id);
                  return (
                    <div key={p.project_id} style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "0.4rem 0.6rem", background: "#f8fafc", borderRadius: 3, border: "1px solid #eef0f3" }}>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", color: "#1c3557", fontWeight: 600, minWidth: 52 }}>{p.project_id}</span>
                      <span style={{ fontSize: "0.72rem", color: "#374151", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.project_description}</span>
                      {risk ? (
                        <span style={{ fontSize: "0.6rem", fontWeight: 700, padding: "1px 6px", borderRadius: 2, whiteSpace: "nowrap", color: "#fff", background: RISK_LEVEL_COLOR[risk.risk_level] }}>
                          {risk.risk_score} {risk.risk_level}
                        </span>
                      ) : (
                        <span style={{ fontSize: "0.6rem", color: "#9ca3af", whiteSpace: "nowrap" }}>no risk result</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div style={{ marginTop: "0.75rem", padding: "0.5rem 0.6rem", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 3, fontSize: "0.65rem", color: "#92400e" }}>
              A larger portfolio or a broader network footprint is not itself an anomaly indicator. {RISK_DISCLAIMER}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
