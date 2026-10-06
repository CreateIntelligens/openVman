import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../../api";
import { findPrecedingUserQuestion } from "./helpers";

describe("findPrecedingUserQuestion", () => {
  it("returns the user question right before an assistant answer", () => {
    const messages: ChatMessage[] = [
      { role: "user", content: " 門診幾點開始？ " },
      { role: "assistant", content: "早上九點" },
    ];

    expect(findPrecedingUserQuestion(messages, 1)).toBe("門診幾點開始？");
  });

  it("returns null when the answer has no user question before it", () => {
    const messages: ChatMessage[] = [
      { role: "assistant", content: "歡迎光臨" },
      { role: "user", content: "你好" },
      { role: "assistant", content: "第一個回答" },
      { role: "assistant", content: "接續的回答" },
    ];

    expect(findPrecedingUserQuestion(messages, 0)).toBeNull();
    expect(findPrecedingUserQuestion(messages, 3)).toBeNull();
  });
});
