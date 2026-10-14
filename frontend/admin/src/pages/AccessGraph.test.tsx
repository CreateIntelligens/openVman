import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  listAccounts,
  type Account,
} from "../api/auth";
import { NavigationProvider } from "../context/NavigationContext";
import AccessGraph from "./AccessGraph";

vi.mock("../api/auth", () => ({
  fetchAccountAccessOptions: vi.fn(),
  fetchAdminScope: vi.fn(),
  listAccounts: vi.fn(),
}));

const accounts: Account[] = [
  {
    id: "root-1",
    username: "ai360",
    role: "root",
    disabled: false,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
  {
    id: "admin-1",
    username: "pm-admin",
    role: "admin",
    disabled: false,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
  {
    id: "user-1",
    username: "clerk",
    role: "user",
    disabled: false,
    created_by: "admin-1",
    admin_portal_access: true,
    created_at: "2026-10-01T00:00:00Z",
    grants: {
      projects: ["p-hk", "p-demo"],
      avatar_characters: ["c-1"],
      custom_voices: ["v-1"],
      asr_engines: [],
    },
    defaults: {
      project_id: "p-hk",
      character_id: "c-1",
      voice_provider: "voxcpm",
      voice_id: "v-1",
    },
  },
  {
    id: "user-2",
    username: "retired",
    role: "user",
    disabled: true,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
];

function renderPage(onSelectTab = vi.fn()) {
  render(
    <NavigationProvider currentTab="AccessGraph" onSelectTab={onSelectTab}>
      <AccessGraph />
    </NavigationProvider>,
  );
  return onSelectTab;
}

describe("AccessGraph page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAccounts).mockResolvedValue(accounts);
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue({
      projects: [
        { id: "p-hk", label: "鶴記" },
        { id: "p-demo", label: "展示" },
      ],
      avatar_characters: [{ id: "c-1", label: "小鶴" }],
      custom_voices: [{ id: "v-1", label: "女聲", provider: "voxcpm" }],
      asr_engines: [],
    });
    vi.mocked(fetchAdminScope).mockResolvedValue({
      user_id: "admin-1",
      scoped: true,
      resources: {
        projects: ["p-demo"],
        avatar_characters: [],
        custom_voices: [],
        avatar_mascots: [],
        avatar_backgrounds: [],
      },
    });
  });

  it("renders accounts and projects as nodes with a summary", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: /帳號 clerk/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /帳號 ai360，ROOT，ROOT：全部/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /專案 鶴記/ })).toBeTruthy();
    expect(screen.getByText("4 個帳號 · 2 個專案 · 3 條專案連線")).toBeTruthy();
    expect(fetchAdminScope).toHaveBeenCalledWith("admin-1");
    expect(document.querySelectorAll('[data-edge-kind="scope"]').length).toBe(1);
    expect(document.querySelectorAll('[data-edge-kind="default"]').length).toBe(2);
  });

  it("opens account details on selection and links to account management", async () => {
    const onSelectTab = renderPage();

    const node = await screen.findByRole("button", { name: /帳號 clerk/ });
    fireEvent.keyDown(node, { key: "Enter" });

    const panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByRole("heading", { name: "clerk" })).toBeTruthy();
    expect(within(panel).getByText("依授權清單")).toBeTruthy();
    expect(within(panel).getByText("可進管理後台")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /鶴記/ }).textContent).toContain("預設");

    fireEvent.click(within(panel).getByRole("button", { name: /到帳號管理編輯/ }));
    expect(onSelectTab).toHaveBeenCalledWith("Accounts", "manage");
  });

  it("finds a project through search and lists who can reach it", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    fireEvent.change(screen.getByRole("combobox", { name: "搜尋節點" }), {
      target: { value: "展示" },
    });
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("button", { name: /展示/ }));

    const panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByRole("heading", { name: "展示" })).toBeTruthy();
    expect(within(panel).getByText("依授權清單（1）")).toBeTruthy();
    expect(within(panel).getByText("依管理範圍（1）")).toBeTruthy();
    expect(within(panel).getByText("ai360")).toBeTruthy();
  });

  it("toggles resource layers and disabled accounts", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    expect(screen.queryByRole("button", { name: /聲音 女聲/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^聲音/ }));
    expect(screen.getByRole("button", { name: /聲音 女聲/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^停用帳號/ }));
    expect(screen.queryByRole("button", { name: /帳號 retired/ })).toBeNull();
  });

  it("shows the error when the account list fails", async () => {
    vi.mocked(listAccounts).mockRejectedValue(new Error("這個帳號沒有權限做這件事。"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("沒有權限"));
  });
});
