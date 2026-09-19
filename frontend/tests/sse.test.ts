import { afterEach, describe, expect, it, vi } from "vitest";
import { sseClient } from "../src/lib/sse";
import type { SseEvent } from "../src/lib/sse";

function streamResponse(events: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${e}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** 模拟 sse-starlette 实际输出：CRLF 事件边界 + 单帧含多个事件 + 帧尾带未完成半事件 */
function crlfStreamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const c of chunks) {
        controller.enqueue(encoder.encode(c));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("SSE client 事件流", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("逐帧解析 delta/citation/done 事件并回调", async () => {
    localStorage.setItem("pharmareg_token", "test-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse([
          JSON.stringify({ type: "delta", content: "依据" }),
          JSON.stringify({ type: "citation", citations: [{ clause_id: 1 }] }),
          JSON.stringify({ type: "done", message_id: 42, confidence: 0.9 }),
        ]),
      ),
    );

    const seen: SseEvent[] = [];
    let completed = false;
    await sseClient.ask("问题", null, {
      onEvent: (e) => seen.push(e),
      onComplete: () => {
        completed = true;
      },
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(seen.map((s) => s.type)).toEqual(["delta", "citation", "done"]);
    expect(seen[2].message_id).toBe(42);
    expect(completed).toBe(true);
  });

  it("CRLF 边界（sse-starlette 实际输出）逐事件解析，含跨帧半事件与空行容错", async () => {
    localStorage.setItem("pharmareg_token", "test-token");
    const e1 = JSON.stringify({ type: "delta", content: "第一段" });
    const e2 = JSON.stringify({ type: "citation", citations: [{ clause_id: 7 }] });
    const e3 = JSON.stringify({ type: "done", message_id: 9 });
    // 帧1：delta 完整 + citation 只发一半（模拟 TCP 分包）；帧2：剩余 + done
    const chunk1 = `event: message\r\ndata: ${e1}\r\n\r\nevent: message\r\ndata: ${e2.slice(0, Math.floor(e2.length / 2))}`;
    const chunk2 = `${e2.slice(Math.floor(e2.length / 2))}\r\n\r\nevent: message\r\ndata: ${e3}\r\n\r\n`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(crlfStreamResponse([chunk1, chunk2])));

    const seen: SseEvent[] = [];
    await sseClient.ask("问题", null, { onEvent: (e) => seen.push(e) });
    expect(seen.map((s) => s.type)).toEqual(["delta", "citation", "done"]);
    expect(seen[1].citations).toEqual([{ clause_id: 7 }]);
    expect(seen[2].message_id).toBe(9);
  });

  it("网络失败超过重试上限后触发 onError", async () => {
    localStorage.setItem("pharmareg_token", "test-token");
    // 无 HTTP status 的网络错误 -> 触发指数退避；缩短重试等待以加快测试
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();

    let error: Error | null = null;
    const p = sseClient.ask("问题", null, {
      onEvent: () => undefined,
      onError: (e) => {
        error = e;
      },
    });

    // 手动推进重试等待（1s+2s+4s+8s+16s = 31s 假时钟）
    await vi.advanceTimersByTimeAsync(32000);
    await p;
    vi.useRealTimers();

    expect(fetchMock).toHaveBeenCalledTimes(6); // 首次 + 5 次重试
    expect(error).toBeInstanceOf(TypeError);
  });

  it("HTTP 业务错误（403）不重试直接 onError", async () => {
    localStorage.setItem("pharmareg_token", "test-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ code: 1002, message: "无权限" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    let errMsg = "";
    await sseClient.ask("问题", null, {
      onEvent: () => undefined,
      onError: (e) => {
        errMsg = e.message;
      },
    });

    expect(fetchMock).toHaveBeenCalledTimes(1); // 403 不重试
    expect(errMsg).toContain("403");
  });
});
