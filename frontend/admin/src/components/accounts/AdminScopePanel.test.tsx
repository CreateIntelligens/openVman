import { fireEvent, render as renderComponent, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  updateAdminScope,
  type Account,
} from "../../api/auth";
import { NavigationGuardProvider, useNavigationGuard } from "../../context/NavigationGuardContext";
import AdminScopePanel from "./AdminScopePanel";

function GuardProbe() {
  const { hasUnsavedChanges } = useNavigationGuard();
  return <span>{hasUnsavedChanges ? "guard:dirty" : "guard:clean"}</span>;
}

function render(element: ReactElement) {
  return renderComponent(<NavigationGuardProvider>{element}<GuardProbe /></NavigationGuardProvider>);
}

vi.mock("../../api/auth", () => ({
  fetchAccountAccessOptions: vi.fn(),
  fetchAdminScope: vi.fn(),
  updateAdminScope: vi.fn(),
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ account: { id: "root-1", username: "root", role: "root" } }),
}));

const account = {
  id: "usr-admin",
  username: "timweng",
  role: "admin",
} as unknown as Account;

const options = {
  projects: [{ id: "esg-1", label: "ESG永續" }],
  avatar_characters: [],
  custom_voices: [],
  avatar_mascots: [],
  avatar_backgrounds: [],
  asr_engines: [],
};

beforeEach(() => {
  vi.mocked(fetchAccountAccessOptions).mockReset();
  vi.mocked(fetchAdminScope).mockReset();
  vi.mocked(updateAdminScope).mockReset();
});

describe("AdminScopePanel 載入失敗", () => {
  it("讀不到目前的上限就不准儲存，重新讀取成功後才開放", async () => {
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue(options);
    vi.mocked(fetchAdminScope)
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({
        user_id: "usr-admin",
        scoped: true,
        resources: {
          projects: ["esg-1"],
          avatar_characters: [],
          custom_voices: [],
          avatar_mascots: [],
          avatar_backgrounds: [],
          asr_engines: [],
        },
      });

    render(<AdminScopePanel account={account} onCancel={() => {}} onSaved={() => {}} />);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("network down"));
    const save = screen.getByRole("button", { name: "儲存上限" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(updateAdminScope).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    await waitFor(() => expect(save.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect((screen.getByLabelText(/限制可用資源/) as HTMLInputElement).checked).toBe(true);
  });
});


describe("AdminScopePanel 未儲存的修改", () => {
  it("改了限制模式就向離開防護登記，收合前會被攔下", async () => {
    // 2026-10-21 複查：只切本機的限制模式再按收合，面板直接消失沒有提醒。
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue(options);
    vi.mocked(fetchAdminScope).mockResolvedValue({
      user_id: "usr-admin",
      scoped: false,
      resources: {
        projects: [], avatar_characters: [], custom_voices: [],
        avatar_mascots: [], avatar_backgrounds: [], asr_engines: [],
      },
    });

    render(<AdminScopePanel account={account} onCancel={() => {}} onSaved={() => {}} />);

    const toggle = await screen.findByLabelText(/限制可用資源/);
    expect(screen.getByText("guard:clean")).toBeTruthy();
    fireEvent.click(toggle);
    expect(await screen.findByText("guard:dirty")).toBeTruthy();
    fireEvent.click(toggle);
    expect(await screen.findByText("guard:clean")).toBeTruthy();
  });
});
