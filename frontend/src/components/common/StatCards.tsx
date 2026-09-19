export interface StatCardDef {
  label: string;
  value: number | string;
  hint?: string;
  tone?: "default" | "warn" | "danger" | "ok";
}

export function StatCards({ stats }: { stats: StatCardDef[] }) {
  const toneColor: Record<string, string> = {
    default: "var(--color-primary)",
    warn: "var(--color-warning)",
    danger: "var(--color-severity-critical)",
    ok: "var(--color-state-done)",
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.8rem", marginBottom: "1.2rem" }}>
      {stats.map((s, i) => (
        <div
          key={i}
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-rule)",
            borderRadius: "10px",
            padding: "0.8rem 1rem",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: "1.4rem", fontWeight: 700, fontFamily: "var(--font-mono)", color: toneColor[s.tone ?? "default"] }}>
            {s.value}
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-muted)" }}>{s.label}</div>
          {s.hint && <div style={{ fontSize: "0.7rem", color: "var(--color-warning)", marginTop: "0.15rem" }}>{s.hint}</div>}
        </div>
      ))}
    </div>
  );
}
