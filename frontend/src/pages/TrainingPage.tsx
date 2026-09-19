import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatCards } from "@/components/common/StatCards";

interface ExamItem {
  id: number;
  title: string;
  position_type: string;
  pass_score: number;
  status: string;
}

export function TrainingPage() {
  const [examId, setExamId] = useState<number | null>(null);
  const exams = useQuery({
    queryKey: ["exams"],
    queryFn: () => api.get("/training/exams").then((d) => (d as { items: ExamItem[] }).items),
  });

  const startExam = async (id: number) => {
    const data = (await api.post(`/training/exams/${id}/start`)) as { record_id: number; questions: { id: number; stem: string; type: string; options?: Record<string, string> }[] };
    setExamId(id);
    const answers: Record<string, string> = {};
    for (const q of data.questions) {
      const opts = Object.entries(q.options ?? {});
      const ans = opts.length > 0 ? opts[0][0] : "对";
      answers[String(q.id)] = ans;
    }
    const result = (await api.post(`/training/exams/${id}/submit`, { answers })) as {
      score: number;
      passed: boolean;
      status: string;
    };
    alert(
      `考核完成！得分 ${result.score}，${result.passed ? "通过，可签发认证" : "未通过，请重新学习后补考"}`,
    );
    setExamId(null);
  };

  return (
    <div>
      <h1 style={{ marginBottom: "0.3rem" }}>培训认证中心</h1>
      <p style={{ color: "var(--color-muted)", marginBottom: "1.4rem" }}>按岗位完成考核，通过后由培训管理员签发岗位认证。</p>
      <StatCards
        stats={[
          { label: "可用考核批次", value: exams.data?.length ?? 0 },
          { label: "当前岗位", value: "请选择批次" },
        ]}
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>考核批次</th>
              <th>面向岗位</th>
              <th>通过线</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!exams.data && (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--color-muted)" }}>加载中…</td>
              </tr>
            )}
            {(exams.data ?? []).map((e) => (
              <tr key={e.id}>
                <td>{e.title}</td>
                <td>{e.position_type}</td>
                <td>{e.pass_score}</td>
                <td>
                  <span className="badge badge-active">{e.status}</span>
                </td>
                <td>
                  <button
                    className="btn-primary"
                    disabled={examId === e.id}
                    onClick={() => startExam(e.id)}
                  >
                    {examId === e.id ? "答题中…" : "开始考核"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
