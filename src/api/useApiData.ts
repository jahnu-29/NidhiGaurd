// Stage 6.5 — a minimal fetch-on-mount hook shared by every migrated page.
// Deliberately not a new dependency: plain useState/useEffect, nothing else.

import { useEffect, useState } from "react";
import { ApiError } from "./client";

export interface ApiDataState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Calls `fetcher` on mount and whenever `deps` changes. Never leaves stale
 * data on screen next to a new error — a failed refetch clears `data` so a
 * migrated intelligence page can't silently show a previous (or generated)
 * result next to a "could not load" message.
 */
export function useApiData<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiDataState<T> {
  const [state, setState] = useState<ApiDataState<T>>({ data: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, loading: true, error: null });

    fetcher()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Unable to load NidhiGuard data. Please ensure the backend server is running.";
        setState({ data: null, loading: false, error: message });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
