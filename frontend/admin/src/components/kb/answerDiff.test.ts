import { describe, expect, it } from "vitest";

import { diffAnswers } from "./answerDiff";

describe("diffAnswers", () => {
  it("keeps the longest shared characters and marks the changed characters on both sides", () => {
    expect(diffAnswers("早上九點", "早上十點")).toEqual([
      [{ text: "早上", changed: false }, { text: "九", changed: true }, { text: "點", changed: false }],
      [{ text: "早上", changed: false }, { text: "十", changed: true }, { text: "點", changed: false }],
    ]);
  });

  it("handles insertions, removals, and whole Unicode code points", () => {
    expect(diffAnswers("甲🐈乙", "甲乙🐕")).toEqual([
      [{ text: "甲", changed: false }, { text: "🐈", changed: true }, { text: "乙", changed: false }],
      [{ text: "甲乙", changed: false }, { text: "🐕", changed: true }],
    ]);
    expect(diffAnswers("", "新答案")).toEqual([[], [{ text: "新答案", changed: true }]]);
  });

  it("shows both answers without highlighting when one exceeds 2000 characters", () => {
    const long = "🐈".repeat(2001);
    expect(diffAnswers(long, "短答案")).toEqual([
      [{ text: long, changed: false }],
      [{ text: "短答案", changed: false }],
    ]);
  });
});
