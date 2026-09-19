import { Citation } from "@/lib/types";

export interface BubbleMsg {
  role: string;
  content: string;
  citations?: Citation[] | null;
  flags?: Record<string, unknown> | null;
  confidence?: number | null;
}

export interface BubbleProps {
  message: BubbleMsg;
  streaming?: boolean;
  onCitationClick?: (citation: Citation) => void;
}

export function MessageBubble({ message, streaming = false, onCitationClick }: BubbleProps) {
  const isUser = message.role === "user";
  const needsReview = Boolean(message.flags?.needs_human_review);

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: "0.9rem",
      }}
    >
      <div
        style={{
          maxWidth: "82%",
          padding: "0.6rem 0.9rem",
          borderRadius: "10px",
          background: isUser ? "#dfe7ee" : "var(--color-primary-soft)",
          border: needsReview && !isUser ? "1px dashed var(--color-warning)" : undefined,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {!isUser && needsReview && (
          <div
            className="badge badge-major"
            style={{ marginBottom: "0.35rem", display: "inline-block", background: "var(--color-warning-soft)" }}
          >
            待人工确认
          </div>
        )}
        <div style={needsReview && !isUser ? { opacity: 0.72 } : undefined}>{message.content}</div>
        {streaming && <span style={{ display: "inline-block", width: 8, height: 16, background: "var(--color-primary)", animation: "blink 1s infinite" }} />}
        {!isUser && message.confidence != null && (
          <div style={{ fontSize: "0.74rem", color: "var(--color-muted)", marginTop: "0.35rem" }}>
            置信度 {(message.confidence * 100).toFixed(0)}%
          </div>
        )}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div style={{ marginTop: "0.5rem", borderTop: "1px solid rgba(10,92,106,.15)", paddingTop: "0.35rem" }}>
            {message.citations.slice(0, 4).map((c, i) => (
              <button
                key={i}
                onClick={() => onCitationClick?.(c)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.3rem",
                  margin: "0.15rem 0.3rem 0 0",
                  padding: "0.15rem 0.5rem",
                  fontSize: "0.75rem",
                  background: "#fff",
                  border: "1px solid var(--color-rule)",
                  borderRadius: "999px",
                }}
              >
                {c.clause_no} · {c.collection}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function CitationPanel({ citations, onClose }: { citations: Citation[]; onClose?: () => void }) {
  return (
    <div
      style={{
        border: "1px solid var(--color-rule)",
        borderRadius: "10px",
        background: "var(--color-surface)",
        padding: "0.9rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <strong style={{ fontSize: "0.88rem" }}>引用依据</strong>
        {onClose && (
          <button className="btn-ghost" onClick={onClose} style={{ fontSize: "0.75rem" }}>
            关闭
          </button>
        )}
      </div>
      {citations.length === 0 && <div style={{ color: "var(--color-muted)", fontSize: "0.85rem" }}>无引用</div>}
      {citations.map((c, i) => (
        <div
          key={i}
          style={{
            borderLeft: "2px solid var(--color-primary)",
            padding: "0.4rem 0.6rem",
            margin: "0.4rem 0",
            background: "#f7fafb",
            borderRadius: "4px",
            fontSize: "0.82rem",
          }}
        >
          <strong>{c.clause_no}</strong>
          <span className="badge badge-muted" style={{ marginLeft: "0.4rem" }}>{c.collection}</span>
          <p style={{ color: "var(--color-muted)", marginTop: "0.2rem" }}>{c.excerpt}</p>
        </div>
      ))}
    </div>
  );
}
