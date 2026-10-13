import { useState, useMemo } from "react";
import { getAllLocations, getProjectById, getLocationByProject, getContractorById } from "@/data/access";
import { getGeographyOverview, getProjectGeography, getRiskResults } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type {
  GeographyOverviewResponse, ProjectGeographyResponse, RiskResultSummary,
} from "@/api/types";

// Stage 6.5 note: Stage 5A intelligence (dataset-wide nearby pairs/clusters/
// duplicate-like matches, and per-project geographic context) and Stage 4
// risk now come from the backend: GET /api/geography (Stage 6.5 addition —
// see backend/app/api/schemas.py's GeographyOverviewResponse for why a bulk
// endpoint was needed), GET /api/projects/{id}/geography, and the bulk
// GET /api/risk-results. Map geometry (every project's latitude/longitude,
// needed to plot all 200 markers) has no Stage 6.4 endpoint — ProjectSummary
// doesn't include coordinates — so the map and basic project-identity fields
// (description, work type, value) still read the legacy Stage 1 local
// adapter (src/data/access.ts). Map design and behavior are unchanged.

function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

const RISK_LEVEL_COLOR: Record<string, string> = {
  CRITICAL: "#7f1d1d",
  HIGH: "#dc2626",
  MEDIUM: "#d97706",
  LOW: "#16a34a",
};

const MAP_W = 420, MAP_H = 240, MAP_PAD = 20;

const COLOR_SELECTED = "#1c3557";
const COLOR_NEARBY = "#d97706";
const COLOR_MUTED = "#334155";
const COLOR_LINE = "#94a3b8";

function buildProjector(locations: { latitude: number; longitude: number }[], padFraction: number, minSpanDeg: number) {
  const lats = locations.map((l) => l.latitude);
  const lons = locations.map((l) => l.longitude);
  const latSpan = Math.max(Math.max(...lats) - Math.min(...lats), minSpanDeg);
  const lonSpan = Math.max(Math.max(...lons) - Math.min(...lons), minSpanDeg);
  const latCenter = (Math.max(...lats) + Math.min(...lats)) / 2;
  const lonCenter = (Math.max(...lons) + Math.min(...lons)) / 2;
  const latPad = latSpan * padFraction;
  const lonPad = lonSpan * padFraction;
  const minLat = latCenter - latSpan / 2 - latPad, maxLat = latCenter + latSpan / 2 + latPad;
  const minLon = lonCenter - lonSpan / 2 - lonPad, maxLon = lonCenter + lonSpan / 2 + lonPad;
  return (lat: number, lon: number) => ({
    x: MAP_PAD + ((lon - minLon) / (maxLon - minLon)) * (MAP_W - 2 * MAP_PAD),
    y: MAP_PAD + ((maxLat - lat) / (maxLat - minLat)) * (MAP_H - 2 * MAP_PAD),
  });
}

type ContractorFilter = "All" | "Yes" | "No";

export default function GeographicPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState("All");
  const [sameContractorFilter, setSameContractorFilter] = useState<ContractorFilter>("All");
  const [sameWorkTypeFilter, setSameWorkTypeFilter] = useState<ContractorFilter>("All");

  const overview = useApiData<GeographyOverviewResponse>(getGeographyOverview, []);
  const riskResults = useApiData<RiskResultSummary[]>(getRiskResults, []);
  const selectedGeo = useApiData<ProjectGeographyResponse | null>(
    () => (selectedId ? getProjectGeography(selectedId) : Promise.resolve(null)),
    [selectedId]
  );

  const allLocations = getAllLocations(); // legacy — see file header

  // Hooks-order fix: everything the useMemo below needs, and the useMemo
  // itself, must run on every render — i.e. before the loading/error early
  // returns. None of these inputs depend on the overview/risk responses.
  const selectedLocation = selectedId ? getLocationByProject(selectedId) : undefined;
  const selectedNearby = selectedGeo.data?.nearby_projects ?? [];
  const nearbyRelatedIds = new Set(selectedNearby.map((r) => r.project_id));

  // Overview mode: all 200 projects, uniformly muted, full-country span.
  // Focused mode (a project selected): zoom to the selected project + its
  // nearby-related projects only, so the relationship is actually legible.
  const focusLocations = useMemo(() => {
    if (!selectedId || !selectedLocation) return allLocations;
    const related = allLocations.filter((l) => nearbyRelatedIds.has(l.projectId));
    return [selectedLocation, ...related];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedLocation, selectedNearby, allLocations]);

  const loading = overview.loading || riskResults.loading;
  const error = overview.error || riskResults.error;

  if (error) return <ErrorBlock message={error} />;
  if (loading || !overview.data || !riskResults.data) return <LoadingBlock label="Loading geographic intelligence…" />;

  const nearby = overview.data.nearby_relationships;
  const duplicateLike = overview.data.duplicate_like_matches;
  const clusters = overview.data.clusters;
  const radiusKm = overview.data.radius_km;
  const riskByProjectId = new Map(riskResults.data.map((r) => [r.project_id, r]));

  const states = Array.from(new Set(allLocations.map((l) => l.state))).sort();

  const selectedProject = selectedId ? getProjectById(selectedId) : undefined;
  const selectedClusterId = selectedGeo.data?.cluster_id ?? null;
  const selectedDuplicates = selectedGeo.data?.duplicate_like_matches ?? [];
  const selectedRisk = selectedId ? riskByProjectId.get(selectedId) : undefined;

  const project = buildProjector(focusLocations, selectedId ? 0.35 : 0.05, selectedId ? 0.03 : 0.5);

  const nearbyEnriched = nearby.map((r) => ({
    rel: r,
    sourceLoc: getLocationByProject(r.source),
    targetLoc: getLocationByProject(r.target),
    sourceProject: getProjectById(r.source),
    targetProject: getProjectById(r.target),
  }));

  const filteredNearby = nearbyEnriched.filter(({ rel, sourceLoc, targetLoc }) => {
    const q = search.toLowerCase();
    const matchSearch = !q || rel.source.toLowerCase().includes(q) || rel.target.toLowerCase().includes(q);
    const matchState = stateFilter === "All" || sourceLoc?.state === stateFilter || targetLoc?.state === stateFilter;
    const matchContractor = sameContractorFilter === "All" || (sameContractorFilter === "Yes") === rel.same_contractor;
    const matchWorkType = sameWorkTypeFilter === "All" || (sameWorkTypeFilter === "Yes") === rel.same_work_type;
    return matchSearch && matchState && matchContractor && matchWorkType;
  });

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>Geographic Intelligence</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>Identify spatial relationships, nearby projects and geographic patterns across monitored works.</p>
        <p style={{ fontSize: "0.68rem", color: "#9ca3af", marginTop: "0.3rem", fontStyle: "italic" }}>{overview.data.disclaimer} Geographic proximity alone is never treated as an anomaly.</p>
      </div>

      {/* Overview cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {[
          { label: "Projects Mapped", value: allLocations.length },
          { label: "Nearby Project Pairs", value: nearby.length },
          { label: "Geographic Clusters", value: clusters.length },
          { label: "Potential Duplicate-like Matches", value: duplicateLike.length },
        ].map((c) => (
          <div key={c.label} style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.75rem 1rem", borderTop: "2px solid #1c3557" }}>
            <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.3rem" }}>{c.label}</div>
            <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "#1c3557", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Geographic Visualization: map (spatial context) + project detail, always visible */}
      <div style={{ marginBottom: "0.5rem" }}>
        <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif" }}>Geographic Visualization</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "440px 1fr", gap: "0.75rem", marginBottom: "1.25rem", alignItems: "start" }}>
        {/* Map — reasonably sized, not page-dominating; focuses on the selection */}
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.65rem" }}>
          <div style={{ fontSize: "0.62rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: "0.4rem" }}>
            {selectedId ? `Geographic Focus — ${selectedId}` : "All Monitored Locations (overview)"}
          </div>
          <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} style={{ width: "100%", background: "#f0f4f0", border: "1px solid #d1d5db", borderRadius: 3, overflow: "hidden" }}>
            {/* relationship lines, drawn under markers */}
            {selectedId && selectedLocation && selectedNearby.map((r, i) => {
              const otherLoc = getLocationByProject(r.project_id);
              if (!otherLoc) return null;
              const a = project(selectedLocation.latitude, selectedLocation.longitude);
              const b = project(otherLoc.latitude, otherLoc.longitude);
              return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={COLOR_LINE} strokeWidth={1.2} strokeDasharray="3 2" />;
            })}

            {/* markers: all 200 shown; muted overview when nothing selected,
                selected + its nearby relationships highlighted otherwise */}
            {allLocations.map((loc) => {
              const { x, y } = project(loc.latitude, loc.longitude);
              const isSelected = loc.projectId === selectedId;
              const isNearby = nearbyRelatedIds.has(loc.projectId);
              const isFocusRelevant = !selectedId || isSelected || isNearby;
              if (selectedId && !isFocusRelevant) return null; // outside the focused view's bounding box
              const color = isSelected ? COLOR_SELECTED : isNearby ? COLOR_NEARBY : COLOR_MUTED;
              const radius = isSelected ? 7 : isNearby ? 5.5 : 2.5;
              return (
                <g key={loc.projectId} transform={`translate(${x},${y})`}
                  onClick={() => setSelectedId(selectedId === loc.projectId ? null : loc.projectId)}
                  style={{ cursor: "pointer" }}>
                  <circle r={radius} fill={color} stroke="#fff" strokeWidth={isSelected ? 1.5 : 1} opacity={isSelected || isNearby ? 0.95 : 0.8} />
                  {(isSelected || isNearby) && (
                    <text y={-11} textAnchor="middle" fontSize={8.5} fontWeight={700} fill="#1c3557" fontFamily="'JetBrains Mono', monospace">{loc.projectId}</text>
                  )}
                </g>
              );
            })}
          </svg>

          {/* Legend */}
          <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.5rem", flexWrap: "wrap", fontSize: "0.6rem", color: "#4b5563" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: COLOR_SELECTED, display: "inline-block" }} /> Selected project
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: COLOR_NEARBY, display: "inline-block" }} /> Nearby related project
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: COLOR_MUTED, display: "inline-block" }} /> Other monitored project
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
              <span style={{ width: 14, height: 0, borderTop: `1.2px dashed ${COLOR_LINE}`, display: "inline-block" }} /> Geographic relationship
            </div>
          </div>
        </div>

        {/* Project detail */}
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "0.9rem 1rem" }}>
          {!selectedId || !selectedProject ? (
            <div style={{ fontSize: "0.72rem", color: "#9ca3af", textAlign: "center", padding: "1.5rem 0" }}>Select a project on the map or in the table below to see its geographic context.</div>
          ) : (
            <>
              <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: "0.5rem" }}>Project Detail</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 1.5rem" }}>
                <div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: "#1c3557", fontSize: "0.85rem", marginBottom: "0.2rem" }}>{selectedId}</div>
                  <div style={{ fontSize: "0.72rem", color: "#374151", marginBottom: "0.6rem", lineHeight: 1.4 }}>{selectedProject.projectDescription}</div>
                  {[
                    ["Work Type", selectedProject.workType],
                    ["District", selectedLocation?.district ?? "—"],
                    ["State", selectedLocation?.state ?? "—"],
                    ["Value", formatINR(selectedProject.sanctionedAmount)],
                    ["Lat/Lng", selectedLocation ? `${selectedLocation.latitude}°, ${selectedLocation.longitude}°` : "—"],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", borderBottom: "1px solid #f3f4f6", padding: "0.2rem 0" }}>
                      <span style={{ color: "#9ca3af" }}>{k}</span>
                      <span style={{ color: "#1f2937", fontWeight: 500 }}>{v}</span>
                    </div>
                  ))}
                </div>

                <div>
                  <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: "0.4rem" }}>
                    Geographic Context ({radiusKm} km radius)
                  </div>
                  {selectedGeo.loading ? (
                    <LoadingBlock label="Loading…" />
                  ) : selectedGeo.error ? (
                    <ErrorBlock message={selectedGeo.error} />
                  ) : selectedNearby.length === 0 ? (
                    <div style={{ fontSize: "0.68rem", color: "#9ca3af" }}>No nearby projects within {radiusKm} km.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginBottom: "0.5rem" }}>
                      {selectedNearby.map((r, i) => (
                        <div key={i} style={{ fontSize: "0.68rem", color: "#374151", padding: "0.3rem 0.5rem", background: "#fdf6ec", borderRadius: 3, border: "1px solid #f5e2c2" }}>
                          <strong style={{ fontFamily: "'JetBrains Mono', monospace", color: COLOR_NEARBY }}>{r.project_id}</strong> — {r.distance_km.toFixed(2)} km, {r.explanation}
                        </div>
                      ))}
                    </div>
                  )}
                  {selectedClusterId && (
                    <div style={{ fontSize: "0.68rem", color: "#374151", marginBottom: "0.5rem" }}>
                      Member of geographic cluster <strong>{selectedClusterId}</strong>.
                    </div>
                  )}
                  {selectedDuplicates.length > 0 && (
                    <div style={{ fontSize: "0.68rem", color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 3, padding: "0.4rem 0.5rem", marginBottom: "0.5rem" }}>
                      Involved in {selectedDuplicates.length} potential duplicate-like match{selectedDuplicates.length > 1 ? "es" : ""} — requires human verification, not a confirmed duplicate.
                    </div>
                  )}

                  <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#6b7280", letterSpacing: "0.06em", textTransform: "uppercase", margin: "0.6rem 0 0.4rem", borderTop: "1px solid #eef0f3", paddingTop: "0.5rem" }}>
                    Stage 4 Risk (informational — separate from geographic context)
                  </div>
                  {selectedRisk ? (
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: "0.85rem", color: RISK_LEVEL_COLOR[selectedRisk.risk_level] }}>{selectedRisk.risk_score}</span>
                      <span style={{ fontSize: "0.62rem", fontWeight: 700, padding: "1px 6px", borderRadius: 2, background: "#f3f4f6", color: RISK_LEVEL_COLOR[selectedRisk.risk_level] }}>{selectedRisk.risk_level}</span>
                    </div>
                  ) : (
                    <div style={{ fontSize: "0.68rem", color: "#9ca3af" }}>No Stage 4 risk result recorded.</div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Nearby project relationships — precise evidence view */}
      <div style={{ marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif" }}>Nearby Project Relationships</div>
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by project ID..."
            style={{ padding: "0.4rem 0.65rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, outline: "none", fontFamily: "inherit", width: 220, background: "#fff" }} />
          <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}
            style={{ padding: "0.4rem 0.55rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
            <option value="All">All States</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={sameContractorFilter} onChange={(e) => setSameContractorFilter(e.target.value as ContractorFilter)}
            style={{ padding: "0.4rem 0.55rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
            <option value="All">Same Contractor: Any</option>
            <option value="Yes">Same Contractor: Yes</option>
            <option value="No">Same Contractor: No</option>
          </select>
          <select value={sameWorkTypeFilter} onChange={(e) => setSameWorkTypeFilter(e.target.value as ContractorFilter)}
            style={{ padding: "0.4rem 0.55rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff", cursor: "pointer" }}>
            <option value="All">Same Work Type: Any</option>
            <option value="Yes">Same Work Type: Yes</option>
            <option value="No">Same Work Type: No</option>
          </select>
          <span style={{ fontSize: "0.7rem", color: "#9ca3af", marginLeft: "auto" }}>{filteredNearby.length} of {nearby.length} pairs</span>
        </div>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Project</th><th>Related Project</th><th>Distance</th><th>Work Type</th><th>District</th><th>Relationship Context</th>
              </tr>
            </thead>
            <tbody>
              {filteredNearby.slice(0, 60).map(({ rel, sourceProject, targetProject, sourceLoc }, i) => (
                <tr key={i}
                  onClick={() => setSelectedId(selectedId === rel.source ? null : rel.source)}
                  style={{ cursor: "pointer", background: selectedId === rel.source ? "#eef3fb" : undefined }}>
                  <td>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{rel.source}</span>
                    <div style={{ fontSize: "0.65rem", color: "#9ca3af", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sourceProject?.projectDescription}</div>
                  </td>
                  <td>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>{rel.target}</span>
                    <div style={{ fontSize: "0.65rem", color: "#9ca3af", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{targetProject?.projectDescription}</div>
                  </td>
                  <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem" }}>{rel.distance_km.toFixed(2)} km</span></td>
                  <td style={{ fontSize: "0.72rem", color: rel.same_work_type ? "#374151" : "#9ca3af" }}>{sourceProject?.workType ?? "—"}{rel.same_work_type ? " (shared)" : ""}</td>
                  <td style={{ fontSize: "0.72rem" }}>{sourceLoc?.district ?? "—"}</td>
                  <td style={{ fontSize: "0.68rem", color: "#4b5563", maxWidth: 260 }}>{rel.explanation}</td>
                </tr>
              ))}
              {filteredNearby.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: "1.25rem", color: "#9ca3af", fontSize: "0.78rem" }}>No nearby relationships match the current filters.</td></tr>
              )}
            </tbody>
          </table>
          {filteredNearby.length > 60 && (
            <div style={{ padding: "0.5rem 0.75rem", fontSize: "0.68rem", color: "#9ca3af", borderTop: "1px solid #eef0f3" }}>
              Showing first 60 of {filteredNearby.length} matching pairs. Narrow the filters to see more.
            </div>
          )}
        </div>
      </div>

      {/* Potential duplicate-like matches */}
      <div style={{ marginBottom: "1.25rem" }}>
        <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", marginBottom: "0.3rem" }}>Potential Duplicate-like Matches</div>
        <p style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "0.6rem" }}>These matches satisfy the Stage 5A geographic similarity criteria and require human verification.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "0.6rem" }}>
          {duplicateLike.map((m, i) => {
            const pa = getProjectById(m.project_a), pb = getProjectById(m.project_b);
            return (
              <div key={i} style={{ background: "#fff", border: "1px solid #fde68a", borderRadius: 3, padding: "0.7rem 0.85rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.35rem" }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: "#1c3557", fontSize: "0.78rem" }}>{m.project_a} ↔ {m.project_b}</span>
                  <span style={{ fontSize: "0.65rem", color: "#b45309", fontWeight: 700 }}>{m.distance_km.toFixed(2)} km</span>
                </div>
                <div style={{ fontSize: "0.68rem", color: "#4b5563", marginBottom: "0.4rem" }}>{pa?.projectDescription} / {pb?.projectDescription}</div>
                <div style={{ display: "flex", gap: "0.75rem", fontSize: "0.65rem", color: "#6b7280", marginBottom: "0.4rem" }}>
                  <span>Description similarity: {(m.description_similarity * 100).toFixed(0)}%</span>
                  <span>Cost similarity: {m.cost_similarity !== null ? `${(m.cost_similarity * 100).toFixed(0)}%` : "—"}</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginBottom: "0.4rem" }}>
                  {m.shared_attributes.map((a) => (
                    <span key={a} style={{ fontSize: "0.6rem", padding: "1px 6px", borderRadius: 2, background: "#fffbeb", color: "#92400e", border: "1px solid #fde68a" }}>{a}</span>
                  ))}
                </div>
                <div style={{ fontSize: "0.65rem", color: "#92400e", fontStyle: "italic" }}>Requires review — not a confirmed duplicate.</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Geographic clusters */}
      <div>
        <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", marginBottom: "0.3rem" }}>Geographic Clusters</div>
        <p style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "0.6rem" }}>Shared spatial patterns within the {radiusKm} km radius. Cluster membership requires contextual review — it does not itself indicate wrongdoing.</p>
        <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr><th>Cluster</th><th>Projects</th><th>Radius</th><th>Common Work Types</th><th>Shared Contractors</th></tr>
            </thead>
            <tbody>
              {clusters.map((c) => (
                <tr key={c.cluster_id}>
                  <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem", fontWeight: 600, color: "#1c3557" }}>{c.cluster_id}</span></td>
                  <td>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", fontWeight: 600 }}>{c.project_count}</span>
                    <div style={{ fontSize: "0.63rem", color: "#9ca3af", maxWidth: 280, whiteSpace: "normal" }}>
                      {c.project_ids.slice(0, 8).join(", ")}{c.project_ids.length > 8 ? ` +${c.project_ids.length - 8} more` : ""}
                    </div>
                  </td>
                  <td><span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.72rem" }}>{c.radius_km} km</span></td>
                  <td style={{ fontSize: "0.7rem", color: "#4b5563", maxWidth: 220 }}>{c.common_work_types.join(", ") || "—"}</td>
                  <td style={{ fontSize: "0.7rem", color: "#4b5563" }}>
                    {c.shared_contractors.length === 0 ? "—" : c.shared_contractors.map((cid) => getContractorById(cid)?.contractorName ?? cid).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}