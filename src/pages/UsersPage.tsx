// Stage 6.6 — minimal user management (Administrator only): list users,
// assign a role, enable/disable. No creation form, password reset, or
// anything else — accounts are issued internally (see backend/README_AUTH.md).

import { useState } from "react";
import { getUsers, updateUser } from "@/api/client";
import { useApiData } from "@/api/useApiData";
import { LoadingBlock, ErrorBlock } from "@/components/ApiState";
import type { Role, UserRecord } from "@/api/types";

const ROLES: Role[] = ["Administrator", "Investigator", "Viewer"];

interface Props {
  currentUserId: number;
}

export default function UsersPage({ currentUserId }: Props) {
  const [reloadKey, setReloadKey] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const users = useApiData<UserRecord[]>(getUsers, [reloadKey]);

  async function change(user: UserRecord, changes: { role?: Role; is_active?: boolean }) {
    setActionError(null);
    setBusyId(user.id);
    try {
      await updateUser(user.id, changes);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The change could not be saved.");
    } finally {
      setBusyId(null);
    }
  }

  if (users.error) return <ErrorBlock message={users.error} />;
  if (users.loading || !users.data) return <LoadingBlock label="Loading users…" />;

  return (
    <div>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#1c3557", fontFamily: "'Source Serif 4', serif", margin: 0 }}>User Management</h1>
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.2rem" }}>
          Assign roles and enable or disable accounts. Changes take effect on the user's next request.
        </p>
      </div>

      {actionError && (
        <div role="alert" style={{ fontSize: "0.75rem", color: "#dc2626", marginBottom: "0.75rem", padding: "0.5rem 0.75rem", background: "#fef2f2", borderRadius: 3 }}>
          {actionError}
        </div>
      )}

      <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 3, overflow: "hidden" }}>
        <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((u) => {
              const isSelf = u.id === currentUserId;
              const busy = busyId === u.id;
              return (
                <tr key={u.id}>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "#1c3557", fontWeight: 600 }}>
                    {u.username}{isSelf && <span style={{ color: "#9ca3af", fontWeight: 400 }}> (you)</span>}
                  </td>
                  <td>
                    <select
                      value={u.role}
                      disabled={isSelf || busy}
                      onChange={(e) => change(u, { role: e.target.value as Role })}
                      style={{ fontSize: "0.75rem", padding: "2px 6px", border: "1px solid #d1d5db", borderRadius: 3, fontFamily: "inherit" }}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    <span style={{ fontSize: "0.65rem", fontWeight: 700, padding: "2px 8px", borderRadius: 2, letterSpacing: "0.06em", color: "#fff", background: u.is_active ? "#16a34a" : "#6b7280" }}>
                      {u.is_active ? "ACTIVE" : "DISABLED"}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.72rem", color: "#6b7280" }}>{new Date(u.created_at).toLocaleDateString("en-IN")}</td>
                  <td>
                    <button
                      disabled={isSelf || busy}
                      onClick={() => change(u, { is_active: !u.is_active })}
                      style={{
                        background: isSelf ? "#9ca3af" : "#1c3557", color: "#fff", border: "none", borderRadius: 2,
                        fontSize: "0.68rem", fontWeight: 600, padding: "3px 10px", cursor: isSelf || busy ? "not-allowed" : "pointer",
                        letterSpacing: "0.04em", fontFamily: "inherit",
                      }}
                    >
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}