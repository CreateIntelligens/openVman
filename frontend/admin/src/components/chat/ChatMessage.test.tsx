import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
      "/api/knowledge/qa/images/B1-4?project_id=default",
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
