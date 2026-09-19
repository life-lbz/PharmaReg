import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatCards } from "@/components/common/StatCards";

interface AuditLogRow {
  id: number;
  event_type: string;
  actor_id: number | null;
  action: string;
  object_type: string | null;
  object_id: number | null;
  after: Record<string, unknown> | null;
  created_at: string | null;
  hash: string | null;
}

interface NotificationRow {
  id: number;
  type: string;
  title: string;
  payload: Record<string, unknown> | null;
  status: string;
}

export function SystemPage() {
  const [tab, setTab] = useState<"audit" | "notify">("audit");

  const auditLogs = useQuery({
    queryKey: ["auditLogs"],
    queryFn: () =>
      api.get("/sys/audit-logs?page=1&page_size=50").then((d) => (d as { items: AuditLogRow[] }).items),
    enabled: tab === "audit",
  });

  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: () =>
      api.get("/sys/notifications?page=1&page_size=50").then((d) => (d as { items: NotificationRow[] }).items),
    enabled: tab === "notify",
  });

  const fmtTime = (iso: string | null) => {
    if (!iso) return "-";
    try {
      return new Date(iso).toLocaleString("zh-CN");
    } catch {
      return iso;
    }
  };

  return (
    <div>
      <h1 style={{ marginBottom: "1rem" }}>系统与审计</h1>
      <div style={{ display: "flex", gap: "0.6rem", marginBottom: "1rem" }}>
        <button className={tab === "audit" ? "btn-primary" : ""} onClick={() => setTab("audit")}>
          审计日志（哈希链）
        </button>
        <button className={tab === "notify" ? "btn-primary" : ""} onClick={() => setTab("notify")}>
          通知中心
        </button>
      </div>

      {tab === "audit" && (
        <>
          <StatCards
            stats={[
              { label: "审计记录数", value: auditLogs.data?.length ?? 0 },
              { label: "哈希链状态", value: "校验中", tone: "ok" },
            ]}
          />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>事件</th>
                  <th>操作者</th>
                  <th>对象</th>
                  <th>动作</th>
                </tr>
              </thead>
              <tbody>
                {!auditLogs.data && (
                  <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td></tr>
                )}
                {(auditLogs.data ?? []).map((log) => (
                  <tr key={log.id}>
                    <td style={{ fontSize: "0.8rem" }}>{fmtTime(log.created_at)}</td>
                    <td><code>{log.event_type}</code></td>
                    <td>{log.actor_id ?? "system"}</td>
                    <td>{log.object_type}:{log.object_id ?? "-"}</td>
                    <td>{log.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "notify" && (
        <div style={{ display: "grid", gap: "0.6rem" }}>
          {!notifications.data && <p style={{ color: "var(--color-muted)" }}>加载中…</p>}
          {(notifications.data ?? []).map((n) => (
            <div
              key={n.id}
              style={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-rule)",
                borderRadius: "10px",
                padding: "0.8rem 1rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <span className="badge badge-active">{n.type}</span>
                <span style={{ marginLeft: "0.6rem" }}>{n.title}</span>
              </div>
              <span className={`badge ${n.status === "read" ? "badge-muted" : "badge-pending"}`}>
                {n.status === "read" ? "已读" : "未读"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
