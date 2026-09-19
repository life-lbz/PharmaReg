import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey } from "@/lib/api";
import { SignDialog } from "@/components/common/SignDialog";
import { statusLabel } from "@/lib/types";

interface SaeRow {
  id: number;
  sae_no: string;
  subject_no: string | null;
  ae_description: string;
  causality: string | null;
  status: string;
  report_deadline_1: string | null;
  report_deadline_2: string | null;
  remaining_hours?: number | null;
  urgent?: boolean;
  draft?: { content?: string } | null;
}

const SIGN_MEANING = "本人作为研究者确认SAE报告内容真实，承担电子签名法律责任";
const SUBMIT_MEANING = "本人确认提交此SAE报告至申办方及伦理委员会";

export function SaePage() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ subject_no: "", ae_description: "" });
  const [signTarget, setSignTarget] = useState<null | { type: "sign" | "submit"; sae: SaeRow }>(null);
  const [detail, setDetail] = useState<SaeRow | null>(null);
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["sae"],
    queryFn: () => api.get("/sae?page=1&page_size=100").then((d) => (d as { items: SaeRow[] }).items),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sae"] });

  const createSae = async () => {
    if (!form.ae_description) return;
    const created = (await api.post("/sae", {
      subject_no: form.subject_no || undefined,
      ae_description: form.ae_description,
      seriousness: ["需确认"],
    })) as { id: number };
    setForm({ subject_no: "", ae_description: "" });
    setShowForm(false);
    refresh();
    const d = (await api.get(`/sae/${created.id}`)) as SaeRow;
    setDetail(d);
  };

  const pvReview = async (sae: SaeRow) => {
    await api.post(`/sae/${sae.id}/pv-review`, {
      seriousness: ["危及生命", "住院"],
      causality: "可能相关",
    });
    refresh();
  };

  const genDraft = async (sae: SaeRow) => {
    const content = prompt("草稿要点（可编辑）：", "受试者发生严重不良事件，已及时采取救治措施，情况稳定。");
    if (content === null) return;
    await api.post(`/sae/${sae.id}/draft`, { draft: { content, version: 1 } });
    refresh();
  };

  const doSign = async (pin: string) => {
    if (!signTarget) return;
    const { type, sae } = signTarget;
    if (type === "sign") {
      await api.post(
        `/sae/${sae.id}/sign`,
        { meaning: SIGN_MEANING, signature_pin: pin, idempotency_key: newIdempotencyKey() },
      );
    } else {
      const ok = window.confirm(`确认将 ${sae.sae_no} 提交至申办方/伦理？`);
      if (!ok) return;
      await api.post(
        `/sae/${sae.id}/submit`,
        { meaning: SUBMIT_MEANING, signature_pin: pin, idempotency_key: newIdempotencyKey() },
      );
    }
    setSignTarget(null);
    refresh();
  };

  const fmtDeadline = (iso: string | null) => {
    if (!iso) return "-";
    try {
      return new Date(iso).toLocaleString("zh-CN");
    } catch {
      return iso;
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1>SAE 上报辅助</h1>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "收起" : "+ 录入SAE事件"}
        </button>
      </div>

      {showForm && (
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "1rem 1.2rem", marginBottom: "1.2rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "0.8rem", marginBottom: "0.8rem" }}>
            <div>
              <label>受试者编号</label>
              <input value={form.subject_no} onChange={(e) => setForm({ ...form, subject_no: e.target.value })} placeholder="SUBJ-XXX" />
            </div>
            <div>
              <label>不良事件描述</label>
              <input value={form.ae_description} onChange={(e) => setForm({ ...form, ae_description: e.target.value })} />
            </div>
          </div>
          <button className="btn-primary" onClick={createSae} disabled={!form.ae_description}>录入并计算时限</button>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SAE单号</th>
              <th>受试者</th>
              <th>状态</th>
              <th>研究者→申办方(24h)</th>
              <th>剩余</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!list.data && (
              <tr><td colSpan={6} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td></tr>
            )}
            {(list.data ?? []).map((sae) => (
              <tr key={sae.id}>
                <td>{sae.sae_no}</td>
                <td>{sae.subject_no ?? "-"}</td>
                <td><span className="badge badge-pending">{statusLabel(sae.status)}</span></td>
                <td style={{ fontSize: "0.83rem" }}>{fmtDeadline(sae.report_deadline_1)}</td>
                <td>
                  {sae.remaining_hours != null && sae.remaining_hours <= 4 ? (
                    <span className="badge badge-critical">{sae.remaining_hours}h 紧急</span>
                  ) : sae.remaining_hours != null ? (
                    <span className="badge badge-active">{sae.remaining_hours}h</span>
                  ) : (
                    "-"
                  )}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button
                    onClick={async () => {
                      const d = (await api.get(`/sae/${sae.id}`)) as SaeRow;
                      setDetail(d);
                    }}
                  >
                    详情
                  </button>
                  {sae.status === "recorded" && (
                    <button onClick={() => pvReview(sae)}>PV复核</button>
                  )}
                  {sae.status === "pv_reviewed" && (
                    <button onClick={() => genDraft(sae)}>生成草稿</button>
                  )}
                  {sae.status === "draft" && (
                    <button onClick={() => setSignTarget({ type: "sign", sae })}>研究者签名</button>
                  )}
                  {sae.status === "signed" && (
                    <button onClick={() => setSignTarget({ type: "submit", sae })}>提交</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 90 }}>
          <div style={{ background: "#fff", borderRadius: "12px", padding: "1.4rem 1.6rem", width: 560 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.8rem" }}>
              <h3>{detail.sae_no}</h3>
              <button className="btn-ghost" onClick={() => setDetail(null)}>关闭</button>
            </div>
            <p style={{ color: "var(--color-muted)", fontSize: "0.9rem", marginBottom: "0.8rem" }}>{detail.ae_description}</p>
            <p>
              相关性：<span className="badge badge-pending">{detail.causality ?? "未判定"}</span>
              时限1：{fmtDeadline(detail.report_deadline_1)}　时限2：{fmtDeadline(detail.report_deadline_2)}
            </p>
            {detail.draft?.content && (
              <div style={{ background: "var(--color-primary-soft)", borderRadius: "8px", padding: "0.8rem 1rem", marginTop: "0.8rem", fontSize: "0.88rem" }}>
                <strong>报告草稿：</strong>
                {detail.draft.content}
              </div>
            )}
          </div>
        </div>
      )}

      <SignDialog
        open={signTarget !== null}
        meaning={signTarget?.type === "sign" ? SIGN_MEANING : SUBMIT_MEANING}
        onConfirm={doSign}
        onClose={() => setSignTarget(null)}
      />
    </div>
  );
}
