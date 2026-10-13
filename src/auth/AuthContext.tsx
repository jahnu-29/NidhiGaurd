// Stage 6.6 — minimal authentication state: plain React context, no state library.
//
// Knows: whether we're authenticated, the username and the role. The role is
// always obtained from the backend (login response / GET /api/auth/me), never
// from browser storage. Logout revokes the token server-side, then clears it
// locally, so protected API calls stop working immediately.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getCurrentUser,
  getStoredToken,
  login as loginRequest,
  logoutRequest,
  setStoredToken,
  setUnauthorizedHandler,
} from "@/api/client";
import type { AuthUser } from "@/api/types";

type Status = "checking" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: Status;
  user: AuthUser | null;
  /** Shown on the login page after an expired/revoked session. */
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(getStoredToken() ? "checking" : "anonymous");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const clearSession = useCallback(() => {
    setStoredToken(null);
    setUser(null);
    setStatus("anonymous");
  }, []);

  // Any protected request answered 401 (expired / revoked / deactivated) ends the session.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      setNotice("Your session has ended. Please sign in again.");
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  // Restore an existing session after a page reload by asking the backend who we are.
  useEffect(() => {
    if (status !== "checking") return;
    let cancelled = false;
    getCurrentUser()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!cancelled) clearSession();
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await loginRequest(username, password); // throws ApiError("Invalid username or password.")
    setStoredToken(result.access_token);
    setNotice(null);
    setUser(result.user);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest(); // revoke the token on the server
    } catch {
      /* even if the server can't be reached, the local session is still ended below */
    }
    setNotice(null);
    clearSession();
  }, [clearSession]);

  const value = useMemo(() => ({ status, user, notice, login, logout }), [status, user, notice, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
