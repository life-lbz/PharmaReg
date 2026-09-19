import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey } from "@/lib/api";
import { DataTable } from "@/components/common/DataTable";

interface QuestionRow {
  id: number;
  position_type: string;
  type: string;
  stem: string;
  difficulty: number;
  status: string;
}

interface ExamRow {
  id: number;
  title: string;
  position_type: string;
  status: string;
}

interface MatrixRow {
  employee_no: string;
  positions: { position_type: string; issue_date: string | null; expire_date: string | null; is_expiring_soon: boolean }[];
}

type TabKey = "bank" | "exams" | "cert" | "matrix";

const TABS: { key: TabKey; label: string }[] = [
  { key: "bank", label: "题库维护" },
  { key: "exams", label: "组卷发布" },
  { key: "cert", label: "认证签发" },
  { key: "matrix", label: "认证矩阵与统计" },
];

const TYPE_LABEL: Record<string, string> = { single: "单选", multi: "多选", judge: "判断" };

function questionPayload(q: QuestionRow) {
  return {
    stem: q.stem,
    difficulty: q.difficulty,
    status: q.status,
  };
}

export function TrainingManagePage() {
  const [tab, setTab] = useState<TabKey>("bank");
  const queryClient = useQueryClient();
  const [positionType, setPositionType] = useState("");

  // —— 题库 ——
  const bankQuery = useQuery({
    queryKey: ["training-questions", positionType],
    queryFn: () =>
      api.get(`/training/questions?page=1&page_size=100${positionType ? `&position_type=${encodeURIComponent(positionType)}` : ""}`)
        .then((d) => (d as { items: QuestionRow[] }).items),
  });

  // 新增/编辑表单态
  const [editing, setEditing] = useState<QuestionRow | null>(null);
  const [form, setForm] = useState({
    position_type: "QA",
    type: "single",
    stem: "",
    options: "A=正确;B=错误",
    answer: "",
    difficulty: 3,
  });

  const bankMut = useMutation({
    mutationFn: async () => {
      if (editing) {
        await api.put(`/training/questions/${editing.id}`, questionPayload(editing));
      } else {
        const options: Record<string, string> = {};
        for (const part of form.options.split(/[;\n]/)) {
          const [k, v] = part.split("=").map((s) => s.trim());
          if (k && v) options[k] = v;
        }
        await api.post("/training/questions", {
          position_type: form.position_type,
          type: form.type,
          stem: form.stem,
          options,
          answer: form.answer,
          difficulty: form.difficulty,
        }, newIdempotencyKey());
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["training-questions"] });
      setEditing(null);
      setForm({ position_type: "QA", type: "single", stem: "", options: "A=正确;B=错误", answer: "", difficulty: 3 });
    },
  });

  const toggleStatus = useMutation({
    mutationFn: (row: QuestionRow) =>
      api.put(`/training/questions/${row.id}`, { status: row.status === "disabled" ? "active" : "disabled" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["training-questions"] }),
  });

  // —— 组卷 ——
  const examsQuery = useQuery({
    queryKey: ["training-exams"],
    queryFn: () => api.get("/training/exams?page=1&page_size=50").then((d) => (d as { items: ExamRow[] }).items),
  });
  const [examForm, setExamForm] = useState({ title: "", position_type: "QA", pass_score: 80, assist: true });
  const examMut = useMutation({
    mutationFn: () =>
      api.post("/training/exams", { ...examForm, assist: examForm.assist }, newIdempotencyKey()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["training-exams"] });
      setExamForm({ title: "", position_type: "QA", pass_score: 80, assist: true });
    },
  });

  // —— 认证签发 ——
  const certMut = useMutation({
    mutationFn: (payload: { exam_record_id: number; employee_no: string; position_type: string; expire_date?: string }) =>
      api.post("/training/certifications", payload, newIdempotencyKey()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cert-matrix"] });
      queryClient.invalidateQueries({ queryKey: ["training-analytics"] });
    },
  });
  const [certForm, setCertForm] = useState({ exam_record_id: "", employee_no: "", position_type: "QA", expire_date: "" });

  // —— 矩阵 & 分析 ——
  const matrixQuery = useQuery({
    queryKey: ["cert-matrix"],
    queryFn: () => api.get<MatrixRow[]>("/training/matrix"),
  });
  const analyticsQuery = useQuery({
    queryKey: ["training-analytics"],
    queryFn: () => api.get<{ total_certifications: number; valid_certifications: number; expiring_soon: number; cert_rate: number }>("/training/analytics"),
  });

  const inputStyle: React.CSSProperties = { padding: "0.35rem 0.55rem", border: "1px solid var(--color-rule)", borderRadius: "6px", fontSize: "0.85rem", minWidth: 0 };
  const formLabel: React.CSSProperties = { fontSize: "0.78rem", color: "var(--color-muted)", marginBottom: "0.2rem" };

  return (
    <div>
      <h2 style={{ fontSize: "1.2rem", marginBottom: "0.2rem" }}>培训管理工作台</h2>
      <p style={{ color: "var(--color-muted)", fontSize: "0.85rem", marginBottom: "1rem" }}>
        题库维护 / 组卷发布 / 认证签发 / 认证矩阵（规格 9.1 trainer 专属）
      </p>

      <div style={{ display: "flex", gap: "0.4rem", borderBottom: "2px solid var(--color-rule)", marginBottom: "1rem" }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "0.45rem 1rem",
              border: "none",
              background: tab === t.key ? "var(--color-primary)" : "transparent",
              color: tab === t.key ? "#fff" : "var(--color-ink)",
              borderRadius: "8px 8px 0 0",
              fontSize: "0.88rem",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "bank" && (
        <div>
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", marginBottom: "0.7rem", flexWrap: "wrap" }}>
            <input
              placeholder="按岗位筛选（如 QA / QC）"
              value={positionType}
              onChange={(e) => setPositionType(e.target.value)}
              style={{ ...inputStyle, width: 180 }}
            />
            <button
              className="btn-primary"
              onClick={() =>
                setEditing({
                  id: 0, position_type: form.position_type, type: form.type, stem: "", difficulty: 3, status: "active",
                })
              }
            >
              + 新增题目
            </button>
            <span style={{ color: "var(--color-muted)", fontSize: "0.8rem" }}>共 {bankQuery.data?.length ?? 0} 题（不含答案展示）</span>
          </div>

          {(editing || bankMut.isPending) && (
            <div style={{ border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "0.9rem 1rem", marginBottom: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.6rem" }}>
              <div>
                <div style={formLabel}>岗位</div>
                <input style={{ ...inputStyle, width: "100%" }} value={editing ? editing.position_type : form.position_type} onChange={(e) => (editing ? setEditing({ ...editing, position_type: e.target.value }) : setForm({ ...form, position_type: e.target.value }))} />
              </div>
              <div>
                <div style={formLabel}>题型</div>
                <select style={{ ...inputStyle, width: "100%" }} value={editing ? editing.type || "single" : form.type} onChange={(e) => (editing ? setEditing({ ...editing, type: e.target.value }) : setForm({ ...form, type: e.target.value }))}>
                  <option value="single">单选</option>
                  <option value="multi">多选</option>
                  <option value="judge">判断</option>
                </select>
              </div>
              <div>
                <div style={formLabel}>题干（新增时必填）</div>
                <input style={{ ...inputStyle, width: "100%" }} value={editing ? editing.stem : form.stem} onChange={(e) => (editing ? setEditing({ ...editing, stem: e.target.value }) : setForm({ ...form, stem: e.target.value }))} />
              </div>
              {!editing && (
                <>
                  <div>
                    <div style={formLabel}>选项（A=xx;B=xx）</div>
                    <input style={{ ...inputStyle, width: "100%" }} value={form.options} onChange={(e) => setForm({ ...form, options: e.target.value })} />
                  </div>
                  <div>
                    <div style={formLabel}>正确答案</div>
                    <input style={{ ...inputStyle, width: "100%" }} value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} />
                  </div>
                </>
              )}
              <div>
                <div style={formLabel}>难度 1-5</div>
                <input type="number" min={1} max={5} style={{ ...inputStyle, width: "100%" }} value={editing ? editing.difficulty : form.difficulty} onChange={(e) => (editing ? setEditing({ ...editing, difficulty: Number(e.target.value) }) : setForm({ ...form, difficulty: Number(e.target.value) }))} />
              </div>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
                <button className="btn-primary" disabled={!editing?.stem && !form.stem} onClick={() => bankMut.mutate()}>
                  {editing ? "保存修改" : "创建题目"}
                </button>
                <button onClick={() => setEditing(null)}>取消</button>
              </div>
            </div>
          )}

          <DataTable<QuestionRow>
            columns={[
              { key: "id", title: "ID", width: "50px" },
              { key: "position_type", title: "岗位" },
              { key: "type", title: "题型", render: (r) => TYPE_LABEL[r.type] ?? r.type },
              { key: "stem", title: "题干" },
              { key: "difficulty", title: "难度" },
              { key: "status", title: "状态", render: (r) => (r.status === "disabled" ? "已停用" : "启用") },
              {
                key: "actions",
                title: "操作",
                render: (r) => (
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    <button onClick={() => setEditing(r)}>编辑</button>
                    <button onClick={() => toggleStatus.mutate(r)}>{r.status === "disabled" ? "启用" : "停用"}</button>
                  </span>
                ),
              },
            ]}
            rows={bankQuery.data ?? []}
            rowKey={(r) => r.id}
          />
        </div>
      )}

      {tab === "exams" && (
        <div>
          <div style={{ border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "0.9rem 1rem", marginBottom: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.6rem" }}>
            <div>
              <div style={formLabel}>试卷标题</div>
              <input style={{ ...inputStyle, width: "100%" }} value={examForm.title} onChange={(e) => setExamForm({ ...examForm, title: e.target.value })} />
            </div>
            <div>
              <div style={formLabel}>岗位</div>
              <input style={{ ...inputStyle, width: "100%" }} value={examForm.position_type} onChange={(e) => setExamForm({ ...examForm, position_type: e.target.value })} />
            </div>
            <div>
              <div style={formLabel}>及格分</div>
              <input type="number" style={{ ...inputStyle, width: "100%" }} value={examForm.pass_score} onChange={(e) => setExamForm({ ...examForm, pass_score: Number(e.target.value) })} />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: "0.5rem" }}>
              <label style={{ fontSize: "0.85rem" }}>
                <input type="checkbox" checked={examForm.assist} onChange={(e) => setExamForm({ ...examForm, assist: e.target.checked })} style={{ marginRight: "0.3rem" }} />
                AI 组卷
              </label>
              <button className="btn-primary" disabled={!examForm.title} onClick={() => examMut.mutate()}>发布试卷</button>
            </div>
          </div>
          <DataTable<ExamRow>
            columns={[
              { key: "id", title: "ID", width: "50px" },
              { key: "title", title: "试卷" },
              { key: "position_type", title: "岗位" },
              { key: "status", title: "状态" },
            ]}
            rows={examsQuery.data ?? []}
            rowKey={(r) => r.id}
          />
        </div>
      )}

      {tab === "cert" && (
        <div style={{ maxWidth: 640 }}>
          <div style={{ border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "0.9rem 1rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem" }}>
            <div>
              <div style={formLabel}>考核记录 ID</div>
              <input style={{ ...inputStyle, width: "100%" }} value={certForm.exam_record_id} onChange={(e) => setCertForm({ ...certForm, exam_record_id: e.target.value })} />
            </div>
            <div>
              <div style={formLabel}>工号</div>
              <input style={{ ...inputStyle, width: "100%" }} value={certForm.employee_no} onChange={(e) => setCertForm({ ...certForm, employee_no: e.target.value })} />
            </div>
            <div>
              <div style={formLabel}>岗位认证类型</div>
              <input style={{ ...inputStyle, width: "100%" }} value={certForm.position_type} onChange={(e) => setCertForm({ ...certForm, position_type: e.target.value })} />
            </div>
            <div>
              <div style={formLabel}>有效期至（YYYY-MM-DD，可空）</div>
              <input style={{ ...inputStyle, width: "100%" }} value={certForm.expire_date} onChange={(e) => setCertForm({ ...certForm, expire_date: e.target.value })} />
            </div>
            <div style={{ gridColumn: "1 / -1" }}>
              <button
                className="btn-primary"
                disabled={!certForm.exam_record_id || !certForm.employee_no}
                onClick={() =>
                  certMut.mutate({
                    exam_record_id: Number(certForm.exam_record_id),
                    employee_no: certForm.employee_no,
                    position_type: certForm.position_type,
                    expire_date: certForm.expire_date || undefined,
                  })
                }
              >
                签发认证
              </button>
            </div>
          </div>
          <p style={{ color: "var(--color-muted)", fontSize: "0.82rem", marginTop: "0.6rem" }}>
            签发走电子签名审计（cert.issue）；通过人员依据考核记录核验后发放，过期前 30 天自动提醒。
          </p>
        </div>
      )}

      {tab === "matrix" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.7rem", marginBottom: "1rem" }}>
            {[
              { label: "认证总数", value: analyticsQuery.data?.total_certifications ?? 0 },
              { label: "有效认证", value: analyticsQuery.data?.valid_certifications ?? 0 },
              { label: "30 天内到期", value: analyticsQuery.data?.expiring_soon ?? 0 },
              { label: "认证率", value: `${analyticsQuery.data?.cert_rate ?? 0}%` },
            ].map((s) => (
              <div key={s.label} style={{ border: "1px solid var(--color-rule)", borderRadius: "10px", padding: "0.8rem", textAlign: "center" }}>
                <div style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--color-primary)" }}>{s.value}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--color-muted)" }}>{s.label}</div>
              </div>
            ))}
          </div>
          <DataTable<MatrixRow>
            columns={[
              { key: "employee_no", title: "工号" },
              {
                key: "positions",
                title: "岗位认证",
                render: (r) =>
                  r.positions
                    .map((p) => `${p.position_type}（至 ${p.expire_date ?? "-"}${p.is_expiring_soon ? "，临期" : ""}）`)
                    .join("；") || "无",
              },
            ]}
            rows={matrixQuery.data ?? []}
            rowKey={(r) => r.employee_no}
            emptyText="暂无有效认证记录"
          />
        </div>
      )}
    </div>
  );
}
