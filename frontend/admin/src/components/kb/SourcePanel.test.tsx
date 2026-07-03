import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SourcePanel from "./SourcePanel";

describe("SourcePanel", () => {
  it("keeps upload mode scoped to document sources", () => {
    render(
      <SourcePanel
        activeMode="upload"
        setActiveMode={vi.fn()}
        uploading={false}
        uploadInputRef={createRef<HTMLInputElement>()}
        currentDir="knowledge"
        crawlUrlValue=""
        setCrawlUrlValue={vi.fn()}
        crawling={false}
        onCrawl={vi.fn()}
        onShowNote={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "選擇檔案上傳到 knowledge" })).toBeTruthy();
    expect(screen.queryByText(/題庫/)).toBeNull();
  });

  it("opens note creation immediately when manual mode is selected", () => {
    const setActiveMode = vi.fn();
    const onShowNote = vi.fn();

    render(
      <SourcePanel
        activeMode="upload"
        setActiveMode={setActiveMode}
        uploading={false}
        uploadInputRef={createRef<HTMLInputElement>()}
        currentDir="knowledge"
        crawlUrlValue=""
        setCrawlUrlValue={vi.fn()}
        crawling={false}
        onCrawl={vi.fn()}
        onShowNote={onShowNote}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /手動/ }));

    expect(setActiveMode).toHaveBeenCalledWith("manual");
    expect(onShowNote).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "新增筆記" })).toBeNull();
    expect(screen.queryByRole("button", { name: "手動新增 QA" })).toBeNull();
  });
});
