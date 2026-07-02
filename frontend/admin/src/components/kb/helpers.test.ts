import { describe, expect, it } from "vitest";

import { SOURCE_MODES, SOURCE_MODE_COPY, getSourceMeta } from "./helpers";

describe("knowledge source modes", () => {
  it("keeps document source modes separate from QA authoring", () => {
    expect(SOURCE_MODES).toEqual(["upload", "web", "manual"]);
    expect(SOURCE_MODE_COPY.upload).not.toContain("題庫");
    expect(SOURCE_MODE_COPY.manual).not.toContain("Q&A");
  });

  it("still renders QA as a document source type", () => {
    expect(getSourceMeta("qa")).toMatchObject({
      icon: "quiz",
      label: "QA",
    });
  });
});
