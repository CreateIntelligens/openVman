import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SourcePanel from "./SourcePanel";

describe("SourcePanel", () => {
  it("shows the QA creation action in QA mode", () => {
    render(
      <SourcePanel
        activeMode="qa"
        setActiveMode={vi.fn()}
        uploading={false}
        uploadInputRef={createRef<HTMLInputElement>()}
        currentDir="knowledge"
        crawlUrlValue=""
        setCrawlUrlValue={vi.fn()}
        crawling={false}
        onCrawl={vi.fn()}
        onShowNote={vi.fn()}
        onShowQa={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "新增 QA" })).toBeTruthy();
  });
});
