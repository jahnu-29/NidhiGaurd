// Stage 6.5 (+ Stage 6.6 auth) — the one place the frontend knows the FastAPI backend's base
// URL and how to call it. No page should hardcode a URL or call fetch()
// directly against the backend; everything goes through the functions below.
//
// Base URL resolution: VITE_API_BASE_URL (set in a .env file) if provided,
// otherwise http://127.0.0.1:8000 — the same address Stage 6.4's backend
// runs on by default — so a fresh checkout works with zero setup.

import type {
  ContractorDetail,
  ContractorSummary,
  DashboardSummaryResponse,
  InvestigationQueueResponse,
  ProjectDetail,
  ProjectGeographyResponse,
  ProjectRelationshipsResponse,
  ProjectRiskResponse,
  ProjectSummary,
  RiskResultSummary,
  GeographyOverviewResponse,
  AuthUser,
  LoginResponse,
  Role,
  UserRecord,
} from "./types";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

/** Raised for both network failures and non-2xx HTTP responses, so every
 * page can catch one error type regardless of what went wrong. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ------------------------------------------------------ session storage --
// Stage 6.6 — the access token lives in sessionStorage (cleared when the tab
// closes, never sent anywhere but this backend). The user's *role* is never
// read from storage: it always comes from GET /api/auth/me, so editing
// storage cannot grant anything. The backend is the real security boundary.

const TOKEN_KEY = "nidhiguard.access_token";

export function getStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode etc.) — the session simply won't survive a reload */
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** AuthProvider registers this so any protected request that comes back 401 ends the session. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  /** Login itself must not be treated as an "expired session" when it returns 401. */
  isLogin?: boolean;
}

async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    // Network-level failure: backend unreachable, not running, CORS block, etc.
    throw new ApiError("Unable to load NidhiGuard data. Please ensure the backend server is running.");
  }

  if (!response.ok) {
    if (response.status === 401) {
      if (options.isLogin) throw new ApiError("Invalid username or password.", 401);
      unauthorizedHandler?.();
      throw new ApiError("Your session has ended. Please sign in again.", 401);
    }
    if (response.status === 403) {
      throw new ApiError("Your role does not permit access to this information.", 403);
    }
    if (response.status === 404) {
      throw new ApiError("The requested record was not found.", 404);
    }
    if (response.status === 400 || response.status === 409) {
      // Backend rule violations (e.g. "cannot change your own role") carry a readable message.
      try {
        const detail = (await response.json())?.detail;
        if (typeof detail === "string") throw new ApiError(detail, response.status);
      } catch (e) {
        if (e instanceof ApiError) throw e;
      }
    }
    throw new ApiError("Unable to load NidhiGuard data. Please ensure the backend server is running.", response.status);
  }

  return (await response.json()) as T;
}

// ------------------------------------------------------------------ auth --

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/auth/login", { method: "POST", body: { username, password }, isLogin: true });
}

export function getCurrentUser(): Promise<AuthUser> {
  return apiFetch<AuthUser>("/api/auth/me");
}

export function logoutRequest(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" });
}

// ------------------------------------------------------- user management --

export function getUsers(): Promise<UserRecord[]> {
  return apiFetch<UserRecord[]>("/api/users");
}

export function updateUser(userId: number, changes: { role?: Role; is_active?: boolean }): Promise<UserRecord> {
  return apiFetch<UserRecord>(`/api/users/${userId}`, { method: "PATCH", body: changes });
}

// ------------------------------------------------------------- projects --

export function getProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/api/projects");
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function getProjectRisk(projectId: string): Promise<ProjectRiskResponse> {
  return apiFetch<ProjectRiskResponse>(`/api/projects/${encodeURIComponent(projectId)}/risk`);
}

/** All 200 projects' risk summaries in one request — see RiskResultSummary. */
export function getRiskResults(): Promise<RiskResultSummary[]> {
  return apiFetch<RiskResultSummary[]>("/api/risk-results");
}

export function getProjectRelationships(projectId: string): Promise<ProjectRelationshipsResponse> {
  return apiFetch<ProjectRelationshipsResponse>(`/api/projects/${encodeURIComponent(projectId)}/relationships`);
}

export function getProjectGeography(projectId: string): Promise<ProjectGeographyResponse> {
  return apiFetch<ProjectGeographyResponse>(`/api/projects/${encodeURIComponent(projectId)}/geography`);
}

/** Dataset-wide geography (all nearby pairs, clusters, duplicate-like matches) — see GeographyOverviewResponse. */
export function getGeographyOverview(): Promise<GeographyOverviewResponse> {
  return apiFetch<GeographyOverviewResponse>("/api/geography");
}

// ----------------------------------------------------------- contractors --

export function getContractors(): Promise<ContractorSummary[]> {
  return apiFetch<ContractorSummary[]>("/api/contractors");
}

export function getContractor(contractorId: string): Promise<ContractorDetail> {
  return apiFetch<ContractorDetail>(`/api/contractors/${encodeURIComponent(contractorId)}`);
}

// ------------------------------------------------------------- dashboard --

export function getInvestigationQueue(): Promise<InvestigationQueueResponse> {
  return apiFetch<InvestigationQueueResponse>("/api/investigation-queue");
}

export function getDashboardSummary(): Promise<DashboardSummaryResponse> {
  return apiFetch<DashboardSummaryResponse>("/api/dashboard/summary");
}
