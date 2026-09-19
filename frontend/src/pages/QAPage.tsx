import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { sseClient, SseEvent } from "@/lib/sse";
import { MessageBubble, CitationPanel } from "@/components/qa/MessageBubble";
import type { MessageItem, Citation } from "@/lib/types";

interface ConvItem {
  id: number;
  title: string | null;
  scenario: string;
}

interface LocalMsg {
  localId: number;
  role: string;
  content: string;
  citations?: Citation[] | null;
  flags?: Record<string, unknown> | null;
  confidence?: number | null;
  streaming?: boolean;
}

export function QAPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<LocalMsg[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [sideCitations, setSideCitations] = useState<Citation[]>([]);
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);

  const convsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: () =>
      api.get("/qa/conversations?page=1&page_size=50").then((d) => (d as { items: ConvItem[] }).items),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 卸载时停止进行中的 SSE（已落库回复可经会话历史或 resume 恢复）
  useEffect(() => () => sseClient.stop(), []);

  const loadMessages = async (convId: number) => {
    setActiveConvId(convId);
    const msgs = await api.get<MessageItem[]>(`/qa/conversations/${convId}/messages`);
    setMessages(msgs.map((m) => ({ localId: m.id, role: m.role, content: m.content, citations: m.citations, flags: m.flags, confidence: m.confidence })));
    setSideCitations([]);
  };

  const send = async () => {
    const query = input.trim();
    if (!query || streaming) return;
    setInput("");
    setStreaming(true);
    const userMsg: LocalMsg = { localId: Date.now(), role: "user", content: query };
    const aiMsg: LocalMsg = { localId: Date.now() + 1, role: "assistant", content: "", streaming: true };
    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setSideCitations([]);

    // 原生 EventSource 通道：断线由浏览器自动重连（携带 Last-Event-Id），
    // 服务端幂等重放已完成回复（规格 4.6）；resume 事件用于清空已收片段防叠加。
    let finished = false;

    const renderEvent = (ev: SseEvent) => {
      if (finished) return;
      if (ev.type === "resume") {
        setMessages((prev) =>
          prev.map((m) => (m.localId === aiMsg.localId ? { ...m, content: "", streaming: true } : m)),
        );
        return;
      }
      if (ev.type === "delta") {
        setMessages((prev) =>
          prev.map((m) =>
            m.localId === aiMsg.localId ? { ...m, content: m.content + (ev.content ?? "") } : m,
          ),
        );
      } else if (ev.type === "citation" && ev.citations) {
        setSideCitations(ev.citations as Citation[]);
      } else if (ev.type === "done") {
        finished = true;
        setMessages((prev) =>
          prev.map((m) => (m.localId === aiMsg.localId ? { ...m, streaming: false, confidence: ev.confidence ?? null } : m)),
        );
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
      } else if (ev.type === "flag") {
        finished = true;
        setMessages((prev) =>
          prev.map((m) =>
            m.localId === aiMsg.localId
              ? { ...m, streaming: false, flags: { needs_human_review: true }, confidence: ev.confidence ?? null }
              : m,
          ),
        );
      } else if (ev.type === "error") {
        finished = true;
        const shown =
          ev.code === "5006"
            ? "[连接中断] 服务端无完整回复记录，请重新发送。"
            : `[错误] ${ev.message ?? ev.code}`;
        setMessages((prev) =>
          prev.map((m) =>
            m.localId === aiMsg.localId
              ? { ...m, streaming: false, content: m.content || shown }
              : m,
          ),
        );
      }
    };

    sseClient.askEventSource(query, activeConvId, {
      onEvent: renderEvent,
      onComplete: () => setStreaming(false),
      onError: (err) => {
        setStreaming(false);
        setMessages((prev) =>
          prev.map((m) =>
            m.localId === aiMsg.localId
              ? {
                  ...m,
                  streaming: false,
                  content: m.content || `[连接失败] ${err.message}`,
                  flags: m.flags ?? { connection_lost: true },
                }
              : m,
          ),
        );
      },
    });
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "210px 1fr 280px", gap: "1rem", height: "calc(100vh - 4.5rem)" }}>
      <aside style={{ overflowY: "auto", borderRight: "1px solid var(--color-rule)", paddingRight: "0.7rem" }}>
        <button
          onClick={() => {
            setActiveConvId(null);
            setMessages([]);
            setSideCitations([]);
          }}
          className="btn-primary"
          style={{ width: "100%", marginBottom: "0.6rem" }}
        >
          + 新对话
        </button>
        {convsQuery.data?.map((conv) => (
          <button
            key={conv.id}
            onClick={() => loadMessages(conv.id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              marginBottom: "0.25rem",
              border: "none",
              background: activeConvId === conv.id ? "var(--color-primary-soft)" : "transparent",
              fontSize: "0.83rem",
              padding: "0.4rem 0.5rem",
            }}
          >
            {conv.title}
          </button>
        ))}
      </aside>

      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div style={{ flex: 1, overflowY: "auto", padding: "1rem 0.5rem" }}>
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--color-muted)", padding: "3rem 1rem" }}>
              <h2 style={{ color: "var(--color-ink)", marginBottom: "0.5rem" }}>规范速查问答</h2>
              <p>输入问题，例如：纯化水检测频次依据哪一条 / GMP对洁净区人员数量有何要求</p>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.localId} message={m} streaming={m.streaming} onCitationClick={(c) => setSideCitations((p) => [c, ...p])} />
          ))}
          <div ref={bottomRef} />
        </div>
        <div style={{ display: "flex", gap: "0.5rem", borderTop: "1px solid var(--color-rule)", paddingTop: "0.8rem" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            style={{ flex: 1, resize: "none" }}
          />
          <button className="btn-primary" onClick={send} disabled={streaming || !input.trim()}>
            {streaming ? "生成中…" : "发送"}
          </button>
        </div>
      </div>

      <aside style={{ overflowY: "auto" }}>
        <CitationPanel citations={sideCitations} onClose={() => setSideCitations([])} />
      </aside>
    </div>
  );
}
