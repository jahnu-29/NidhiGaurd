// V2.6 — Investigator review + audit history, shown on the Project Investigation page.
//
// Two different voices are kept visibly apart:
//   NidhiGuard   -> risk signal / anomaly evidence (computed elsewhere, shown read-only here)
//   Investigator -> investigation status / investigator note (recorded by a person)
//
// Nothing here computes or alters a risk score, and no text is generated about
// whether anything is fraudulent. Status changes and notes are sent to the
// backend, which enforces who may write; `canWrite` only decides whether the
// controls are drawn.

import { useState, type CSSProperties, type ReactNode } from "react";
import { addInvestigationNote, changeInvestigationStatus, getInvestigation, ApiError } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { InvestigationHistoryEntry, InvestigationResponse, InvestigationStatus } from "@/api/types";
import { INVESTIGATION_STATUSES, STATUS_LABEL, STATUS_STYLE, formatTimestamp } from "@/investigation/status";

const MAX_NOTE_LENGTH = 1000; // keep in step with backend/app/investigation/schemas.py

interface Props {
  projectId: string;
  riskScore: number;
  riskLevel: string;
  /** Investigator / Administrator. Purely a UX switch — the API refuses everyone else. */
  canWrite: boolean;
  /** Lets the page header mirror the current status without a second fetch. */
  onStatusKnown?: (status: InvestigationStatus) => void;
}

const LABEL: CSSProperties = {
  fontSize: "0.6rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: "0.25rem",
};

function Panel({ title, tone, children }: { title: string; tone: string; children: ReactNode }) {
  return (
    <div style={{ border: "1px solid #e5e7eb", borderTop: `3px solid ${tone}`, borderRadius: 3, padding: "0.85rem 1rem", background: "#fff" }}>
      <div style={{ fontSize: "0.62rem", fontWeight: 700, color: tone, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "0.6rem" }}>{title}</div>
      {children}
    </div>
  );
}

export function StatusBadge({ status, large = false }: { status: InvestigationStatus; large?: boolean }) {
  const st = STATUS_STYLE[status];
  return (
    <span style={{
      background: st.bg, color: st.color, border: `1px solid ${st.border}`, borderRadius: 2, fontWeight: 700,
      fontSize: large ? "0.75rem" : "0.65rem", padding: large ? "3px 10px" : "2px 7px", display: "inline-block", whiteSpace: "nowrap",
    }}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function HistoryItem({ entry }: { entry: InvestigationHistoryEntry }) {
  return (
    <li style={{ display: "grid", gridTemplateColumns: "9.5rem 1fr", gap: "0.75rem", padding: "0.6rem 0", borderTop: "1px solid #f1f2f4" }}>
      <div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.68rem", color: "#374151" }}>{formatTimestamp(entry.created_at)}</div>
        <div style={{ fontSize: "0.68rem", color: "#6b7280", marginTop: "0.1rem" }}>
          {entry.username} <span style={{ color: "#9ca3af" }}>({entry.user_role})</span>
        </div>
      </div>
      <div style={{ fontSize: "0.78rem", color: "#1f2937", minWidth: 0 }}>
        {entry.action === "STATUS_CHANGE" && entry.previous_status && entry.new_status ? (
          <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.68rem", color: "#6b7280" }}>Status changed</span>
            <StatusBadge status={entry.previous_status} />
            <span aria-hidden="true">→</span>
            <StatusBadge status={entry.new_status} />
          </span>
        ) : (
          <div>
            <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: "0.15rem" }}>Investigator note</div>
            {/* Rendered as plain text (React escapes it); the investigator's own words, verbatim. */}
            <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{entry.note}</div>
          </div>
        )}
      </div>
    </li>
  );
}

export default function InvestigationWorkflow({ projectId, riskScore, riskLevel, canWrite, onStatusKnown }: Props) {
  const loaded = useApiData<InvestigationResponse>(
    () => getInvestigation(projectId).then((r) => { onStatusKnown?.(r.status); return r; }),
    [projectId]
  );
  const [latest, setLatest] = useState<InvestigationResponse | null>(null);
  const [pendingStatus, setPendingStatus] = useState<InvestigationStatus | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loaded.loading) return <LoadingBlock label="Loading investigation workflow…" />;
  const state = latest && latest.project_id === projectId ? latest : loaded.data;
  if (loaded.error || !state) return <ErrorBlock message={loaded.error ?? "Unable to load the investigation workflow."} />;

  async function run(action: () => Promise<InvestigationResponse>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setLatest(next);
      onStatusKnown?.(next.status);
      after?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The action could not be saved. Nothing was recorded.");
    } finally {
      setBusy(false);
    }
  }

  const target = pendingStatus || state.status;
  const trimmedNote = note.trim();
  const noteTooLong = trimmedNote.length > MAX_NOTE_LENGTH;

  return (
    <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, padding: "1.1rem 1.25rem", marginBottom: "1.25rem", borderTop: "3px solid #4b5563" }}>
      <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#1c3557", letterSpacing: "0.07em", textTransform: "uppercase" }}>Investigator Review &amp; Audit History</div>
      <div style={{ fontSize: "0.7rem", color: "#6b7280", margin: "0.2rem 0 0.9rem" }}>
        Status and notes below are recorded by human investigators. They are not generated by NidhiGuard, and they do not change the risk score.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "0.9rem", marginBottom: "1rem" }}>
        <Panel title="NidhiGuard — risk signal" tone="#1c3557">
          <div style={LABEL}>Risk assessment</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "1.05rem", fontWeight: 700, color: "#1c3557" }}>
            {riskScore.toFixed(1)} — {riskLevel}
          </div>
          <div style={{ fontSize: "0.68rem", color: "#6b7280", marginTop: "0.4rem" }}>
            Risk score indicates anomaly signals and does not constitute a finding of fraud.
          </div>
        </Panel>

        <Panel title="Investigator — review status" tone="#4b5563">
          <div style={LABEL}>Current status</div>
          <StatusBadge status={state.status} large />
          {state.updated_at && (
            <div style={{ fontSize: "0.68rem", color: "#6b7280", marginTop: "0.4rem" }}>Last action {formatTimestamp(state.updated_at)}</div>
          )}
          {!canWrite && (
            <div style={{ fontSize: "0.68rem", color: "#6b7280", marginTop: "0.6rem" }}>Read-only: your role cannot change status or add notes.</div>
          )}
        </Panel>
      </div>

      {canWrite && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "0.9rem", marginBottom: "1rem" }}>
          <div>
            <label htmlFor="inv-status" style={LABEL}>Change investigation status</label>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <select
                id="inv-status"
                value={target}
                disabled={busy}
                onChange={(e) => setPendingStatus(e.target.value as InvestigationStatus)}
                style={{ flex: 1, padding: "0.4rem 0.5rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", background: "#fff" }}
              >
                {INVESTIGATION_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              </select>
              <button
                type="button"
                disabled={busy || target === state.status}
                onClick={() => run(() => changeInvestigationStatus(projectId, target as InvestigationStatus), () => setPendingStatus(""))}
                style={{
                  background: busy || target === state.status ? "#9ca3af" : "#1c3557", color: "#fff", border: "none", borderRadius: 3,
                  padding: "0.4rem 0.9rem", fontSize: "0.75rem", fontWeight: 600, cursor: busy || target === state.status ? "default" : "pointer", fontFamily: "inherit",
                }}
              >
                Update status
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="inv-note" style={LABEL}>Add investigator note — your own words, not an automated conclusion</label>
            <textarea
              id="inv-note"
              value={note}
              maxLength={MAX_NOTE_LENGTH + 200}
              disabled={busy}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="e.g. Project cost is above comparable projects; verification of estimate and work scope recommended."
              style={{ width: "100%", boxSizing: "border-box", padding: "0.45rem 0.55rem", fontSize: "0.78rem", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit", resize: "vertical" }}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.3rem" }}>
              <span style={{ fontSize: "0.65rem", color: noteTooLong ? "#b91c1c" : "#9ca3af" }}>{trimmedNote.length} / {MAX_NOTE_LENGTH}</span>
              <button
                type="button"
                disabled={busy || !trimmedNote || noteTooLong}
                onClick={() => run(() => addInvestigationNote(projectId, trimmedNote), () => setNote(""))}
                style={{
                  background: busy || !trimmedNote || noteTooLong ? "#9ca3af" : "#1c3557", color: "#fff", border: "none", borderRadius: 3,
                  padding: "0.4rem 0.9rem", fontSize: "0.75rem", fontWeight: 600, cursor: busy || !trimmedNote || noteTooLong ? "default" : "pointer", fontFamily: "inherit",
                }}
              >
                Add note
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 3, padding: "0.5rem 0.75rem", color: "#b91c1c", fontSize: "0.75rem", marginBottom: "0.9rem" }}>
          {error}
        </div>
      )}

      <div style={LABEL}>Investigation history ({state.history.length}) — oldest first, append-only</div>
      {state.history.length === 0 ? (
        <div style={{ fontSize: "0.75rem", color: "#9ca3af", padding: "0.5rem 0" }}>No investigator actions have been recorded for this project yet.</div>
      ) : (
        <ol data-testid="investigation-history" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {state.history.map((h) => <HistoryItem key={h.id} entry={h} />)}
        </ol>
      )}
    </div>
  );
}
