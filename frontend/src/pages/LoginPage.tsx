import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "@/lib/auth";
import { useAuthStore } from "@/app/stores/authStore";

export function LoginPage() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const setUser = useAuthStore((s) => s.setUser);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await login(username, password);
      setUser(user);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(150deg, #08323d 0%, #0a5c6a 55%, #0d7a8c 100%)",
      }}
    >
      <form
        onSubmit={onSubmit}
        style={{
          background: "#fff",
          borderRadius: "14px",
          padding: "2.4rem 2.6rem",
          width: 380,
          boxShadow: "0 12px 40px rgba(0,0,0,.25)",
        }}
      >
        <h1 style={{ fontSize: "1.4rem", marginBottom: "0.3rem", color: "var(--color-ink)" }}>PharmaReg</h1>
        <p style={{ color: "var(--color-muted)", fontSize: "0.88rem", marginBottom: "1.6rem" }}>
          制药合规知识平台
        </p>
        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="username">用户名</label>
          <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div style={{ marginBottom: "1.2rem" }}>
          <label htmlFor="password">密码</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        {error && (
          <p style={{ color: "var(--color-severity-critical)", fontSize: "0.85rem", marginBottom: "0.8rem" }}>{error}</p>
        )}
        <button type="submit" className="btn-primary" style={{ width: "100%", padding: "0.6rem" }} disabled={busy}>
          {busy ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}
