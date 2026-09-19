import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/app/stores/authStore";
import { hasPermission, logout } from "@/lib/auth";

const NAV_ITEMS: { path: string; label: string; permission?: string; roles?: string[] }[] = [
  { path: "/qa", label: "规范问答", permission: "qa.ask" },
  // 方案A：培训认证中心仅考生角色（operator / crc）可见；培训管理台 trainer/admin 可见
  { path: "/training", label: "培训认证", roles: ["operator", "crc"] },
  { path: "/training/manage", label: "培训管理", roles: ["trainer", "admin"] },
  { path: "/deviation", label: "偏差处理", roles: ["qa", "qc", "engineer"] },
  { path: "/change", label: "变更控制", roles: ["qa", "compliance"] },
  { path: "/audit", label: "审计准备", roles: ["compliance", "qa", "cra"] },
  { path: "/sae", label: "SAE上报", roles: ["investigator", "pv", "cra", "crc"] },
  { path: "/kb", label: "法规库", roles: ["compliance"] },
  { path: "/sys", label: "系统审计", roles: ["admin", "compliance"] },
];

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();

  if (!user) return null;

  const visible = NAV_ITEMS.filter((item) => {
    if (item.roles && !item.roles.some((r) => user.roles.includes(r))) return false;
    if (item.permission && !hasPermission(user, item.permission)) return false;
    return true;
  });

  const onLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside
        style={{
          width: 200,
          background: "var(--color-primary)",
          color: "#eaf6f8",
          padding: "1.2rem 0.8rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.2rem",
          position: "sticky",
          top: 0,
          height: "100vh",
        }}
      >
        <div style={{ fontSize: "1.05rem", fontWeight: 700, padding: "0.3rem 0.6rem 1rem", letterSpacing: "0.02em" }}>
          PharmaReg
        </div>
        <nav style={{ display: "flex", flexDirection: "column", gap: "0.1rem", flex: 1 }}>
          {visible.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/training"}
              style={({ isActive }) => ({
                padding: "0.45rem 0.7rem",
                borderRadius: "6px",
                color: isActive ? "#fff" : "rgba(234,246,248,.75)",
                background: isActive ? "rgba(255,255,255,.14)" : "transparent",
                textDecoration: "none",
                fontSize: "0.92rem",
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div style={{ fontSize: "0.82rem", padding: "0.6rem", borderTop: "1px solid rgba(255,255,255,.18)" }}>
          <div style={{ opacity: 0.9 }}>{user.display_name}</div>
          <div style={{ opacity: 0.6, fontSize: "0.75rem", marginTop: "0.15rem" }}>
            {user.roles.join(" / ")}
          </div>
          <button
            onClick={onLogout}
            style={{
              marginTop: "0.6rem",
              background: "rgba(255,255,255,.1)",
              border: "none",
              color: "#eaf6f8",
              width: "100%",
            }}
          >
            退出登录
          </button>
        </div>
      </aside>
      <main style={{ flex: 1, padding: "1.5rem 2rem", minWidth: 0 }}>
        <Outlet />
      </main>
    </div>
  );
}
