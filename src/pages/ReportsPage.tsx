import { useState } from "react";
import { PROJECTS, CONTRACTORS, KPI, formatINR } from "@/data/synthetic";

const REPORTS = [
  {
    id: "risk-summary",
    title: "Risk Summary Report",
    description: "Consolidated risk distribution across all monitored MPLADS projects with signal breakdown.",
    generated: "10 Sep 2026, 13:45 IST",
    pages: 12,
    category: "Risk Intelligence",
  },
  {
    id: "high-risk",
    title: "High-Risk Projects Report",
    description: "Detailed analysis of all projects with risk score ≥ 75, including supporting anomaly signals.",
    generated: "10 Sep 2026, 13:45 IST",
    pages: 28,
    category: "Risk Intelligence",
  },
  {
    id: "contractor-patterns",
    title: "Contractor Patterns Report",
    description: "Network analysis of contractors with elevated risk associations across multiple projects.",
    generated: "10 Sep 2026, 12:00 IST",
    pages: 18,
    category: "Contractor Intelligence",
  },
  {
    id: "geo-anomalies",
    title: "Geographic Anomalies Report",
    description: "Geo-spatial clustering analysis identifying proximity-based anomaly patterns.",
    generated: "09 Sep 2026, 09:30 IST",
    pages: 8,
    category: "Geo-Spatial Intelligence",
  },
  {
    id: "investigation-status",
    title: "Investigation Status Report",
    description: "Current queue status, officer assignments, and case progression summary.",
    generated: "10 Sep 2026, 13:45 IST",
    pages: 6,
    category: "Operations",
  },
];

export default function ReportsPage() {
  const [exported, setExported] = useState<string | null>(null);

  function handleExport(id: string, title: string) {
    setExported(title);
    setTimeout(() => setExported(null), 2500);
  }

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Intelligence Reports</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>System-generated analytical reports from NidhiGuard intelligence processing.</p>
      </div>

      {/* Summary stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.5rem" }}>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", borderTop: "2px solid #1c3557" }}>
          <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>Total Monitored</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#1c3557", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{KPI.totalProjects.toLocaleString()}</div>
          <div style={{ fontSize: "0.62rem", color: "#9ca3af", marginTop: "0.2rem" }}>MPLADS projects</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", borderTop: "2px solid #dc2626" }}>
          <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>High-Risk Projects</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#b91c1c", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{KPI.highRisk}</div>
          <div style={{ fontSize: "0.62rem", color: "#9ca3af", marginTop: "0.2rem" }}>Require investigation</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", borderTop: "2px solid #d97706" }}>
          <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>Flagged Contractors</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#b45309", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{CONTRACTORS.filter((c) => c.riskIndicator !== "Normal").length}</div>
          <div style={{ fontSize: "0.62rem", color: "#9ca3af", marginTop: "0.2rem" }}>Elevated or requires review</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", borderTop: "2px solid #1c3557" }}>
          <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>Total Value at Risk</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#1c3557", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>
            {formatINR(PROJECTS.filter((p) => p.riskLevel === "High").reduce((a, p) => a + p.sanctionedAmount, 0))}
          </div>
          <div style={{ fontSize: "0.62rem", color: "#9ca3af", marginTop: "0.2rem" }}>High-risk project value</div>
        </div>
      </div>

      {exported && (
        <div style={{ marginBottom: "1rem", padding: "0.6rem 1rem", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 3, fontSize: "0.75rem", color: "#15803d", fontWeight: 500 }}>
          Export initiated: "{exported}" — simulated export for prototype environment.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
        {REPORTS.map((r) => (
          <div key={r.id} style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1.1rem", display: "flex", alignItems: "center", gap: "1.5rem" }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.2rem" }}>
                <span style={{ fontSize: "0.62rem", fontWeight: 600, color: "#4b6c8e", background: "#eef3fb", border: "1px solid #c8d9f0", padding: "1px 7px", borderRadius: 2 }}>{r.category}</span>
                <span style={{ fontSize: "0.62rem", color: "#9ca3af" }}>{r.pages} pages</span>
              </div>
              <div style={{ fontSize: "0.875rem", fontWeight: 700, color: "#1c3557", marginBottom: "0.2rem" }}>{r.title}</div>
              <div style={{ fontSize: "0.72rem", color: "#6b7280" }}>{r.description}</div>
            </div>
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <div style={{ fontSize: "0.62rem", color: "#9ca3af", marginBottom: "0.5rem", whiteSpace: "nowrap" }}>Generated: {r.generated}</div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  onClick={() => {}}
                  style={{ padding: "4px 12px", fontSize: "0.7rem", fontWeight: 600, border: "1px solid #d1d5db", borderRadius: 2, background: "#fff", cursor: "pointer", color: "#374151", fontFamily: "inherit" }}>
                  View Report
                </button>
                <button
                  onClick={() => handleExport(r.id, r.title)}
                  style={{ padding: "4px 12px", fontSize: "0.7rem", fontWeight: 600, border: "none", borderRadius: 2, background: "#1c3557", cursor: "pointer", color: "#fff", fontFamily: "inherit" }}>
                  Export PDF
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* System note */}
      <div style={{ marginTop: "1.25rem", padding: "0.75rem 1rem", background: "#f4f5f7", border: "1px solid #e5e7eb", borderRadius: 3, fontSize: "0.65rem", color: "#6b7280", lineHeight: 1.6 }}>
        <strong style={{ color: "#374151" }}>NidhiGuard Intelligence Architecture:</strong>{" "}
        Government Data Sources → NidhiGuard Intelligence Layer → Data Correlation → Anomaly Detection → Relationship/Graph Analysis → Geo-Spatial Analysis → Explainable Risk Scoring → Investigation Prioritisation.
        All reports are generated automatically from connected government data pipelines and updated on each synchronisation cycle.
      </div>
    </div>
  );
}
