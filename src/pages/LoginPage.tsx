import { useState } from "react";
import { useAuth } from "@/auth/AuthContext";

// Stage 6.6 — the single login page. One username/password form for every
// role; the backend decides the role after authentication. There is no
// sign-up or registration: accounts are created internally by administrators.

export default function LoginPage() {
  const { login, notice } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Please enter your username and password.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await login(username.trim(), password);
      // On success the AuthProvider flips to "authenticated" and App renders the application.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column", background: "#f4f5f7", fontFamily: "'Source Sans 3', sans-serif" }}>
      {/* Top bar */}
      <div style={{ background: "#1c3557", borderBottom: "3px solid #c41e3a", padding: "0.6rem 2rem", display: "flex", alignItems: "center", gap: "1rem" }}>
        <img src="https://upload.wikimedia.org/wikipedia/commons/5/55/Emblem_of_India.svg" alt="Emblem of India" style={{ height: 36, opacity: 0.9 }} />
        <div>
          <div style={{ color: "#e2ecf9", fontWeight: 700, fontSize: "0.95rem", letterSpacing: "0.02em" }}>Government of India</div>
          <div style={{ color: "#8aaed4", fontSize: "0.65rem", letterSpacing: "0.07em", textTransform: "uppercase" }}>Ministry of Statistics &amp; Programme Implementation</div>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "3rem 1rem" }}>
        <div style={{ width: "100%", maxWidth: 400 }}>
          {/* Logo + title */}
          <div style={{ textAlign: "center", marginBottom: "2rem" }}>
            <svg width="56" height="64" viewBox="0 0 32 36" fill="none" style={{ margin: "0 auto 1rem" }}>
              <path d="M16 1 L31 7 L31 20 Q31 30 16 35 Q1 30 1 20 L1 7 Z" fill="#1c3557" stroke="#3a639e" strokeWidth="1.5"/>
              <path d="M16 5 L27 10 L27 20 Q27 28 16 32 Q5 28 5 20 L5 10 Z" fill="#2d5184"/>
              <text x="16" y="23" textAnchor="middle" fill="#c8d9f0" fontSize="13" fontWeight="700" fontFamily="serif">N</text>
            </svg>
            <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "#1c3557", letterSpacing: "-0.02em", lineHeight: 1.1, fontFamily: "'Source Serif 4', serif" }}>NidhiGuard</div>
            <div style={{ fontSize: "0.78rem", color: "#4b6c8e", fontWeight: 500, marginTop: "0.25rem", letterSpacing: "0.02em" }}>MPLADS Intelligence &amp; Monitoring System</div>
            <div style={{ fontSize: "0.65rem", color: "#9ca3af", marginTop: "0.25rem", letterSpacing: "0.06em", textTransform: "uppercase" }}>Detect Early. Explain Clearly. Prioritise Intelligently.</div>
          </div>

          {/* Card */}
          <div style={{ background: "#fff", border: "1px solid #dde1e7", borderRadius: 4, padding: "2rem", boxShadow: "0 1px 4px rgba(0,0,0,0.07)" }}>
            <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#4b6c8e", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "1.25rem", borderBottom: "1px solid #eef0f3", paddingBottom: "0.75rem" }}>
              Authorized Access Only
            </div>

            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.72rem", fontWeight: 600, color: "#374151", marginBottom: "0.35rem", letterSpacing: "0.03em" }}>
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                  style={{
                    width: "100%", padding: "0.55rem 0.75rem", fontSize: "0.85rem",
                    border: "1px solid #d1d5db", borderRadius: 3, outline: "none",
                    fontFamily: "inherit", color: "#1f2937", background: "#fcfcfd",
                  }}
                />
              </div>
              <div style={{ marginBottom: "1.25rem" }}>
                <label style={{ display: "block", fontSize: "0.72rem", fontWeight: 600, color: "#374151", marginBottom: "0.35rem", letterSpacing: "0.03em" }}>
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  style={{
                    width: "100%", padding: "0.55rem 0.75rem", fontSize: "0.85rem",
                    border: "1px solid #d1d5db", borderRadius: 3, outline: "none",
                    fontFamily: "inherit", color: "#1f2937", background: "#fcfcfd",
                  }}
                />
              </div>
              {!error && notice && <div style={{ fontSize: "0.75rem", color: "#92400e", marginBottom: "0.75rem", padding: "0.4rem 0.6rem", background: "#fffbeb", borderRadius: 3 }}>{notice}</div>}
              {error && <div role="alert" style={{ fontSize: "0.75rem", color: "#dc2626", marginBottom: "0.75rem", padding: "0.4rem 0.6rem", background: "#fef2f2", borderRadius: 3 }}>{error}</div>}
              <button
                type="submit"
                disabled={loading}
                style={{
                  width: "100%", padding: "0.65rem", background: loading ? "#4b6c8e" : "#1c3557",
                  color: "#fff", border: "none", borderRadius: 3, fontSize: "0.85rem",
                  fontWeight: 600, cursor: loading ? "wait" : "pointer", letterSpacing: "0.04em",
                  fontFamily: "inherit", transition: "background 0.15s",
                }}
              >
                {loading ? "Signing in…" : "Sign In"}
              </button>
            </form>

            <div style={{ marginTop: "1rem", padding: "0.6rem 0.75rem", background: "#f8faff", border: "1px solid #dde8f5", borderRadius: 3 }}>
              <div style={{ fontSize: "0.65rem", color: "#4b6c8e", lineHeight: 1.6 }}>
                Accounts are issued internally. If you need access, contact your NidhiGuard administrator.
              </div>
            </div>
          </div>

          <div style={{ textAlign: "center", marginTop: "1.25rem", fontSize: "0.62rem", color: "#9ca3af" }}>
            Authorised access only. All activity is monitored and logged.<br />
            NidhiGuard v1.0 — Prototype Environment — Synthetic Demonstration Data
          </div>
        </div>
      </div>
    </div>
  );
}