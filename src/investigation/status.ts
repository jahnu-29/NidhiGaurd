// V2.6 — shared labels/colours for the investigation workflow status.
//
// Investigation status is WORKFLOW state chosen by a human investigator. It is
// deliberately styled apart from risk levels (which use red/amber/green) and
// never reinterprets or replaces the risk level.

import type { InvestigationStatus } from "@/api/types";

export const INVESTIGATION_STATUSES: readonly InvestigationStatus[] = [
  "NEW",
  "UNDER_REVIEW",
  "REQUIRES_FURTHER_INVESTIGATION",
  "REVIEWED_NO_CONCERN",
  "ESCALATED",
];

export const STATUS_LABEL: Record<InvestigationStatus, string> = {
  NEW: "New",
  UNDER_REVIEW: "Under Review",
  REQUIRES_FURTHER_INVESTIGATION: "Requires Further Investigation",
  REVIEWED_NO_CONCERN: "Reviewed — No Concern",
  ESCALATED: "Escalated",
};

export const STATUS_STYLE: Record<InvestigationStatus, { bg: string; color: string; border: string }> = {
  NEW: { bg: "#f3f4f6", color: "#374151", border: "#d1d5db" },
  UNDER_REVIEW: { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
  REQUIRES_FURTHER_INVESTIGATION: { bg: "#f5f3ff", color: "#6d28d9", border: "#ddd6fe" },
  REVIEWED_NO_CONCERN: { bg: "#f0fdf4", color: "#15803d", border: "#bbf7d0" },
  ESCALATED: { bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" },
};

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}
