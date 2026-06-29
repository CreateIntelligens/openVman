import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import QaModal from "./QaModal";

describe("QaModal", () => {
  it("previews QA rows as Markdown and allows creation when rows are complete", () => {
    render(
      <QaModal
        qaTitle="FAQ"
        setQaTitle={vi.fn()}
        qaTargetDir=""
        setQaTargetDir={vi.fn()}
        directoryOptions={["faq"]}
        qaRows={[{ question: "如何啟用?", answer: "按下開關。" }]}
        setQaRows={vi.fn()}
        creating={false}
        onClose={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    expect(screen.getByText("Markdown 預覽")).toBeTruthy();
    expect(screen.getByText((_, element) =>
      element?.tagName === "PRE" &&
      element.textContent === "## 如何啟用?\n\n按下開關。",
    )).toBeTruthy();
    expect((screen.getByRole("button", { name: "建立來源" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("blocks creation when a row has only a question or answer", () => {
    render(
      <QaModal
        qaTitle="FAQ"
        setQaTitle={vi.fn()}
        qaTargetDir=""
        setQaTargetDir={vi.fn()}
        directoryOptions={[]}
        qaRows={[{ question: "只有問題", answer: "" }]}
        setQaRows={vi.fn()}
        creating={false}
        onClose={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    expect(screen.getByText("每列都需要同時有問題與答案。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "建立來源" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers existing directories and a new directory input", () => {
    const setQaTargetDir = vi.fn();

    render(
      <QaModal
        qaTitle="FAQ"
        setQaTitle={vi.fn()}
        qaTargetDir="faq"
        setQaTargetDir={setQaTargetDir}
        directoryOptions={["faq", "support/billing"]}
        qaRows={[{ question: "Q", answer: "A" }]}
        setQaRows={vi.fn()}
        creating={false}
        onClose={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "faq" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "support/billing" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "新增目錄" })).toBeTruthy();
  });

  it("blocks creation for invalid new directory paths", () => {
    render(
      <QaModal
        qaTitle="FAQ"
        setQaTitle={vi.fn()}
        qaTargetDir="../outside"
        setQaTargetDir={vi.fn()}
        directoryOptions={[]}
        qaRows={[{ question: "Q", answer: "A" }]}
        setQaRows={vi.fn()}
        creating={false}
        onClose={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    expect(screen.getByText("目錄不可為絕對路徑或包含 ..。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "建立來源" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
