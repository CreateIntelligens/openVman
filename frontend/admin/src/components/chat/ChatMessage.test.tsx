import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChatMessage from "./ChatMessage";

describe("ChatMessage privacy warning rendering", () => {
  it("renders localized privacy warning summaries for user messages", () => {
    render(
      <ChatMessage
        message={{
          role: "user",
          content: "Call me",
          privacy_warning: {
            categories: ["private_phone", "private_email"],
            counts: { private_phone: 1, private_email: 2 },
          },
        }}
        privacyWarningsVisible
      />,
    );

    expect(screen.getByText("偵測到：電話 ×1、Email ×2")).not.toBeNull();
  });

  it("hides privacy warnings when visibility is disabled", () => {
    render(
      <ChatMessage
        message={{
          role: "user",
          content: "Call me",
          privacy_warning: {
            categories: ["private_phone"],
            counts: { private_phone: 1 },
          },
        }}
        privacyWarningsVisible={false}
      />,
    );

    expect(screen.queryByText("偵測到：電話 ×1")).toBeNull();
  });

  it("renders the primary RAG image and link", () => {
    render(
      <ChatMessage
        message={{
          role: "assistant",
          content: "請掃描院內提供的 QR code。",
          image_id: "B1-4",
          url: "https://example.com/line",
          citations: [
            {
              uri: "knowledge/qa/line.csv",
              title: "官方 LINE",
              text: "請掃描 QR code",
            },
          ],
        }}
      />,
    );

    const image = screen.getByRole("img", { name: "官方 LINE" });
    expect(image.getAttribute("src")).toBe(
      "/api/v1/knowledge/qa/images/B1-4?project_id=default",
    );
    expect(screen.getByRole("link", { name: "開啟相關連結" }).getAttribute("href"))
      .toBe("https://example.com/line");
  });

  it("does not render unsafe RAG links", () => {
    render(
      <ChatMessage
        message={{
          role: "assistant",
          content: "不安全連結",
          url: "javascript:alert(1)",
        }}
      />,
    );

    expect(screen.queryByRole("link", { name: "開啟相關連結" })).toBeNull();
  });
});

describe("ChatMessage correct-as-QA action", () => {
  const actionProps = { index: 1, onPlayTts: vi.fn(), showAssistantActions: true };

  it("shows the action on assistant messages and calls the handler", () => {
    const onCorrectAsQa = vi.fn();
    render(
      <ChatMessage
        message={{ role: "assistant", content: "錯的答案" }}
        {...actionProps}
        onCorrectAsQa={onCorrectAsQa}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "修正成 QA" }));
    expect(onCorrectAsQa).toHaveBeenCalledTimes(1);
  });

  it("hides the action when no handler is given", () => {
    render(
      <ChatMessage
        message={{ role: "assistant", content: "沒有提問的回答" }}
        {...actionProps}
      />,
    );

    expect(screen.queryByRole("button", { name: "修正成 QA" })).toBeNull();
  });

  it("never shows the action on user messages", () => {
    render(
      <ChatMessage
        message={{ role: "user", content: "使用者提問" }}
        {...actionProps}
        onCorrectAsQa={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "修正成 QA" })).toBeNull();
  });
});
