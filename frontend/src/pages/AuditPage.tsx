import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatCards } from "@/components/common/StatCards";
import { statusLabel } from "@/lib/types";

interface AuditRow {
  id: number;
  audit_no: string;
  check_type: string;
  status: string;
  round_no: number;
  checklist: { sections?: { section?: string; items?: { key: string; text: string }[] }[] } | null;
  gaps: { items?: { key: string; status?: string; rectification?: string }[] } | null;
}

export function AuditPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [checkType, setCheckType] = useState("gmp");
  const [detail, setDetail] = useState<AuditRow | null>(null);
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["auditChecks"],
    queryFn: () => api.get("/audit/checks?page=1&page_size=50").then((d) => (d as { items: AuditRow[] }).items),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["auditChecks"] });

  const createCheck = async () => {
    const created = (await api.post("/audit/checks", { check_type: checkType })) as { id: number };
    setCreateOpen(false);
    setDetail(null);
    const fetchDetail = async () => {
      const d = (await api.get(`/audit/checks/${created.id}`)) as AuditRow;
      setDetail(d);
    };
    await fetchDetail();
    refresh();
  };

  const confirmGaps = async () => {
    if (!detail) return;
    const sections = detail.checklist?.sections ?? [];
    const gaps = sections.flatMap((s) =>
      (s.items ?? []).map((item) => ({
        key: item.key,
        section: s.section,
        text: item.text,
        status: "open",
        owner: "",
        due_date: "",
      })),
    );
    const d = (await api.post(`/audit/checks/${detail.id}/gaps`, { gaps })) as { status: string };
    setDetail({ ...detail, status: d.status, gaps: { items: gaps } });
    refresh();
  };

  const generateReport = async () => {
    if (!detail) return;
    const report = (await api.post(`/audit/checks/${detail.id}/report`, { summary: "迎检报告（自动生成）" })) as {
      open_gaps: number;
      evidence_count: number;
      audit_no: string;
    };
    alert(
      `迎检报告已生成：${report.audit_no}，未闭环缺口 ${report.open_gaps} 项，证据 ${report.evidence_count} 份。`,
    );
    refresh();
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1>审计检查准备</h1>
        <button className="btn-primary" onClick={() => setCreateOpen(!createOpen)}>
          {createOpen ? "收起" : "+ 创建检查任务"}
        </button>
      </div>

      {createOpen && (
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "1rem 1.2rem", marginBottom: "1.2rem" }}>
          <div style={{ display: "flex", gap: "0.8rem", alignItems: "flex-end" }}>
            <div style={{ width: 220 }}>
              <label>检查类型</label>
              <select value={checkType} onChange={(e) => setCheckType(e.target.value)}>
                <option value="gmp">GMP 生产检查</option>
                <option value="gcp">GCP 临床核查</option>
                <option value="iso">ISO 外审</option>
              </select>
            </div>
            <button className="btn-primary" onClick={createCheck}>生成检查表</button>
          </div>
        </div>
      )}

      <StatCards
        stats={[
          { label: "检查任务", value: list.data?.length ?? 0 },
          { label: "整改中", value: list.data?.filter((d) => d.status === "rectifying").length ?? 0, tone: "warn" },
          { label: "已出报告", value: list.data?.filter((d) => d.status === "reported").length ?? 0, tone: "ok" },
        ]}
      />

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>检查单号</th>
              <th>类型</th>
              <th>轮次</th>
              <th>检查项</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!list.data && (
              <tr><td colSpan={6} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td></tr>
            )}
            {(list.data ?? []).map((c) => (
              <tr key={c.id}>
                <td>{c.audit_no}</td>
                <td>{c.check_type.toUpperCase()}</td>
                <td>第 {c.round_no} 轮</td>
                <td>{(c.checklist?.sections ?? []).reduce((n, s) => n + (s.items ?? []).length, 0)} 项</td>
                <td><span className="badge badge-pending">{statusLabel(c.status)}</span></td>
                <td>
                  <button
                    onClick={async () => {
                      const d = (await api.get(`/audit/checks/${c.id}`)) as AuditRow;
                      setDetail(d);
                    }}
                  >
                    查看/整改
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 90 }}>
          <div style={{ background: "#fff", borderRadius: "12px", padding: "1.4rem 1.6rem", width: 720, maxHeight: "85vh", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.8rem" }}>
              <h3>{detail.audit_no} 检查明细</h3>
              <button className="btn-ghost" onClick={() => setDetail(null)}>关闭</button>
            </div>
            {(detail.checklist?.sections ?? []).map((sec, i) => (
              <div key={i} style={{ marginBottom: "0.8rem" }}>
                <strong>{sec.section}</strong>
                {(sec.items ?? []).map((item) => (
                  <div key={item.key} style={{ padding: "0.3rem 0.4rem", fontSize: "0.88rem", borderBottom: "1px solid var(--color-rule)" }}>
                    {item.text}
                  </div>
                ))}
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem", marginTop: "1rem" }}>
              {detail.status !== "reported" && (
                <>
                  <button onClick={confirmGaps} disabled={detail.status === "rectifying"}>
                    派发缺口整改
                  </button>
                  <button className="btn-primary" onClick={generateReport}>生成迎检报告</button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
