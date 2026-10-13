import { type ReactNode } from "react";
import type { Role } from "@/api/types";
import { canAccessPage } from "@/auth/permissions";

export type Page =
  | "dashboard"
  | "projects"
  | "risk-analysis"
  | "contractors"
  | "geographic"
  | "investigation-queue"
  | "reports"
  | "users";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: "⊟" },
  { id: "projects", label: "Projects", icon: "≡" },
  { id: "risk-analysis", label: "Risk Analysis", icon: "◈" },
  { id: "contractors", label: "Contractors", icon: "◉" },
  { id: "geographic", label: "Geographic Intelligence", icon: "⊕" },
  { id: "investigation-queue", label: "Investigation Queue", icon: "▣" },
  { id: "reports", label: "Reports", icon: "⊞" },
  { id: "users", label: "User Management", icon: "⚙" },
];

interface LayoutProps {
  page: Page;
  onNavigate: (p: Page) => void;
  children: ReactNode;
  username: string;
  role: Role;
  onLogout: () => void;
}

export default function Layout({ page, onNavigate, children, username, role, onLogout }: LayoutProps) {
  return (
    <div className="h-full flex flex-col" style={{ background: "#f4f5f7", fontFamily: "'Source Sans 3', sans-serif" }}>
      {/* Header */}
      <header style={{ background: "#1c3557", borderBottom: "3px solid #c41e3a" }}>
        <div className="flex items-center justify-between px-4 py-0" style={{ minHeight: 52 }}>
          <div className="flex items-center gap-3">
            {/* Shield logo */}
            <svg width="32" height="36" viewBox="0 0 32 36" fill="none" className="shrink-0">
              <path d="M16 1 L31 7 L31 20 Q31 30 16 35 Q1 30 1 20 L1 7 Z" fill="#234169" stroke="#3a639e" strokeWidth="1.5"/>
              <path d="M16 5 L27 10 L27 20 Q27 28 16 32 Q5 28 5 20 L5 10 Z" fill="#2d5184"/>
              <text x="16" y="23" textAnchor="middle" fill="#c8d9f0" fontSize="13" fontWeight="700" fontFamily="serif">N</text>
            </svg>
            <div>
              <div className="font-bold text-white" style={{ fontSize: "1.05rem", letterSpacing: "-0.01em", lineHeight: 1.2 }}>NidhiGuard</div>
              <div style={{ color: "#8aaed4", fontSize: "0.65rem", letterSpacing: "0.06em", textTransform: "uppercase" }}>MPLADS Intelligence &amp; Monitoring System</div>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right">
              <div style={{ color: "#8aaed4", fontSize: "0.65rem", letterSpacing: "0.05em", textTransform: "uppercase" }}>Signed in as</div>
              <div style={{ color: "#e2ecf9", fontSize: "0.8rem", fontWeight: 600 }}>{username} <span style={{ color: "#8aaed4", fontWeight: 500, fontSize: "0.7rem" }}>· {role}</span></div>
            </div>
            <button
              onClick={onLogout}
              style={{ background: "transparent", color: "#c8d9f0", border: "1px solid #3a639e", borderRadius: 3, fontSize: "0.7rem", fontWeight: 600, padding: "4px 12px", cursor: "pointer", letterSpacing: "0.04em", fontFamily: "inherit" }}
            >
              Sign Out
            </button>
            <div className="text-right" style={{ borderLeft: "1px solid #2d5184", paddingLeft: "1.25rem" }}>
              <div className="flex items-center gap-1.5 justify-end">
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#22c55e", display: "inline-block", flexShrink: 0 }} />
                <span style={{ color: "#a8cce8", fontSize: "0.7rem", fontWeight: 600 }}>System Status: Connected</span>
              </div>
              <div style={{ color: "#6b94c0", fontSize: "0.65rem" }}>Last Sync: 10 Sep 2026 | 13:45 IST</div>
            </div>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside style={{ width: 216, background: "#1a2f4a", display: "flex", flexDirection: "column", flexShrink: 0, overflowY: "auto" }}>
          <nav className="flex-1 py-3">
            {NAV.filter((n) => canAccessPage(role, n.id)).map((n) => {
              const active = page === n.id;
              return (
                <button
                  key={n.id}
                  onClick={() => onNavigate(n.id)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.6rem",
                    padding: "0.55rem 1rem",
                    fontSize: "0.8rem",
                    fontWeight: active ? 600 : 400,
                    color: active ? "#ffffff" : "#7ba3c8",
                    background: active ? "#234169" : "transparent",
                    borderLeft: active ? "3px solid #c41e3a" : "3px solid transparent",
                    textAlign: "left",
                    cursor: "pointer",
                    transition: "all 0.12s",
                    letterSpacing: "0.01em",
                  }}
                  onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = "#b8d3ed"; }}
                  onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = "#7ba3c8"; }}
                >
                  <span style={{ fontFamily: "monospace", fontSize: "0.85rem", opacity: 0.7 }}>{n.icon}</span>
                  {n.label}
                </button>
              );
            })}
          </nav>

          <div style={{ padding: "0.75rem 1rem", borderTop: "1px solid #263f5e" }}>
            <div className="flex items-center gap-1.5 mb-1">
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", display: "inline-block" }} />
              <span style={{ color: "#5a8cb0", fontSize: "0.65rem", fontWeight: 600 }}>Data Services Connected</span>
            </div>
            <div style={{ color: "#3d5f7a", fontSize: "0.6rem", fontWeight: 500, letterSpacing: "0.04em" }}>PROTOTYPE ENVIRONMENT</div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto" style={{ padding: "1.5rem 1.75rem" }}>
          {children}
        </main>
      </div>

      {/* Bottom disclaimer bar */}
      <div style={{ background: "#f0f3f8", borderTop: "1px solid #dde1e7", padding: "3px 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: "0.6rem", color: "#9ca3af", letterSpacing: "0.05em" }}>PROTOTYPE ENVIRONMENT — SYNTHETIC DEMONSTRATION DATA — NOT FOR OPERATIONAL USE</span>
        <span style={{ fontSize: "0.6rem", color: "#9ca3af" }}>Ministry of Statistics &amp; Programme Implementation | NidhiGuard v1.0</span>
      </div>
    </div>
  );
}
