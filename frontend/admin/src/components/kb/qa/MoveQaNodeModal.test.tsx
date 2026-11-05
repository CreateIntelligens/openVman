import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { QaNode } from "../../../hooks/useQaNodes";
import MoveQaNodeModal from "./MoveQaNodeModal";

function category(
  id: string,
  label: string,
  parentIds: string[],
  children: QaNode[] = [],
  hidden = false,
): QaNode {
  return {
    node_id: id,
    label,
    parent_ids: parentIds,
    child_ids: children.map((child) => child.node_id),
    order: 1,
    hidden,
    qa_entries: [],
    children,
  };
}

const grandchild = category("grandchild", "孫分類", ["child"]);
const child = category("child", "子分類", ["moving"], [grandchild]);
const moving = category("moving", "退換貨", ["zh"], [child]);
const zh = category("zh", "中文", [], [moving]);
const hiddenOne = category("en", "English", [], [], true);
const tree = [zh, hiddenOne];

function radio(name: RegExp | string) {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

function renderModal(overrides: Partial<Parameters<typeof MoveQaNodeModal>[0]> = {}) {
  const props = {
    node: moving,
    nodesTree: tree,
    onConfirm: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  return { ...render(<MoveQaNodeModal {...props} />), props };
}

describe("MoveQaNodeModal", () => {
  it("names the category being moved in the title", () => {
    renderModal();

    expect(screen.getByRole("dialog", { name: "把「退換貨」移到…" })).toBeTruthy();
  });

  // Chromium 的 fieldset 不裁切自己的內容：捲動放在它身上時，分類一多清單就畫到對話框外面。
  // jsdom 看不出來，1280×720 的實際瀏覽器 15 個分類就會超出。
  it("scrolls the list in a wrapper around the fieldset", () => {
    renderModal();

    const fieldset = screen.getByRole("group", { name: "新位置" });
    expect(fieldset.className).not.toContain("overflow");
    expect(fieldset.parentElement?.className).toContain("overflow-y-auto");
  });

  it("lists 最上層 first, then the category tree, indented by level", () => {
    renderModal();

    const labels = screen.getAllByRole("radio").map((input) => input.closest("label"));
    expect(labels[0]?.textContent).toContain("最上層");
    expect(labels[1]?.textContent).toContain("中文");
    const indent = (name: string) => radio(new RegExp(name)).closest("label")?.style.paddingLeft;
    expect(parseFloat(indent("中文") ?? "0")).toBeLessThan(parseFloat(indent("退換貨") ?? "0"));
    expect(parseFloat(indent("退換貨") ?? "0")).toBeLessThan(parseFloat(indent("子分類") ?? "0"));
  });

  // 實測沒有「移到…」時同層分類根本進不去；選了子孫則會造成循環。
  it("cannot choose the category itself or anything under it", () => {
    renderModal();

    expect(radio(/退換貨/).disabled).toBe(true);
    expect(radio(/子分類/).disabled).toBe(true);
    expect(radio(/孫分類/).disabled).toBe(true);
    expect(screen.getByText("就是這個分類")).toBeTruthy();
    expect(screen.getAllByText("在這個分類底下")).toHaveLength(2);

    expect(radio(/最上層/).disabled).toBe(false);
    expect(radio(/中文/).disabled).toBe(false);
    expect(radio(/English/).disabled).toBe(false);
  });

  it("marks the current location, selects it, and has nothing to confirm yet", () => {
    renderModal();

    expect(radio(/中文/).checked).toBe(true);
    expect(radio(/中文/).closest("label")?.textContent).toContain("目前位置");
    expect(radio(/最上層/).closest("label")?.textContent).not.toContain("目前位置");
    expect((screen.getByRole("button", { name: "移到這裡" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("marks 最上層 as current for a top-level category, or one whose parent is gone", () => {
    renderModal({ node: hiddenOne });
    expect(radio(/最上層/).closest("label")?.textContent).toContain("目前位置");
    expect(radio(/最上層/).checked).toBe(true);
  });

  it("treats a category whose parent no longer exists as top level", () => {
    renderModal({ node: category("orphan", "孤兒", ["deleted"]), nodesTree: tree });

    expect(radio(/最上層/).checked).toBe(true);
    expect(radio(/最上層/).closest("label")?.textContent).toContain("目前位置");
  });

  it("lets a category on several parents settle on just one of them", async () => {
    const shared = category("shared", "共用", ["zh", "en"]);
    const { props } = renderModal({ node: shared });

    expect(radio(/中文/).closest("label")?.textContent).toContain("目前位置");
    expect(radio(/English/).closest("label")?.textContent).toContain("目前位置");

    fireEvent.click(screen.getByRole("button", { name: "移到這裡" }));

    await waitFor(() => expect(props.onConfirm).toHaveBeenCalledWith("zh"));
  });

  it("labels hidden categories in the list", () => {
    renderModal();

    expect(radio(/English/).closest("label")?.textContent).toContain("已隱藏");
  });

  it("confirms the chosen category", async () => {
    const { props } = renderModal();

    fireEvent.click(radio(/English/));
    fireEvent.click(screen.getByRole("button", { name: "移到這裡" }));

    await waitFor(() => expect(props.onConfirm).toHaveBeenCalledWith("en"));
  });

  it("confirms 最上層 as null", async () => {
    const { props } = renderModal();

    fireEvent.click(radio(/最上層/));
    fireEvent.click(screen.getByRole("button", { name: "移到這裡" }));

    await waitFor(() => expect(props.onConfirm).toHaveBeenCalledWith(null));
  });

  it("stays open and says why when the move fails", async () => {
    const { props } = renderModal({
      onConfirm: vi.fn().mockRejectedValue(new Error("伺服器忙碌")),
    });

    fireEvent.click(radio(/English/));
    fireEvent.click(screen.getByRole("button", { name: "移到這裡" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("沒有移動成功");
    expect(alert.textContent).toContain("伺服器忙碌");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(props.onClose).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "移到這裡" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("closes with Escape, the cancel button, and a click on the backdrop", () => {
    const { props } = renderModal();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(props.onClose).toHaveBeenCalledTimes(2);

    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
    fireEvent.pointerDown(backdrop);
    fireEvent.pointerUp(backdrop);
    expect(props.onClose).toHaveBeenCalledTimes(3);
  });

  it("focuses the current choice, and gives focus back when it closes", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = renderModal();
    expect(document.activeElement).toBe(radio(/中文/));

    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
