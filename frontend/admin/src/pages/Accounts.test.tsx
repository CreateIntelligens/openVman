import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Accounts from "./Accounts";
import {
  createAccount,
  fetchAccountAccessOptions,
  listAccounts,
  resetAccountPassword,
  updateAccountRole,
  type Account,
} from "../api/auth";

const authState = vi.hoisted(() => ({
  account: {
    id: "admin-a",
    username: "admin",
    role: "admin" as "root" | "admin" | "user",
  },
}));

vi.mock("../api/auth", () => ({
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  fetchAccountAccessOptions: vi.fn(),
  listAccounts: vi.fn(),
  resetAccountPassword: vi.fn(),
  revokeAccountSessions: vi.fn(),
  setAccountDisabled: vi.fn(),
  updateAccountRole: vi.fn(),
  updateAccountAccess: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("../components/accounts/FormalAccountAccessPanel", () => ({
  default: () => null,
}));

vi.mock("../components/accounts/TemporaryBatchPanel", () => ({
  default: () => <section>臨時帳號批次</section>,
}));

describe("Accounts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.account = {
      id: "admin-a",
      username: "admin",
      role: "admin",
    };
    vi.mocked(listAccounts).mockResolvedValue([]);
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue({
      projects: [{ id: "project-a", label: "專案 A" }],
      avatar_characters: [{ id: "character-a", label: "人物 A" }],
      custom_voices: [
        { id: "voice-a", label: "聲音 A", provider: "indextts" },
      ],
    });
    vi.mocked(createAccount).mockResolvedValue({
      id: "user-a",
      username: "alice",
      role: "user",
      kind: "formal",
      disabled: false,
      created_at: "2026-08-18T00:00:00Z",
    });
  });

  it("selects access before creating a formal user", async () => {
    render(<Accounts />);

    fireEvent.change(screen.getByLabelText("帳號"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密碼"), {
      target: { value: "correct horse battery staple" },
    });
    const submit = await screen.findByRole("button", {
      name: "建立正式帳號",
    });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(createAccount).toHaveBeenCalledWith({
      username: "alice",
      password: "correct horse battery staple",
      role: "user",
      access: {
        grants: {
          projects: ["project-a"],
          avatar_characters: ["character-a"],
          custom_voices: ["voice-a"],
          avatar_mascots: [],
          avatar_backgrounds: [],
        },
        defaults: {
          project_id: "project-a",
          character_id: "character-a",
          voice_provider: "indextts",
          voice_id: "voice-a",
          mascot_id: "",
          background_id: "",
        },
      },
    }));
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledTimes(2);
      expect(fetchAccountAccessOptions).toHaveBeenCalledTimes(2);
    });
  });

  it("shows one account creation flow at a time", async () => {
    render(<Accounts />);

    expect(screen.getByText("新增正式帳號")).toBeTruthy();
    expect(screen.queryByText("臨時帳號批次")).toBeNull();
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledOnce();
      expect(fetchAccountAccessOptions).toHaveBeenCalledOnce();
    });

    fireEvent.click(screen.getByRole("button", { name: /臨時帳號/ }));

    expect(screen.queryByText("新增正式帳號")).toBeNull();
    expect(screen.getByText("臨時帳號批次")).toBeTruthy();
  });

  it("lets ROOT create an administrator without scoped access", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    vi.mocked(createAccount).mockResolvedValue(
      formalAccount("admin-b", "operator", "admin"),
    );

    render(<Accounts />);
    fireEvent.change(screen.getByLabelText("帳號"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("密碼"), {
      target: { value: "operator-password" },
    });
    fireEvent.change(screen.getByLabelText("角色"), {
      target: { value: "admin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "建立正式帳號" }));

    await waitFor(() => expect(createAccount).toHaveBeenCalledWith({
      username: "operator",
      password: "operator-password",
      role: "admin",
    }));
  });

  it("shows ROOT controls for lower accounts but no self-destructive controls", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    vi.mocked(listAccounts).mockResolvedValue([
      formalAccount("root-a", "ai360", "root"),
      formalAccount("admin-b", "operator", "admin"),
      formalAccount("user-b", "viewer", "user"),
    ]);

    render(<Accounts />);

    expect(await screen.findByText("ROOT")).toBeTruthy();
    expect(screen.getByRole("option", { name: "管理員" })).toBeTruthy();

    const rootRow = screen.getByText("ai360").closest("article");
    const adminRow = screen.getByText("operator").closest("article");
    const userRow = screen.getByText("viewer").closest("article");
    expect(rootRow?.querySelectorAll("button")).toHaveLength(0);
    expect(rowButtonLabels(adminRow)).toEqual([
      "變更角色",
      "重設密碼",
      "停用",
      "登出所有裝置",
      "刪除",
    ]);
    expect(rowButtonLabels(userRow)).toEqual([
      "資源權限",
      "變更角色",
      "重設密碼",
      "停用",
      "登出所有裝置",
      "刪除",
    ]);
  });

  it("hides privileged creation and mutation controls from administrators", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      formalAccount("root-a", "ai360", "root"),
      formalAccount("admin-a", "admin", "admin"),
      formalAccount("admin-b", "operator", "admin"),
      formalAccount("user-b", "viewer", "user"),
    ]);

    render(<Accounts />);

    await screen.findByText("ROOT");
    expect(screen.queryByRole("option", { name: "管理員" })).toBeNull();
    expect(rowButtonLabels(rowByUsername("ai360"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("admin"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("operator"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("viewer"))).toEqual([
      "資源權限",
      "停用",
      "登出所有裝置",
      "刪除",
    ]);
  });

  it("recovers from a denied role change without optimistic state", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    const user = formalAccount("user-b", "viewer", "user");
    vi.mocked(listAccounts).mockResolvedValue([user]);
    vi.mocked(updateAccountRole)
      .mockRejectedValueOnce(new Error("角色變更已被伺服器拒絕"))
      .mockResolvedValueOnce({ ...user, role: "admin" });

    render(<Accounts />);
    const row = (await screen.findByText("viewer")).closest("article");
    clickRowButton(row, "變更角色");
    fireEvent.click(screen.getByRole("button", { name: "確認變更角色" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "角色變更已被伺服器拒絕",
    );
    expect(row?.textContent).toContain("user");

    fireEvent.click(screen.getByRole("button", { name: "確認變更角色" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(row?.textContent).toContain("admin");
    });
  });

  it("sends complete scoped access when ROOT demotes an administrator", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    const admin = formalAccount("admin-b", "operator", "admin");
    vi.mocked(listAccounts).mockResolvedValue([admin]);
    vi.mocked(updateAccountRole).mockResolvedValue({
      ...formalAccount("admin-b", "operator", "user"),
    });

    render(<Accounts />);
    clickRowButton(
      (await screen.findByText("operator")).closest("article"),
      "變更角色",
    );
    const submit = screen.getByRole("button", { name: "確認變更角色" });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(updateAccountRole).toHaveBeenCalledWith(
      "admin-b",
      {
        role: "user",
        access: {
          grants: {
            projects: ["project-a"],
            avatar_characters: ["character-a"],
            custom_voices: ["voice-a"],
            avatar_mascots: [],
            avatar_backgrounds: [],
          },
          defaults: {
            project_id: "project-a",
            character_id: "character-a",
            voice_provider: "indextts",
            voice_id: "voice-a",
            mascot_id: "",
            background_id: "",
          },
        },
      },
    ));
  });

  it("keeps a failed reset editable and clears the password after success", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    const user = formalAccount("user-b", "viewer", "user");
    vi.mocked(listAccounts).mockResolvedValue([user]);
    vi.mocked(resetAccountPassword)
      .mockRejectedValueOnce(new Error("新密碼不符合規則"))
      .mockResolvedValueOnce(user);

    render(<Accounts />);
    const row = (await screen.findByText("viewer")).closest("article");
    clickRowButton(row, "重設密碼");
    const password = screen.getByLabelText("新密碼") as HTMLInputElement;
    const confirmation = screen.getByLabelText(
      "再次輸入新密碼",
    ) as HTMLInputElement;
    fireEvent.change(password, { target: { value: "valid-password" } });
    fireEvent.change(confirmation, { target: { value: "valid-password" } });
    fireEvent.click(screen.getByRole("button", { name: "確認重設" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "新密碼不符合規則",
    );
    expect(password.value).toBe("valid-password");
    expect(confirmation.value).toBe("valid-password");

    fireEvent.click(screen.getByRole("button", { name: "確認重設" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(resetAccountPassword).toHaveBeenCalledTimes(2);

    clickRowButton(row, "重設密碼");
    expect((screen.getByLabelText("新密碼") as HTMLInputElement).value).toBe("");
    expect(
      (screen.getByLabelText("再次輸入新密碼") as HTMLInputElement).value,
    ).toBe("");
  });
});

function formalAccount(
  id: string,
  username: string,
  role: Account["role"],
): Account {
  return {
    id,
    username,
    role,
    kind: "formal",
    disabled: false,
    created_at: "2026-08-18T00:00:00Z",
    grants: role === "user"
      ? {
        projects: ["project-a"],
        avatar_characters: ["character-a"],
        custom_voices: ["voice-a"],
      }
      : null,
    defaults: role === "user"
      ? {
        project_id: "project-a",
        character_id: "character-a",
        voice_provider: "indextts",
        voice_id: "voice-a",
      }
      : null,
  };
}

function rowButtonLabels(row: Element | null): string[] {
  return Array.from(row?.querySelectorAll("button") ?? []).map(
    (button) => button.textContent?.trim() ?? "",
  );
}

function rowByUsername(username: string): Element | null {
  const label = screen.getAllByText(username).find(
    (candidate) => candidate.classList.contains("font-medium"),
  );
  if (!label) throw new Error(`找不到帳號列：${username}`);
  return label.closest("article");
}

function clickRowButton(row: Element | null, label: string): void {
  const button = Array.from(row?.querySelectorAll("button") ?? []).find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`找不到操作按鈕：${label}`);
  }
  fireEvent.click(button);
}
