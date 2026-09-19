import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageBubble } from "../src/components/qa/MessageBubble";

describe("MessageBubble 渲染", () => {
  it("用户消息右对齐展示文本", () => {
    render(<MessageBubble message={{ role: "user", content: "纯化水检测频次？" }} />);
    expect(screen.getByText("纯化水检测频次？")).toBeTruthy();
  });

  it("assistant 消息展示置信度与引用芯片", () => {
    const onCitation = vi.fn();
    render(
      <MessageBubble
        message={{
          role: "assistant",
          content: "依据第X条…",
          confidence: 0.92,
          citations: [
            { clause_id: 1, clause_no: "第X条", excerpt: "摘录", collection: "doc_gmp_2010" },
          ],
        }}
        onCitationClick={onCitation}
      />,
    );
    expect(screen.getByText(/92%/)).toBeTruthy();
    const chip = screen.getByRole("button", { name: /第X条/ });
    expect(chip).toBeTruthy();
    chip.click();
    expect(onCitation).toHaveBeenCalledTimes(1);
  });

  it("needs_human_review 标记展示待人工确认徽标", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant",
          content: "需人工确认的答案",
          flags: { needs_human_review: true },
          confidence: 0.5,
        }}
      />,
    );
    expect(screen.getByText("待人工确认")).toBeTruthy();
  });

  it("流式输出展示光标且无完成态徽标", () => {
    render(<MessageBubble message={{ role: "assistant", content: "部分内容" }} streaming />);
    expect(screen.getByText("部分内容")).toBeTruthy();
  });
});
