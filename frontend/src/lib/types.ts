export interface Citation {
  clause_id: number | null;
  clause_no: string;
  excerpt: string;
  collection: string;
  kb_version_id?: number;
}

export interface QaAnswer {
  answer: string;
  mode: "faq" | "retrieval" | "needs_human_review";
  confidence: number;
  citations: Citation[];
  unverified_claims: string[];
}

export interface MessageItem {
  id: number;
  role: string;
  content: string;
  citations: Citation[] | null;
  flags: Record<string, unknown> | null;
  confidence: number | null;
  created_at: string | null;
}

export function severityLabel(s: string): string {
  const map: Record<string, string> = {
    critical: "重大",
    major: "主要",
    minor: "次要",
  };
  return map[s] ?? s;
}

export function statusLabel(s: string): string {
  const map: Record<string, string> = {
    reported: "已上报",
    classified: "已分级",
    investigating: "调查中",
    qa_review: "QA审核",
    capa_linked: "CAPA关联",
    closed: "已关闭",
    submitted: "已提交",
    assessed: "已评估",
    approved: "已批准",
    implemented: "实施中",
    verified: "已验证",
    recorded: "已记录",
    pv_reviewed: "PV已复核",
    draft: "草稿",
    signed: "已签名",
    archived: "已归档",
  };
  return map[s] ?? s;
}
