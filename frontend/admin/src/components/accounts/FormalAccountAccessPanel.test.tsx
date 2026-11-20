import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { fetchAccountAccessOptions, updateAccountAccess, type Account } from "../../api/auth";
import FormalAccountAccessPanel from "./FormalAccountAccessPanel";

vi.mock("../../api/auth", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/auth")>(),
  fetchAccountAccessOptions: vi.fn(),
  updateAccountAccess: vi.fn(),
}));

vi.mock("../../context/NavigationGuardContext", () => ({
  useUnsavedChanges: vi.fn(),
}));

it("edits and reopens network search access without overwriting preset project grants", async () => {
  const account: Account = {
    id: "vendor-1",
    username: "vendor",
    role: "user",
    disabled: false,
    created_at: "2026-11-20T00:00:00Z",
    preset: "vendor_editor",
    vendor_name: "合作廠商",
    admin_portal_access: true,
    grants: { projects: ["project-a"], avatar_characters: [], custom_voices: [] },
    defaults: null,
    web_search_access: false,
  };
  vi.mocked(fetchAccountAccessOptions).mockResolvedValue({
    projects: [{ id: "project-a", label: "廠商專案 A", vendor_name: "合作廠商" }],
    avatar_characters: [],
    custom_voices: [],
  });
  const saved = { ...account, web_search_access: true };
  vi.mocked(updateAccountAccess).mockResolvedValueOnce(saved).mockResolvedValueOnce(account);
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const view = render(<FormalAccountAccessPanel account={account} onSaved={onSaved} onCancel={onCancel} />);
  const checkbox = screen.getByRole("checkbox", { name: "可用網路搜尋" }) as HTMLInputElement;
  await waitFor(() => expect(checkbox.disabled).toBe(false));
  expect(checkbox.checked).toBe(false);
  expect(screen.getByText("沒勾的帳號，AI 只查知識庫，不上網搜尋。")).toBeTruthy();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "儲存權限" }));

  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
  expect(updateAccountAccess).toHaveBeenNthCalledWith(1, account.id, { web_search_access: true });
  view.unmount();

  render(<FormalAccountAccessPanel account={saved} onSaved={onSaved} onCancel={onCancel} />);
  const reopened = screen.getByRole("checkbox", { name: "可用網路搜尋" }) as HTMLInputElement;
  await waitFor(() => expect(reopened.checked).toBe(true));
  fireEvent.click(reopened);
  fireEvent.click(screen.getByRole("button", { name: "儲存權限" }));
  await waitFor(() => expect(updateAccountAccess).toHaveBeenNthCalledWith(2, account.id, { web_search_access: false }));
});
