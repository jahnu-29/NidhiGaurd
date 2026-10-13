// Stage 6.6 — which pages each role sees in the UI.
//
// This is a UX convenience only (it hides navigation a role cannot use).
// The real enforcement is on the backend: every /api route checks the
// signed-in user's role and answers 403 regardless of what the UI shows.
// Keep this table in step with backend/app/api/routes/__init__.py.

import type { Role } from "@/api/types";
import type { Page } from "@/components/Layout";

export const ROLE_PAGES: Record<Role, readonly Page[]> = {
  Administrator: ["dashboard", "projects", "risk-analysis", "contractors", "geographic", "investigation-queue", "reports", "users"],
  Investigator: ["dashboard", "projects", "risk-analysis", "contractors", "geographic", "investigation-queue", "reports"],
  Viewer: ["dashboard", "projects", "risk-analysis", "reports"],
};

export function canAccessPage(role: Role, page: Page): boolean {
  return ROLE_PAGES[role].includes(page);
}

/** Investigator and Administrator can open a project's investigation view; Viewer cannot. */
export function canInvestigate(role: Role): boolean {
  return role === "Administrator" || role === "Investigator";
}
