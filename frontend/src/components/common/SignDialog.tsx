import { useState, type FormEvent } from "react";

export interface SignDialogProps {
  open: boolean;
  meaning: string;
  onConfirm: (pin: string) => Promise<void> | void;
  onClose: () => void;
}

export function SignDialog({ open, meaning, onConfirm, onClose }: SignDialogProps) {
  const [pin, setPin] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onConfirm(pin);
      setPin("");
      setConfirmed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "签名失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: "12px",
          padding: "1.6rem 1.8rem",
          width: 460,
          boxShadow: "0 10px 40px rgba(0,0,0,.2)",
        }}
      >
        <h3 style={{ marginBottom: "0.6rem" }}>电子签名确认</h3>
        <div
          style={{
            background: "var(--color-warning-soft)",
            border: "1px solid #e8c9b3",
            borderRadius: "8px",
            padding: "0.8rem 1rem",
            margin: "0.8rem 0",
            fontSize: "0.9rem",
          }}
        >
          <strong>签名承诺：</strong>
          {meaning}
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", margin: "0.8rem 0", fontSize: "0.9rem" }}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} style={{ width: "auto" }} />
          我已理解上述签名含义并确认执行
        </label>
        <div style={{ marginBottom: "0.9rem" }}>
          <label>签名口令</label>
          <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} autoComplete="off" />
        </div>
        {error && <p style={{ color: "var(--color-severity-critical)", fontSize: "0.85rem", marginBottom: "0.6rem" }}>{error}</p>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
          <button type="button" onClick={onClose}>取消</button>
          <button type="submit" className="btn-primary" disabled={!confirmed || !pin || busy}>
            {busy ? "签名中…" : "确认签名"}
          </button>
        </div>
      </form>
    </div>
  );
}
