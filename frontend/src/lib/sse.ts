import { getToken } from "./api";

// 开发期流通道直连后端：避免 vite proxy 连接复用失效导致的首连 ERR_ABORTED；
// 生产同域反代时为空字符串（走相对路径）。
const API_STREAM_BASE = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";

export interface SseEvent {
  type: string;
  content?: string;
  citations?: unknown[];
  flag?: string;
  confidence?: number;
  code?: string;
  message?: string;
  message_id?: number;
  resumed?: boolean;
  unverified_claims?: string[];
}

export interface SseCallbacks {
  onEvent: (event: SseEvent) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

export interface AskOptions {
  resume?: boolean;
}

const MAX_RETRY = 5;
const BASE_DELAY_MS = 1000;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class SseClient {
  private controller: AbortController | null = null;
  // 主动停止标志：仅 stop() 置位；网络取消（net::ERR_ABORTED 等）不视为主动停止
  private userStopped = false;
  private es: EventSource | null = null;

  /**
   * 原生 EventSource 通道（GET 流）：规避 fetch+ReadableStream 在部分 Chromium
   * 环境对已完成流的 ERR_ABORTED 打标；断线由浏览器自动重连并携带 Last-Event-Id，
   * 服务端据此幂等重放已完成回答（规格 4.6）。
   */
  askEventSource(query: string, conversationId: number | null, callbacks: SseCallbacks): void {
    const token = getToken();
    if (!token) {
      callbacks.onError?.(new Error("未登录"));
      return;
    }
    this.userStopped = false;
    this.stopStreams();
    const params = new URLSearchParams({ query, token });
    if (conversationId) params.set("conversation_id", String(conversationId));
    const es = new EventSource(`${API_STREAM_BASE}/api/v1/qa/ask-stream?${params.toString()}`);
    this.es = es;

    es.onmessage = (e: MessageEvent<string>) => {
      let event: SseEvent;
      try {
        event = JSON.parse(e.data) as SseEvent;
      } catch {
        return;
      }
      callbacks.onEvent(event);
      if (event.type === "done" || event.type === "error") {
        // 不主动 close：让服务端 EOF 自然结束连接，避免客户端先行关闭被
        // Chromium 网络层打标 ERR_ABORTED（done 后由 onerror(CLOSED) 兜底清理）
        if (this.es === es) this.es = null;
        callbacks.onComplete?.();
      }
    };

    es.onerror = () => {
      // CONNECTING：浏览器自动退避重连（自动带 Last-Event-Id），静默等待
      if (es.readyState === EventSource.CLOSED) {
        if (this.es === es) this.es = null;
        callbacks.onError?.(new Error("SSE 连接中断，请重试或稍后重发"));
      }
    };
  }

  /** 保留的 fetch 流通道（兼容旧客户端/测试） */
  async ask(
    query: string,
    conversationId: number | null,
    callbacks: SseCallbacks,
    options?: AskOptions,
  ): Promise<void> {
    this.controller = new AbortController();
    this.userStopped = false;
    const token = getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    // 规格 4.6：连接建立前失败按指数退避重试（1s/2s/4s/8s/16s，封顶 5 次）；
    // 收到部分流后断线由调用方以 resume 模式重连（服务端重放已落库回复，幂等不重复落库）。
    const connectWithRetry = (attempt: number): Promise<Response> => {
      return fetch("/api/v1/qa/ask", {
        method: "POST",
        headers,
        body: JSON.stringify({
          query,
          conversation_id: conversationId,
          resume: !!options?.resume,
        }),
        signal: this.controller?.signal,
      })
        .then((resp) => {
          if (!resp.ok || !resp.body) {
            const err: Error & { status?: number } = new Error(`SSE 请求失败: ${resp.status}`);
            err.status = resp.status;
            throw err;
          }
          return resp;
        })
        .catch((err: Error) => {
          if (this.userStopped) throw err;
          const status = (err as Error & { status?: number }).status;
          // HTTP 业务错误（401/403/4xx/5xx）不重试，直接透传
          if (typeof status === "number") throw err;
          if (attempt < MAX_RETRY) {
            const delay = Math.min(BASE_DELAY_MS * 2 ** attempt, 30000);
            return sleep(delay).then(() => connectWithRetry(attempt + 1));
          }
          throw err;
        });
    };

    try {
      const resp = await connectWithRetry(0);
      // resp.body 已在连接校验通过（非 ok 或空 body 会抛错），此处安全取用
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // 看门狗：连接建立后若长时间收不到任何数据（半开连接 / 代理静默中断），
      // 强制结束本次流，避免 streaming 永久挂起
      const watchdog = setTimeout(() => this.controller?.abort(), 60000);

      const read = (): Promise<void> => {
        return reader.read().then(({ done, value }) => {
          if (done) {
            clearTimeout(watchdog);
            callbacks.onComplete?.();
            return;
          }
          clearTimeout(watchdog);
          buffer += decoder.decode(value, { stream: true });
          // 事件边界兼容 \r\n\r\n（SSE 规范 / sse-starlette 实际输出）与 \n\n
          const events = buffer.split(/\r?\n\r?\n/);
          buffer = events.pop() ?? "";
          for (const raw of events) {
            const line = raw
              .split(/\r?\n/)
              .find((l) => l.startsWith("data:"));
            if (!line) continue;
            const data = line.slice(5).trim();
            if (!data) continue;
            let event: SseEvent;
            try {
              event = JSON.parse(data);
            } catch {
              continue;
            }
            callbacks.onEvent(event);
            if (event.type === "error") {
              throw new Error(event.message || "服务端错误");
            }
          }
          return read();
        });
      };
      await read();
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      // 网络取消（ERR_ABORTED 等）同样上报，由调用方恢复/提示；
      // 仅用户主动 stop() 不打扰 UI
      if (!this.userStopped) {
        callbacks.onError?.(error);
      }
    }
  }

  private stopStreams() {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.controller?.abort();
  }

  stop() {
    this.userStopped = true;
    this.stopStreams();
  }
}

export const sseClient = new SseClient();
