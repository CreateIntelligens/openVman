import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MemoryPagination from "./MemoryPagination";

describe("MemoryPagination", () => {
  it("offers every last-window page once and identifies the active page", () => {
    const onPageChange = vi.fn();
    render(<MemoryPagination page={9} totalPages={10} onPageChange={onPageChange} />);

    const navigation = screen.getByRole("navigation", { name: "記憶分頁" });
    const pages = within(navigation).getAllByRole("button", { name: /^第 \d+ 頁$/ });
    expect(pages.map((button) => button.textContent)).toEqual(["4", "5", "6", "7", "8", "9", "10"]);
    expect(screen.getByRole("button", { name: "第 9 頁" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: "第 10 頁" }));
    expect(onPageChange).toHaveBeenLastCalledWith(10);
    fireEvent.click(screen.getByRole("button", { name: "上一頁" }));
    expect(onPageChange).toHaveBeenLastCalledWith(8);
  });

  it("disables the boundary actions and omits single-page navigation", () => {
    const onPageChange = vi.fn();
    const { rerender } = render(<MemoryPagination page={1} totalPages={10} onPageChange={onPageChange} />);
    expect((screen.getByRole("button", { name: "上一頁" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<MemoryPagination page={10} totalPages={10} onPageChange={onPageChange} />);
    expect((screen.getByRole("button", { name: "下一頁" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<MemoryPagination page={1} totalPages={1} onPageChange={onPageChange} />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
