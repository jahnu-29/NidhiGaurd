import { useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, CartesianGrid,
} from "recharts";
import { getProjects, getRiskResults, getProjectRisk } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { ProjectSummary, RiskResultSummary, ProjectRiskResponse, RiskComponents } from "@/api/types";

// Stage 6.5 note: Stage 4 (the backend) is the single source of truth for
// every value on this page — nothing here recalculates a score. The
// register/charts come from one bulk GET /api/risk-results call (all 200
// projects); a row's full component breakdown is fetched lazily from
// GET /api/projects/{id}/risk only when that row is expanded, so loading
// this page never makes 200 separate requests.

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

const RISK_DISCLAIMER = "Risk score indicates anomaly signals and does not constitute a finding of fraud.";

function ExpandedRow({ projectId }: { projectId: string }) {
  const detail = useApiData<ProjectRiskResponse>(() => getProjectRisk(projectId), [projectId]);

  if (detail.error) return <ErrorBlock message={detail.error} />;
  if (detail.loading || !detail.data) return <LoadingBlock label="Loading component breakdown…" />;

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "0.6rem" }}>
        {COMPONENT_LABELS.map(({ key, label }) => {
          const c = detail.data!.components[key];
          return (
            <div key={key} style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.6rem 0.7rem" }}>
              <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.3rem" }}>{label}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: "0.25rem", marginBottom: "0.3rem" }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.95rem", fontWeight: 700, color: "#1c3557" }}>{c.score}</span>
                <span style={{ fontSize: "0.68rem", color: "#9ca3af" }}>/ {c.max_score}</span>
              </div>
              <div style={{ width: "100%", height: 3, background: "#eef0f3", borderRadius: 2, overflow: "hidden", marginBottom: "0.4rem" }}>
                <div style={{ height: "100%", width: `${(c.score / c.max_score) * 100}%`, background: c.detected ? "#dc2626" : "#9ca3af" }} />
              </div>
              <div style={{ fontSize: "0.68rem", color: "#4b5563", lineHeight: 1.4 }}>{c.explanation}</div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: "0.65rem", color: "#9ca3af", marginTop: "0.6rem", fontStyle: "italic" }}>{detail.data.disclaimer}</div>
    </>
  );
}

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export default function RiskAnalysisPage() {
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);

  const projects = useApiData<ProjectSummary[]>(getProjects, []);
  const riskResults = useApiData<RiskResultSummary[]>(getRiskResults, []);

  const loading = projects.loading || riskResults.loading;
  const error = projects.error || riskResults.error;

  if (error) return <ErrorBlock message={error} />;
  if (loading || !projects.data || !riskResults.data) return <LoadingBlock label="Loading risk analysis…" />;

  const projectById = new Map(projects.data.map((p) => [p.project_id, p]));
  const countByLevel = (level: RiskLevel) => riskResults.data!.filter((r) => r.risk_level === level).length;

  const scatterData = riskResults.data.map((r) => {
    const project = projectById.get(r.project_id);
    return { x: project ? project.sanctioned_amount / 1000 : 0, y: r.risk_score, id: r.project_id, level: r.risk_level };
  });

  const byWorkType = Object.entries(
    riskResults.data.reduce<Record<string, { low: number; medium: number; high: number; critical: number }>>((acc, r) => {
      const workType = projectById.get(r.project_id)?.work_type ?? "Unknown";
      if (!acc[workType]) acc[workType] = { low: 0, medium: 0, high: 0, critical: 0 };
      if (r.risk_level === "CRITICAL") acc[workType].critical++;
      else if (r.risk_level === "HIGH") acc[workType].high++;
      else if (r.risk_level === "MEDIUM") acc[workType].medium++;
      else acc[workType].low++;
      return acc;
    }, {})
  ).map(([workType, counts]) => ({ workType, ...counts }));

  const sortedResults = [...riskResults.data].sort((a, b) => b.risk_score - a.risk_score);

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Risk Analysis</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>Backend-generated risk intelligence across all monitored MPLADS projects.</p>
        <p style={{ fontSize: "0.68rem", color: "#9ca3af", marginTop: "0.3rem", fontStyle: "italic" }}>{RISK_DISCLAIMER}</p>
      </div>

      {/* Summary cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {([
          { label: "Critical Risk", level: "CRITICAL" as RiskLevel },
          { label: "High Risk", level: "HIGH" as RiskLevel },
          { label: "Medium Risk", level: "MEDIUM" as RiskLevel },
          { label: "Low Risk", level: "LOW" as RiskLevel },
        ]).map((c) => (
          <div key={c.label} style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", borderTop: `2px solid ${LEVEL_COLOR[c.level]}` }}>
            <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.35rem" }}>{c.label}</div>
            <div style={{ fontSize: "2rem", fontWeight: 700, color: LEVEL_COLOR[c.level], fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{countByLevel(c.level)}</div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem" }}>
          <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.75rem" }}>Project Value vs Risk Score</div>
          <ResponsiveContainer width="100%" height={200}>
            <ScatterChart margin={{ left: 0, right: 10, bottom: 0, top: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="x" name="Value (₹K)" tick={{ fontSize: 10, fill: "#9ca3af" }} label={{ value: "Value (₹K)", position: "insideBottomRight", offset: -5, fontSize: 9, fill: "#9ca3af" }} />
              <YAxis dataKey="y" name="Risk Score" tick={{ fontSize: 10, fill: "#9ca3af" }} domain={[0, 100]} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ payload }) => {
                if (!payload?.length) return null;
                const d = payload[0].payload;
                return <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.4rem 0.7rem", fontSize: "0.72rem" }}>
                  <div style={{ fontWeight: 600, color: "#1c3557" }}>{d.id}</div>
                  <div style={{ color: "#6b7280" }}>Value: ₹{d.x.toFixed(0)}K | Risk: {d.y}</div>
                </div>;
              }} />
              <Scatter data={scatterData} shape={(props: any) => {
                const { cx, cy, payload } = props;
                return <circle cx={cx} cy={cy} r={5} fill={LEVEL_COLOR[payload.level as RiskLevel]} opacity={0.8} />;
              }} />
            </ScatterChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
            {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as RiskLevel[]).map((level) => (
              <div key={level} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.65rem", color: "#6b7280" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: LEVEL_COLOR[level], display: "inline-block" }} />
                {level.charAt(0) + level.slice(1).toLowerCase()}
              </div>
            ))}
          </div>
        </div>

        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem" }}>
          <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.75rem" }}>Risk by Work Type</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={byWorkType} layout="vertical" margin={{ left: 100, right: 15 }}>
              <XAxis type="number" tick={{ fontSize: 9, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="workType" tick={{ fontSize: 9, fill: "#4b5563" }} axisLine={false} tickLine={false} width={95} />
              <Tooltip contentStyle={{ fontSize: "0.72rem" }} />
              <Bar dataKey="critical" name="Critical" fill={LEVEL_COLOR.CRITICAL} stackId="a" />
              <Bar dataKey="high" name="High" fill={LEVEL_COLOR.HIGH} stackId="a" />
              <Bar dataKey="medium" name="Medium" fill={LEVEL_COLOR.MEDIUM} stackId="a" />
              <Bar dataKey="low" name="Low" fill={LEVEL_COLOR.LOW} stackId="a" radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Risk table */}
      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ padding: "0.75rem 1.1rem", borderBottom: "1px solid #eef0f3", fontSize: "0.68rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.07em", textTransform: "uppercase" }}>Risk Register — All Projects</div>
        <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Project ID</th><th>Description</th><th>District</th><th>Value</th>
              <th>Risk Score</th><th>Level</th><th>Components Detected</th><th>Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {sortedResults.map((r) => {
              const project = projectById.get(r.project_id);
              const isExpanded = expandedProjectId === r.project_id;
              return (
                <>
                  <tr
                    key={r.project_id}
                    onClick={() => setExpandedProjectId(isExpanded ? null : r.project_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{r.project_id}</span></td>
                    <td style={{ maxWidth: 220 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{project?.project_description ?? "—"}</span></td>
                    <td>{project?.district ?? "—"}</td>
                    <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{project ? formatINR(project.sanctioned_amount) : "—"}</span></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                        <div style={{ width: 48, height: 4, background: "#eef0f3", borderRadius: 2, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${r.risk_score}%`, background: LEVEL_COLOR[r.risk_level] }} />
                        </div>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600 }}>{r.risk_score}</span>
                      </div>
                    </td>
                    <td>
                      <span style={{ ...LEVEL_BADGE_STYLE[r.risk_level], fontSize: "0.62rem", fontWeight: 700, padding: "2px 7px", borderRadius: 2 }}>
                        {r.risk_level}
                      </span>
                    </td>
                    <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{r.components_detected} / 5</span></td>
                    <td><span style={{ fontSize: "0.75rem", color: "#374151" }}>{r.recommendation}</span></td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${r.project_id}-detail`}>
                      <td colSpan={8} style={{ background: "#f8fafc", padding: "0.9rem 1.1rem", borderBottom: "1px solid #eef0f3" }}>
                        <ExpandedRow projectId={r.project_id} />
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
