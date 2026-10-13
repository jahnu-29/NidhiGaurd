import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { getDashboardSummary, getInvestigationQueue } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { useAuth } from "@/auth/AuthContext";
import { canInvestigate } from "@/auth/permissions";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { DashboardSummaryResponse, InvestigationQueueResponse } from "@/api/types";

const DATA_SOURCES = [
  "MPLADS Project Records",
  "Expenditure Records",
  "Bill & Payment Records",
  "Contractor Records",
  "Geographic Records",
  "Historical Project Records",
];

const LEVEL_COLOR: Record<string, string> = {
  CRITICAL: "#7f1d1d",
  HIGH: "#dc2626",
  MEDIUM: "#d97706",
  LOW: "#16a34a",
};

interface Props {
  onViewProject: (id: string) => void;
}

function KPICard({ label, value, sub, alert }: { label: string; value: string; sub?: string; alert?: boolean }) {
  return (
    <div style={{
      background: "#fff", border: "1px solid #dde1e7", borderRadius: 3,
      padding: "0.9rem 1.1rem", borderTop: `2px solid ${alert ? "#dc2626" : "#1c3557"}`,
    }}>
      <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.4rem" }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 700, color: alert ? "#b91c1c" : "#1c3557", lineHeight: 1, fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
      {sub && <div style={{ fontSize: "0.65rem", color: "#9ca3af", marginTop: "0.3rem" }}>{sub}</div>}
    </div>
  );
}

const RTOOLTIP = ({ active, payload }: any) => {
  if (active && payload?.length) {
    return (
      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.4rem 0.7rem", fontSize: "0.75rem", color: "#1f2937" }}>
        <strong>{payload[0].name}</strong>: {payload[0].value} projects
      </div>
    );
  }
  return null;
};

export default function DashboardPage({ onViewProject }: Props) {
  const summary = useApiData<DashboardSummaryResponse>(getDashboardSummary, []);
  // Stage 6.6: the investigation queue is an Investigator/Administrator resource
  // (backend answers 403 to a Viewer), so a Viewer's dashboard skips it entirely.
  const { user } = useAuth();
  const mayInvestigate = !!user && canInvestigate(user.role);
  const queue = useApiData<InvestigationQueueResponse | null>(
    () => (mayInvestigate ? getInvestigationQueue() : Promise.resolve(null)),
    [mayInvestigate]
  );

  const loading = summary.loading || queue.loading;
  const error = summary.error || queue.error;

  return (
    <div>
      {/* Page title */}
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>
          MPLADS Intelligence Dashboard
        </h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>
          Intelligence generated from connected government project and expenditure records, served by the NidhiGuard backend.
        </p>
      </div>

      {/* Data connectivity */}
      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.65rem" }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.05em", textTransform: "uppercase" }}>Connected Government Data Sources</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.35rem" }}>
          {DATA_SOURCES.map((s) => (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.72rem", color: "#374151" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#22c55e", flexShrink: 0 }} />
              {s} <span style={{ color: "#6b7280" }}>— Connected</span>
            </div>
          ))}
        </div>
      </div>

      {error && <ErrorBlock message={error} />}
      {!error && loading && <LoadingBlock label="Loading dashboard…" />}

      {!error && !loading && summary.data && (queue.data || !mayInvestigate) && (
        <>
          {/* KPIs — every value below comes from GET /api/dashboard/summary and
              GET /api/investigation-queue, never a frontend constant. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
            <KPICard label="Total Projects Monitored" value={summary.data.total_projects.toLocaleString()} sub="Across all constituencies" />
            <KPICard label="High-Risk Projects" value={String(summary.data.risk_level_distribution.high + summary.data.risk_level_distribution.critical)} alert sub="HIGH + CRITICAL" />
            <KPICard label="Medium-Risk Projects" value={String(summary.data.risk_level_distribution.medium)} sub="Review recommended" />
            <KPICard label="Investigation Queue" value={String(summary.data.investigation_queue_size)} alert sub="Risk level above LOW" />
          </div>

          {/* Charts row — both panels show the same backend-computed risk-level
              distribution (pie + bar), not fabricated signal-type data. */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
            <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem" }}>
              <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.75rem" }}>Risk Level Distribution</div>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={[
                      { name: "Low", value: summary.data.risk_level_distribution.low, color: LEVEL_COLOR.LOW },
                      { name: "Medium", value: summary.data.risk_level_distribution.medium, color: LEVEL_COLOR.MEDIUM },
                      { name: "High", value: summary.data.risk_level_distribution.high, color: LEVEL_COLOR.HIGH },
                      { name: "Critical", value: summary.data.risk_level_distribution.critical, color: LEVEL_COLOR.CRITICAL },
                    ]}
                    dataKey="value" cx="50%" cy="50%" innerRadius={45} outerRadius={72} strokeWidth={2}
                  >
                    {[LEVEL_COLOR.LOW, LEVEL_COLOR.MEDIUM, LEVEL_COLOR.HIGH, LEVEL_COLOR.CRITICAL].map((c) => <Cell key={c} fill={c} />)}
                  </Pie>
                  <Legend iconType="circle" iconSize={8} formatter={(v) => <span style={{ fontSize: "0.7rem", color: "#4b5563" }}>{v}</span>} />
                  <Tooltip formatter={(v) => [v, "Projects"]} contentStyle={{ fontSize: "0.75rem" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem" }}>
              <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "0.75rem" }}>Projects by Risk Level</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart
                  data={[
                    { level: "Low", count: summary.data.risk_level_distribution.low },
                    { level: "Medium", count: summary.data.risk_level_distribution.medium },
                    { level: "High", count: summary.data.risk_level_distribution.high },
                    { level: "Critical", count: summary.data.risk_level_distribution.critical },
                  ]}
                  layout="vertical" margin={{ left: 60, right: 20 }}
                >
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="level" tick={{ fontSize: 10, fill: "#4b5563" }} axisLine={false} tickLine={false} width={55} />
                  <Tooltip content={<RTOOLTIP />} cursor={{ fill: "#f4f5f7" }} />
                  <Bar dataKey="count" radius={[0, 2, 2, 0]}>
                    {[LEVEL_COLOR.LOW, LEVEL_COLOR.MEDIUM, LEVEL_COLOR.HIGH, LEVEL_COLOR.CRITICAL].map((c) => <Cell key={c} fill={c} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* High-priority projects — top of GET /api/investigation-queue */}
          {queue.data && (
          <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ padding: "0.9rem 1.1rem", borderBottom: "1px solid #eef0f3" }}>
              <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.05em", textTransform: "uppercase" }}>High-Priority Projects</div>
              <div style={{ fontSize: "0.7rem", color: "#6b7280", marginTop: "0.2rem" }}>Top of the investigation queue — ranked by Stage 4 risk score, descending.</div>
            </div>
            <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Project ID</th>
                  <th>Description</th>
                  <th>Contractor</th>
                  <th>Risk Score</th>
                  <th>Level</th>
                  <th>Recommendation</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {queue.data.items.slice(0, 5).map((item) => (
                  <tr key={item.project_id}>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", color: "#6b7280" }}>#{item.rank}</td>
                    <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{item.project_id}</span></td>
                    <td style={{ maxWidth: 220 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.project_description}</span></td>
                    <td style={{ maxWidth: 160 }}><span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.contractor_id}</span></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
                        <div style={{ width: 40, height: 4, background: "#eef0f3", borderRadius: 2, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${item.risk_score}%`, background: LEVEL_COLOR[item.risk_level] }} />
                        </div>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600, color: item.risk_level === "LOW" ? "#1f2937" : "#b91c1c" }}>{item.risk_score}</span>
                      </div>
                    </td>
                    <td>
                      <span style={{ fontSize: "0.65rem", fontWeight: 700, padding: "2px 8px", borderRadius: 2, letterSpacing: "0.06em", color: "#fff", background: LEVEL_COLOR[item.risk_level] }}>
                        {item.risk_level}
                      </span>
                    </td>
                    <td style={{ fontSize: "0.72rem", color: "#374151" }}>{item.recommendation}</td>
                    <td>
                      <button
                        onClick={() => onViewProject(item.project_id)}
                        style={{
                          background: "#1c3557", color: "#fff", border: "none", borderRadius: 2,
                          fontSize: "0.68rem", fontWeight: 600, padding: "3px 10px", cursor: "pointer",
                          letterSpacing: "0.04em", fontFamily: "inherit",
                        }}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </>
      )}
    </div>
  );
}