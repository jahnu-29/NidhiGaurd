import { useState } from "react";
import { getInvestigationQueue, getProjects } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { InvestigationQueueResponse, ProjectSummary } from "@/api/types";

// Stage 6.5: the queue itself — membership, ranking, risk scores, levels,
// recommendations — now all come from GET /api/investigation-queue, which
// applies the same riskLevel != LOW / sorted-by-score-descending rule Stage
// 4 already classified projects with. District and sanctioned amount (not
// part of the queue response) are joined client-side from GET /api/projects
// by project_id, the same small-join pattern used on ProjectsPage.
//
// "Review status" (Pending Review / Under Investigation / Reviewed /
// Closed) remains frontend-only React state, not persisted — Stage 6.4 has
// no review-status endpoint, and this stage explicitly keeps it local.

type ReviewStatus = "Pending Review" | "Under Investigation" | "Reviewed" | "Closed";
type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

const REVIEW_STATUSES: ReviewStatus[] = ["Pending Review", "Under Investigation", "Reviewed", "Closed"];

const REVIEW_STATUS_STYLE: Record<ReviewStatus, { bg: string; color: string; border: string }> = {
  "Pending Review": { bg: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
  "Under Investigation": { bg: "#fffbeb", color: "#b45309", border: "#fde68a" },
  "Reviewed": { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
  "Closed": { bg: "#f0fdf4", color: "#15803d", border: "#bbf7d0" },
};

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

type LevelFilter = "All" | RiskLevel;

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export default function InvestigationQueuePage() {
  const queue = useApiData<InvestigationQueueResponse>(getInvestigationQueue, []);
  const projects = useApiData<ProjectSummary[]>(getProjects, []);

  const [reviewStatus, setReviewStatus] = useState<Record<string, ReviewStatus>>({});
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("All");
  const [statusFilter, setStatusFilter] = useState<"All" | ReviewStatus>("All");

  const loading = queue.loading || projects.loading;
  const error = queue.error || projects.error;

  if (error) return <ErrorBlock message={error} />;
  if (loading || !queue.data || !projects.data) return <LoadingBlock label="Loading investigation queue…" />;

  function changeStatus(projectId: string, status: ReviewStatus) {
    setReviewStatus((prev) => ({ ...prev, [projectId]: status }));
  }

  const projectById = new Map(projects.data.map((p) => [p.project_id, p]));
  const queueItems = queue.data.items;

  const rows = queueItems.map((item) => ({
    item,
    project: projectById.get(item.project_id),
    status: reviewStatus[item.project_id] ?? "Pending Review",
  }));

  const filtered = rows.filter(({ item, status }) => {
    const q = search.toLowerCase();
    const matchSearch = !q || item.project_id.toLowerCase().includes(q) || item.project_description.toLowerCase().includes(q);
    const matchLevel = levelFilter === "All" || item.risk_level === levelFilter;
    const matchStatus = statusFilter === "All" || status === statusFilter;
    return matchSearch && matchLevel && matchStatus;
  });

  const countByReviewStatus = (s: ReviewStatus) =>
    queueItems.filter((item) => (reviewStatus[item.project_id] ?? "Pending Review") === s).length;

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Investigation Priority Queue</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>
          {queue.data.total} of {projects.data.length} monitored projects require review, ranked by Stage 4 risk score.
        </p>
        <p style={{ fontSize: "0.68rem", color: "#9ca3af", marginTop: "0.3rem", fontStyle: "italic" }}>{queue.data.disclaimer}</p>
      </div>

      {/* Summary: review-status workflow counts */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {REVIEW_STATUSES.map((s) => {
          const st = REVIEW_STATUS_STYLE[s];
          return (
            <div key={s} style={{ background: "#fff", border: `1px solid ${st.border}`, borderRadius: 3, padding: "0.75rem 1rem", borderTop: `2px solid ${st.color}` }}>
              <div style={{ fontSize: "0.62rem", fontWeight: 700, color: st.color, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>{s}</div>
              <div style={{ fontSize: "1.8rem", fontWeight: 700, color: st.color, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{countByReviewStatus(s)}</div>
            </div>
          );
        })}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by project ID or description..."
          style={{
            padding: "0.45rem 0.75rem", fontSize: "0.8rem", border: "1px solid #d1d5db",
            borderRadius: 3, outline: "none", fontFamily: "inherit", width: 280, background: "#fff",
          }}
        />
        <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value as LevelFilter)}
          style={{ padding: "0.45rem 0.6rem", fontSize: "0.8rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
          <option value="All">All Risk Levels</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "All" | ReviewStatus)}
          style={{ padding: "0.45rem 0.6rem", fontSize: "0.8rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
          <option value="All">All Review Statuses</option>
          {REVIEW_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span style={{ fontSize: "0.72rem", color: "#9ca3af", marginLeft: "auto" }}>{filtered.length} of {queueItems.length} queued</span>
      </div>

      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
        <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Priority</th>
              <th>Project ID</th>
              <th>Description</th>
              <th>Work Type</th>
              <th>District</th>
              <th>Value</th>
              <th>Risk Score</th>
              <th>Level</th>
              <th>Components</th>
              <th>Recommendation</th>
              <th>Review Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(({ item, project, status }) => (
              <tr key={item.project_id}>
                <td>
                  <span style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    width: 24, height: 24, borderRadius: "50%", background: LEVEL_COLOR[item.risk_level],
                    color: "#fff", fontSize: "0.65rem", fontWeight: 700,
                  }}>{item.rank}</span>
                </td>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{item.project_id}</span></td>
                <td style={{ maxWidth: 200 }}>
                  <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.project_description}
                  </span>
                </td>
                <td style={{ fontSize: "0.75rem", color: "#4b5563" }}>{item.work_type}</td>
                <td style={{ fontSize: "0.75rem", color: "#4b5563" }}>{project?.district ?? "—"}</td>
                <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{project ? formatINR(project.sanctioned_amount) : "—"}</span></td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                    <div style={{ width: 36, height: 3, background: "#eef0f3", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${item.risk_score}%`, background: LEVEL_COLOR[item.risk_level] }} />
                    </div>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600, color: LEVEL_COLOR[item.risk_level] }}>{item.risk_score}</span>
                  </div>
                </td>
                <td>
                  <span style={{ ...LEVEL_BADGE_STYLE[item.risk_level], fontSize: "0.62rem", fontWeight: 700, padding: "2px 7px", borderRadius: 2 }}>
                    {item.risk_level}
                  </span>
                </td>
                <td>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600, color: "#374151" }}>{item.components_detected}</span>
                  <span style={{ fontSize: "0.65rem", color: "#9ca3af", marginLeft: "0.2rem" }}>/ 5</span>
                </td>
                <td style={{ fontSize: "0.72rem", color: "#374151" }}>{item.recommendation}</td>
                <td>
                  <select
                    value={status}
                    onChange={(e) => changeStatus(item.project_id, e.target.value as ReviewStatus)}
                    style={{
                      padding: "2px 6px", fontSize: "0.68rem", borderRadius: 2, fontFamily: "inherit",
                      cursor: "pointer", fontWeight: 700,
                      background: REVIEW_STATUS_STYLE[status].bg, color: REVIEW_STATUS_STYLE[status].color,
                      border: `1px solid ${REVIEW_STATUS_STYLE[status].border}`,
                    }}
                  >
                    {REVIEW_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={11} style={{ textAlign: "center", padding: "1.5rem", color: "#9ca3af", fontSize: "0.8rem" }}>
                  No queued projects match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: "0.75rem", padding: "0.5rem 0.75rem", background: "#f8faff", border: "1px solid #dde8f5", borderRadius: 3, fontSize: "0.65rem", color: "#4b6c8e" }}>
        Queue membership and ranking are generated automatically from Stage 4's independently computed risk scores. Review status tracks investigator progress for this session only and is not itself a risk signal.
      </div>
    </div>
  );
}