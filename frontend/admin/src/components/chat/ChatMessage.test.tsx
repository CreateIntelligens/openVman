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
});
