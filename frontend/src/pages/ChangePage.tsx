import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey } from "@/lib/api";
import { SignDialog } from "@/components/common/SignDialog";
import { statusLabel } from "@/lib/types";
import { useAuthStore } from "@/app/stores/authStore";

interface ChangeRow {
  id: number;
  chg_no: string;
  title: string;
  change_type: string;
  impact_level: string | null;
  status: string;
  description: string;
}

const APPROVE_MEANING = "本人批准此变更申请，已确认影响评估结果";

export function ChangePage() {
  const [signTarget, setSignTarget] = useState<ChangeRow | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", change_type: "文件", description: "" });
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const permissions = user?.permissions ?? [];
  const can = (p: string) => permissions.includes("*") || permissions.includes(p);

  const list = useQuery({
    queryKey: ["changes"],
    queryFn: () => api.get("/changes?page=1&page_size=100").then((d) => (d as { items: ChangeRow[] }).items),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["changes"] });

  const createChange = async () => {
    if (!form.title || !form.description) return;
    await api.post("/changes", form);
    setForm({ title: "", change_type: "文件", description: "" });
    setShowForm(false);
    refresh();
  };

  const assess = async (chg: ChangeRow) => {
    await api.post(`/changes/${chg.id}/assess`, {
      impact_assessment: {
        ai_draft: "变更影响范围初步评估",
        impacted_systems: ["涉及文件/流程需同步更新"],
        regulatory_basis: [{ clause: "GMP 变更控制要求" }],
        human_reviewed: true,
      },
    });
    refresh();
  };

  const implement = async (chg: ChangeRow) => {
    await api.post(`/changes/${chg.id}/implement`, {
      implementation_plan: { steps: ["更新受控文件", "培训相关人员"], owner: user?.employee_no ?? "" },
    });
    refresh();
  };

  const verify = async (chg: ChangeRow) => {
    await api.post(`/changes/${chg.id}/verify`, { verification_result: { result: "实施确认完成" } });
    refresh();
  };

  const doApprove = async (pin: string) => {
    if (!signTarget) return;
    await api.post(
      `/changes/${signTarget.id}/approve`,
      { approval_comment: "已确认影响评估，批准变更", signature_pin: pin, idempotency_key: newIdempotencyKey() },
    );
    setSignTarget(null);
    refresh();
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1>变更控制工作台</h1>
        {can("change.manage") && (
          <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
            {showForm ? "收起" : "+ 发起变更"}
          </button>
        )}
      </div>

      {showForm && (
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "1rem 1.2rem", marginBottom: "1.2rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.8rem", marginBottom: "0.8rem" }}>
            <div>
              <label>变更标题</label>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </div>
            <div>
              <label>变更类型</label>
              <select value={form.change_type} onChange={(e) => setForm({ ...form, change_type: e.target.value })}>
                {["设施", "设备", "工艺", "文件", "物料"].map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ marginBottom: "0.8rem" }}>
            <label>变更描述</label>
            <textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <button className="btn-primary" onClick={createChange} disabled={!form.title || !form.description}>提交申请</button>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>单号</th>
              <th>标题</th>
              <th>类型</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!list.data && (
              <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td></tr>
            )}
            {(list.data ?? []).map((chg) => (
              <tr key={chg.id}>
                <td>{chg.chg_no}</td>
                <td title={chg.description}>{chg.title}</td>
                <td>{chg.change_type}</td>
                <td><span className="badge badge-pending">{statusLabel(chg.status)}</span></td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {chg.status === "submitted" && can("change.assess") && (
                    <button onClick={() => assess(chg)}>确认评估</button>
                  )}
                  {chg.status === "assessed" && can("change.approve") && (
                    <button onClick={() => setSignTarget(chg)}>批准</button>
                  )}
                  {chg.status === "approved" && can("change.manage") && (
                    <button onClick={() => implement(chg)}>实施</button>
                  )}
                  {chg.status === "implemented" && can("change.approve") && (
                    <button onClick={() => verify(chg)}>验证</button>
                  )}
                  {chg.status === "verified" && can("change.approve") && (
                    <button onClick={() => api.post(`/changes/${chg.id}/close`, {}).then(refresh)}>关闭</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SignDialog
        open={signTarget !== null}
        meaning={APPROVE_MEANING}
        onConfirm={doApprove}
        onClose={() => setSignTarget(null)}
      />
    </div>
  );
}
