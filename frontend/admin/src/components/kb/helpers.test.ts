import { describe, expect, it } from "vitest";

import { SOURCE_MODES, SOURCE_MODE_COPY, getSourceMeta } from "./helpers";

describe("knowledge source modes", () => {
  it("includes QA as a selectable source mode", () => {
    expect(SOURCE_MODES).toEqual(["upload", "web", "manual", "qa"]);
    expect(SOURCE_MODE_COPY.qa).toContain("Q&A");
    expect(getSourceMeta("qa")).toMatchObject({
      icon: "quiz",
      label: "QA",
    });
  });
});
