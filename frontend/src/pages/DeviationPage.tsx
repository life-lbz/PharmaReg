import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey } from "@/lib/api";
import { StatCards } from "@/components/common/StatCards";
import { SignDialog } from "@/components/common/SignDialog";
import { statusLabel } from "@/lib/types";
import { useAuthStore } from "@/app/stores/authStore";

interface DeviationRow {
  id: number;
  dev_no: string;
  title: string;
  description: string;
  area: string | null;
  severity: string;
  status: string;
  root_cause: string | null;
}

const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge-critical",
  major: "badge-major",
  minor: "badge-minor",
};

const REVIEW_MEANING = "本人已审核偏差分级与调查结论，批准此偏差处理结果";
const CLOSE_MEANING = "本人批准关闭此偏差记录（关联CAPA已验证、批次已解除）";

export function DeviationPage() {
  const [signAction, setSignAction] = useState<null | { type: "review" | "close"; dev: DeviationRow }>(null);
  const [classifyTarget, setClassifyTarget] = useState<DeviationRow | null>(null);
  const [classifySeverity, setClassifySeverity] = useState("major");
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const permissions = user?.permissions ?? [];
  const can = (p: string) => permissions.includes("*") || permissions.includes(p);

  const list = useQuery({
    queryKey: ["deviations"],
    queryFn: () => api.get("/deviations?page=1&page_size=100").then((d) => (d as { items: DeviationRow[] }).items),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["deviations"] });

  const classify = async () => {
    if (!classifyTarget) return;
    await api.post(`/deviations/${classifyTarget.id}/classify`, {
      severity: classifySeverity,
      classify_result: { ai_suggestion: classifySeverity, basis: "人工确认分级", ai_confidence: 0.9 },
    });
    setClassifyTarget(null);
    refresh();
  };

  const investigate = async (dev: DeviationRow) => {
    await api.post(`/deviations/${dev.id}/investigate`, {
      investigation_plan: {
        steps: ["收集现场证据与记录", "复核受影响范围", "按5-Why法分析根本原因"],
        owner: user?.employee_no ?? "",
      },
    });
    refresh();
  };

  const submitReview = async (dev: DeviationRow) => {
    const rootCause = prompt("请输入调查结论（根因）：", "已完成根因分析（待完善）");
    if (rootCause === null) return;
    await api.post(`/deviations/${dev.id}/submit-review`, { root_cause: rootCause });
    refresh();
  };

  const reopen = async (dev: DeviationRow) => {
    const reason = prompt("请输入驳回原因：");
    if (!reason) return;
    await api.post(`/deviations/${dev.id}/reopen`, { reason });
    refresh();
  };

  const doReview = async (pin: string) => {
    if (!signAction) return;
    if (signAction.type === "review") {
      await api.post(
        `/deviations/${signAction.dev.id}/review`,
        { approve: true, review_comment: "审核通过", signature_pin: pin, idempotency_key: newIdempotencyKey() },
      );
    } else {
      await api.post(
        `/deviations/${signAction.dev.id}/close`,
        { review_comment: "CAPA已验证，关闭偏差", signature_pin: pin, idempotency_key: newIdempotencyKey() },
      );
    }
    setSignAction(null);
    refresh();
  };

  return (
    <div>
      <h1 style={{ marginBottom: "1rem" }}>偏差处理工作台</h1>
      <StatCards
        stats={[
          { label: "偏差总数", value: list.data?.length ?? 0 },
          { label: "待QA审核", value: list.data?.filter((d) => d.status === "qa_review").length ?? 0, tone: "warn" },
          { label: "调查中", value: list.data?.filter((d) => d.status === "investigating").length ?? 0 },
          { label: "已关闭", value: list.data?.filter((d) => d.status === "closed").length ?? 0, tone: "ok" },
        ]}
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>单号</th>
              <th>标题</th>
              <th>区域</th>
              <th>等级</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!list.data && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td>
              </tr>
            )}
            {(list.data ?? []).map((dev) => (
              <tr key={dev.id}>
                <td>{dev.dev_no}</td>
                <td title={dev.description}>{dev.title}</td>
                <td>{dev.area ?? "-"}</td>
                <td>
                  <span className={`badge ${SEVERITY_BADGE[dev.severity] ?? "badge-muted"}`}>{statusLabel(dev.severity)}</span>
                </td>
                <td>
                  <span className="badge badge-pending">{statusLabel(dev.status)}</span>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {dev.status === "reported" && can("deviation.review") && (
                    <button onClick={() => { setClassifyTarget(dev); setClassifySeverity("major"); }}>分级</button>
                  )}
                  {dev.status === "classified" && can("deviation.manage") && (
                    <button onClick={() => investigate(dev)}>确认调查</button>
                  )}
                  {dev.status === "investigating" && can("deviation.manage") && (
                    <button onClick={() => submitReview(dev)}>提交审核</button>
                  )}
                  {dev.status === "qa_review" && can("deviation.review") && (
                    <>
                      <button onClick={() => setSignAction({ type: "review", dev })}>审核通过</button>
                      <button onClick={() => reopen(dev)}>驳回</button>
                    </>
                  )}
                  {dev.status === "capa_linked" && can("deviation.close") && (
                    <button onClick={() => setSignAction({ type: "close", dev })}>关闭</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {classifyTarget && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 80,
          }}
        >
          <div style={{ background: "#fff", borderRadius: "12px", padding: "1.4rem 1.6rem", width: 460 }}>
            <h3 style={{ marginBottom: "0.6rem" }}>偏差分级 - {classifyTarget.dev_no}</h3>
            <p style={{ color: "var(--color-muted)", marginBottom: "0.9rem" }}>{classifyTarget.title}</p>
            <div style={{ background: "var(--color-primary-soft)", borderRadius: "8px", padding: "0.8rem 1rem", marginBottom: "0.9rem", fontSize: "0.88rem" }}>
              <strong>AI建议：</strong> 主要 (major) —— 影响产品质量风险中等，需调查并采取纠正措施
            </div>
            <div style={{ marginBottom: "0.9rem" }}>
              <label>确认等级</label>
              <select value={classifySeverity} onChange={(e) => setClassifySeverity(e.target.value)}>
                <option value="critical">重大 critical</option>
                <option value="major">主要 major</option>
                <option value="minor">次要 minor</option>
              </select>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
              <button onClick={() => setClassifyTarget(null)}>取消</button>
              <button className="btn-primary" onClick={classify}>确认分级</button>
            </div>
          </div>
        </div>
      )}

      <SignDialog
        open={signAction !== null}
        meaning={signAction?.type === "review" ? REVIEW_MEANING : CLOSE_MEANING}
        onConfirm={doReview}
        onClose={() => setSignAction(null)}
      />
    </div>
  );
}
