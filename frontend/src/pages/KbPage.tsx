import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey } from "@/lib/api";
import { SignDialog } from "@/components/common/SignDialog";

interface VersionRow {
  id: number;
  regulation: string;
  version_label: string;
  collection_prefix: string;
  status: string;
  activated_at: string | null;
  frozen_at: string | null;
}

const REG_LABEL: Record<string, string> = { gmp: "GMP", gcp: "GCP", ich: "ICH", iso: "ISO", internal: "内部SOP" };
const ACTIVATE_MEANING = "本人确认激活此法规版本集合，承担版本切换责任";

export function KbPage() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ regulation: "gcp", version_label: "", collection_prefix: "" });
  const [diffResult, setDiffResult] = useState<{ id: number; change_type: string }[] | null>(null);
  const [activateTarget, setActivateTarget] = useState<null | { type: "activate" | "rollback"; v: VersionRow }>(null);
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["kbVersions"],
    queryFn: () => api.get("/kb/versions").then((d) => d as VersionRow[]),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["kbVersions"] });

  const createVersion = async () => {
    if (!form.version_label || !form.collection_prefix) return;
    await api.post("/kb/versions", form);
    setForm({ regulation: "gcp", version_label: "", collection_prefix: "" });
    setShowForm(false);
    refresh();
  };

  const runDiff = async (v: VersionRow) => {
    const diffs = (await api.post(`/kb/versions/${v.id}/diff`)) as { id: number; change_type: string }[];
    if (diffs.length === 0) {
      alert("无差异，可提交人工复核确认后激活。");
    }
    setDiffResult(diffs);
    refresh();
  };

  const confirmAllDiffs = async () => {
    if (!diffResult) return;
    for (const d of diffResult) {
      await api.put(`/kb/version-diffs/${d.id}/review`, { review_status: "confirmed" });
    }
    setDiffResult(null);
    alert("差异已全部人工复核确认，可进行激活。");
    refresh();
  };

  const doActivate = async (pin: string) => {
    if (!activateTarget) return;
    const { type, v } = activateTarget;
    let reason: string | undefined;
    if (type === "rollback") {
      reason = prompt("请填写回滚原因（必填）：") ?? undefined;
      if (!reason) return;
    }
    const path = type === "activate" ? `/kb/versions/${v.id}/activate` : `/kb/versions/${v.id}/rollback`;
    await api.post(path, {
      signature_pin: pin,
      idempotency_key: newIdempotencyKey(),
      reason,
    });
    setActivateTarget(null);
    refresh();
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1>法规库版本管理</h1>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "收起" : "+ 新建版本集合"}
        </button>
      </div>

      {showForm && (
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "1rem 1.2rem", marginBottom: "1.2rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.8rem", marginBottom: "0.8rem" }}>
            <div>
              <label>法规</label>
              <select value={form.regulation} onChange={(e) => setForm({ ...form, regulation: e.target.value })}>
                {Object.entries(REG_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label>版本标签</label>
              <input value={form.version_label} onChange={(e) => setForm({ ...form, version_label: e.target.value })} placeholder="如 2026修订" />
            </div>
            <div>
              <label>集合前缀</label>
              <input value={form.collection_prefix} onChange={(e) => setForm({ ...form, collection_prefix: e.target.value })} placeholder="如 gcp-2026" />
            </div>
          </div>
          <button className="btn-primary" onClick={createVersion}>创建草稿集合</button>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>法规</th>
              <th>版本</th>
              <th>集合前缀</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!list.data && (
              <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td></tr>
            )}
            {(list.data ?? []).map((v) => (
              <tr key={v.id}>
                <td>{REG_LABEL[v.regulation] ?? v.regulation}</td>
                <td>{v.version_label}</td>
                <td>{v.collection_prefix}</td>
                <td>
                  {v.status === "active" && <span className="badge badge-done">激活中</span>}
                  {v.status === "draft" && <span className="badge badge-active">草稿</span>}
                  {v.status === "frozen" && <span className="badge badge-muted">已冻结</span>}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {v.status === "draft" && (
                    <>
                      <button onClick={() => runDiff(v)}>版本对比</button>
                      <button className="btn-primary" onClick={() => setActivateTarget({ type: "activate", v })} disabled={diffResult !== null}>
                        激活
                      </button>
                    </>
                  )}
                  {v.status === "frozen" && (
                    <button onClick={() => setActivateTarget({ type: "rollback", v })}>回滚激活</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {diffResult && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 90 }}>
          <div style={{ background: "#fff", borderRadius: "12px", padding: "1.4rem 1.6rem", width: 560, maxHeight: "80vh", overflowY: "auto" }}>
            <h3 style={{ marginBottom: "0.6rem" }}>版本差异复核（{diffResult.length} 条）</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "1rem" }}>
              {diffResult.map((d) => (
                <span key={d.id} className={`badge ${d.change_type === "added" ? "badge-done" : d.change_type === "removed" ? "badge-critical" : "badge-major"}`}>
                  {d.change_type}
                </span>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
              <button onClick={() => setDiffResult(null)}>关闭</button>
              <button className="btn-primary" onClick={confirmAllDiffs}>全部确认</button>
            </div>
          </div>
        </div>
      )}

      <SignDialog
        open={activateTarget !== null}
        meaning={activateTarget?.type === "activate" ? ACTIVATE_MEANING : "本人确认回滚此法规版本至上一冻结版本"}
        onConfirm={doActivate}
        onClose={() => setActivateTarget(null)}
      />
    </div>
  );
}
