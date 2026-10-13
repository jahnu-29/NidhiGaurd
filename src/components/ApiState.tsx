// Stage 6.5 — shared loading/error presentation for API-backed pages.
// Plain blocks in the existing palette (navy/grey/red) — no new visual style.

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div style={{ padding: "3rem", textAlign: "center", color: "#6b7280", fontSize: "0.85rem" }}>
      {label}
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      style={{
        background: "#fef2f2",
        border: "1px solid #fecaca",
        borderRadius: 3,
        padding: "1.25rem 1.5rem",
        color: "#b91c1c",
        fontSize: "0.85rem",
        maxWidth: 560,
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: "0.25rem" }}>Unable to load data</div>
      <div>{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginTop: "0.75rem",
            background: "#1c3557",
            color: "#fff",
            border: "none",
            borderRadius: 3,
            padding: "0.4rem 0.9rem",
            fontSize: "0.75rem",
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}
