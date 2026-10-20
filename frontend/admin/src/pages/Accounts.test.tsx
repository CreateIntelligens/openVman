import { useEffect, useState, type ReactElement } from "react";
import { NavigationProvider } from "../context/NavigationContext";
import { buildAdminPath, parseAdminRoute } from "../components/app/navigation";
import {
  fireEvent,
  render as renderComponent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Accounts from "./Accounts";
import {
  createAccount,
  updateAdminScope,
  deleteAccount,
  fetchAccountAccessOptions,
  listAccounts,
  resetAccountPassword,
  revokeAccountSessions,
  setAccountDisabled,
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
  isAtLeastAdmin: (role: string) => role === "admin" || role === "root",
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  fetchAccountAccessOptions: vi.fn(),
  listAccounts: vi.fn(),
  resetAccountPassword: vi.fn(),
  revokeAccountSessions: vi.fn(),
  setAccountDisabled: vi.fn(),
  updateAccountRole: vi.fn(),
  updateAccountAccess: vi.fn(),
  updateAdminScope: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => authState,
}));

const guard = vi.hoisted(() => ({ block: false, requests: 0 }));

vi.mock("../context/NavigationGuardContext", () => ({
  // 守衛本身在 NavigationGuardContext.test 驗；這裡預設放行，block 時模擬使用者按了「留下」。
  useNavigationGuard: () => ({
    hasUnsavedChanges: guard.block,
    requestNavigation: (go: () => void) => {
      guard.requests += 1;
      if (guard.block) return false;
      go();
      return true;
    },
  }),
  useUnsavedChanges: () => {},
}));

vi.mock("../components/accounts/FormalAccountAccessPanel", () => ({
  default: () => null,
}));

vi.mock("../components/accounts/AdminScopePanel", () => ({
  default: () => <section>資源上限面板</section>,
}));

vi.mock("../components/accounts/TemporaryBatchPanel", () => ({
  default: ({ view }: { view: "create" | "manage" }) => (
    <section>{view === "create" ? "臨時帳號批次" : "批次紀錄"}</section>
  ),
}));

function render(element: ReactElement) {
  function RouteHarness() {
    const [view, setView] = useState(() => parseAdminRoute(window.location.pathname, window.location.search)?.subView);
    useEffect(() => {
      const update = () => setView(parseAdminRoute(window.location.pathname, window.location.search)?.subView);
      window.addEventListener("popstate", update);
      return () => window.removeEventListener("popstate", update);
    }, []);
    return <NavigationProvider currentTab="Access" currentSubView={view} onSelectTab={(tab, next) => {
      window.history.pushState(null, "", buildAdminPath(tab, "default", next));
      setView(next);
    }}>{element}</NavigationProvider>;
  }
  return renderComponent(<RouteHarness />);
}

describe("Accounts", () => {
  beforeEach(() => {
  window.history.replaceState(null, "", "/admin/access/accounts");
    vi.clearAllMocks();
    guard.block = false;
    guard.requests = 0;
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

  it("opens management directly from its URL", async () => {
    window.history.replaceState(null, "", "/admin/access/accounts/manage");
    render(<Accounts />);
    expect(screen.getByRole("tab", { name: "編輯／管理" }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("批次紀錄")).toBeTruthy();
  });

  it("opens temporary creation directly and synchronizes mode changes", async () => {
    window.history.replaceState(null, "", "/admin/access/accounts/temporary");
    render(<Accounts />);
    expect(await screen.findByText("臨時帳號批次")).toBeTruthy();
    expect(screen.getByRole("button", { name: "臨時帳號" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "正式帳號" }));
    expect(window.location.pathname).toBe("/admin/access/accounts");
    fireEvent.click(screen.getByRole("button", { name: "臨時帳號" }));
    expect(window.location.pathname).toBe("/admin/access/accounts/temporary");
  });

  it("lets ROOT set an admin's scope while creating the account", async () => {
    authState.account = { id: "root-1", username: "root", role: "root" };
    vi.mocked(createAccount).mockResolvedValue({ id: "admin-new", username: "jane", role: "admin" } as never);
    render(<Accounts />);
    await screen.findByText(/可檢視並編輯下方授權的專案/);

    fireEvent.change(screen.getByLabelText("帳號"), { target: { value: "jane" } });
    fireEvent.change(screen.getByLabelText("密碼"), { target: { value: "correct horse battery staple" } });
    fireEvent.change(screen.getByLabelText("角色"), { target: { value: "admin" } });
    expect(await screen.findByText("資源上限")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/限制可用資源/));
    // 登入預設值那段也列同一個專案；要勾的是「資源上限」區塊裡的那個。
    const scopeSection = screen.getByRole("region", { name: "資源上限" });
    fireEvent.click(within(scopeSection).getByLabelText("專案 A"));

    const submit = screen.getByRole("button", { name: "建立正式帳號" });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(createAccount).toHaveBeenCalled());
    expect(vi.mocked(createAccount).mock.calls[0][0].role).toBe("admin");
    await waitFor(() => expect(updateAdminScope).toHaveBeenCalledWith("admin-new", {
      scoped: true,
      resources: expect.objectContaining({ projects: ["project-a"] }),
    }));
  });

  it("selects access before creating a formal user", async () => {
    render(<Accounts />);

    expect(
      await screen.findByText(/可檢視並編輯下方授權的專案/),
    ).toBeTruthy();

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
          asr_engines: [],
        },
        defaults: {
          project_id: "project-a",
          character_id: "character-a",
          voice_provider: "indextts",
          voice_id: "voice-a",
          mascot_id: "",
          background_id: "",
        },
        admin_portal_access: false,
        kiosk: false,
      },
    }));
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledTimes(2);
      expect(fetchAccountAccessOptions).toHaveBeenCalledTimes(2);
    });
  });

  it("creates a kiosk account when the 展示機台 box is checked", async () => {
    render(<Accounts />);

    const kiosk = await screen.findByRole("checkbox", {
      name: /展示機台：登入後自動進入訪客模式（藏起設定與登出）/,
    });
    expect((kiosk as HTMLInputElement).checked).toBe(false);
    fireEvent.click(kiosk);
    expect((kiosk as HTMLInputElement).checked).toBe(true);

    fireEvent.change(screen.getByLabelText("帳號"), {
      target: { value: "lobby" },
    });
    fireEvent.change(screen.getByLabelText("密碼"), {
      target: { value: "correct horse battery staple" },
    });
    const submit = await screen.findByRole("button", {
      name: "建立正式帳號",
    });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(createAccount).toHaveBeenCalledWith(
      expect.objectContaining({
        username: "lobby",
        access: expect.objectContaining({ kiosk: true }),
      }),
    ));
  });

  it("badges kiosk accounts in the account list", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      { ...formalAccount("user-k", "lobby", "user", "admin-a"), kiosk: true },
      formalAccount("user-a", "alice", "user", "admin-a"),
    ]);

    render(<Accounts />);
    switchToManageTab();

    const kioskRow = (await screen.findByText("lobby")).closest("article");
    const plainRow = screen.getByText("alice").closest("article");
    expect(kioskRow?.textContent).toContain("展示機台");
    expect(plainRow?.textContent).not.toContain("展示機台");
  });

  it("shows one account creation flow at a time", async () => {
    render(<Accounts />);

    expect(screen.getByText("新增正式帳號")).toBeTruthy();
    expect(screen.queryByText("臨時帳號批次")).toBeNull();
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledOnce();
      expect(fetchAccountAccessOptions).toHaveBeenCalledOnce();
    });

    fireEvent.click(screen.getByRole("button", { name: /^臨時帳號/ }));

    expect(screen.queryByText("新增正式帳號")).toBeNull();
    expect(screen.getByText("臨時帳號批次")).toBeTruthy();
  });

  it("a scoped admin creating an admin always writes a scope, preselected to what the creator sees", async () => {
    vi.mocked(createAccount).mockResolvedValue({ id: "admin-child", username: "kid", role: "admin" } as never);
    render(<Accounts />);
    await screen.findByText(/可檢視並編輯下方授權的專案/);
    fireEvent.change(screen.getByLabelText("帳號"), { target: { value: "kid" } });
    fireEvent.change(screen.getByLabelText("密碼"), { target: { value: "correct horse battery staple" } });
    fireEvent.change(screen.getByLabelText("角色"), { target: { value: "admin" } });
    const scopeBox = (await screen.findByLabelText(/限制可用資源/)) as HTMLInputElement;
    await waitFor(() => expect(scopeBox.checked).toBe(true));
    expect(scopeBox.disabled).toBe(true);
    const submit = screen.getByRole("button", { name: "建立正式帳號" });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);
    await waitFor(() => expect(updateAdminScope).toHaveBeenCalledWith("admin-child", {
      scoped: true,
      resources: expect.objectContaining({ projects: ["project-a"], avatar_characters: ["character-a"] }),
    }));
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

    // 管理員也帶登入預設值（access），但不設資源上限。
    await waitFor(() => expect(createAccount).toHaveBeenCalledWith(expect.objectContaining({
      username: "operator",
      password: "operator-password",
      role: "admin",
    })));
    expect(updateAdminScope).not.toHaveBeenCalled();
  });

  it("switches cleanly between create account and account management tabs", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      formalAccount("user-a", "alice", "user"),
    ]);

    render(<Accounts />);

    expect(screen.getByText("新增正式帳號")).toBeTruthy();
    expect(screen.queryByText("正式帳號列表")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /^編輯／管理/ }));
    expect(await screen.findByText("正式帳號列表")).toBeTruthy();
    expect(screen.queryByText("新增正式帳號")).toBeNull();
    expect(screen.getByText("alice")).toBeTruthy();
    expect(screen.getByText("批次紀錄")).toBeTruthy();
    expect(screen.queryByText("臨時帳號批次")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "+ 建立新帳號" }));
    expect(screen.getByText("新增正式帳號")).toBeTruthy();
    expect(screen.queryByText("正式帳號列表")).toBeNull();
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

    expect(screen.getByRole("option", { name: "管理員" })).toBeTruthy();
    switchToManageTab();

    expect(await screen.findByText("ROOT")).toBeTruthy();

    const rootRow = screen.getByText("ai360").closest("article");
    const adminRow = screen.getByText("operator").closest("article");
    const userRow = screen.getByText("viewer").closest("article");
    expect(rootRow?.querySelectorAll("button")).toHaveLength(0);
    // 每列只攤開一個主要動作，其餘收進「更多動作」選單。
    expect(rowButtonLabels(adminRow)).toEqual(["資源權限", "更多動作：operator"]);
    expect(menuGroups(adminRow)).toEqual({
      // ROOT 才看得到的資源上限入口，只對管理員帳號出現。
      帳號設定: ["資源上限", "變更角色", "重設密碼"],
      安全與危險: ["登出所有裝置", "停用", "刪除"],
    });
    expect(rowButtonLabels(userRow)).toEqual(["資源權限", "更多動作：viewer"]);
    expect(menuGroups(userRow)).toEqual({
      帳號設定: ["變更角色", "重設密碼"],
      安全與危險: ["登出所有裝置", "停用", "刪除"],
    });
  });

  it("keeps ROOT-only controls away from administrators", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      formalAccount("root-a", "ai360", "root"),
      formalAccount("admin-a", "admin", "admin"),
      formalAccount("admin-b", "operator", "admin", "root-a"),
      formalAccount("user-b", "viewer", "user", "root-a"),
    ]);

    render(<Accounts />);
    switchToManageTab();

    await screen.findByText("ROOT");
    // 子樹裡看得到，但不是自己建立的就動不了。
    expect(rowButtonLabels(rowByUsername("ai360"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("admin"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("operator"))).toEqual([]);
    expect(rowButtonLabels(rowByUsername("viewer"))).toEqual([]);
  });

  it("lets an administrator manage the accounts it created, admins included", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      formalAccount("admin-a", "admin", "admin"),
      formalAccount("admin-c", "delegate", "admin", "admin-a"),
      formalAccount("user-c", "own-user", "user", "admin-a"),
    ]);

    render(<Accounts />);
    // 委派鏈要起得來，admin 得開得出 admin。
    expect(screen.queryByRole("option", { name: "管理員" })).not.toBeNull();
    switchToManageTab();

    await screen.findByText("delegate");
    // 變更角色／重設密碼仍是 ROOT 專屬，不出現在這裡。
    expect(rowButtonLabels(rowByUsername("delegate"))).toEqual([
      "資源權限",
      "更多動作：delegate",
    ]);
    expect(menuGroups(rowByUsername("delegate"))).toEqual({
      帳號設定: ["資源上限"],
      安全與危險: ["登出所有裝置", "停用", "刪除"],
    });
    // 一般使用者沒有資源上限，帳號設定整組為空就不顯示。
    expect(menuGroups(rowByUsername("own-user"))).toEqual({
      安全與危險: ["登出所有裝置", "停用", "刪除"],
    });
  });

  it("lets ROOT pick the target role and blocks a no-op change", async () => {
    authState.account = {
      id: "root-a",
      username: "ai360",
      role: "root",
    };
    const user = formalAccount("user-b", "viewer", "user");
    vi.mocked(listAccounts).mockResolvedValue([user]);

    render(<Accounts />);
    switchToManageTab();
    clickRowButton(
      (await screen.findByText("viewer")).closest("article"),
      "變更角色",
    );

    const select = screen.getByLabelText(/變更為/) as HTMLSelectElement;
    const submit = screen.getByRole("button", { name: "確認變更角色" });

    // 預設跳到另一個角色，直接送出即可。
    expect(select.value).toBe("admin");
    expect(submit.hasAttribute("disabled")).toBe(false);

    // 選回目前角色是空操作，要擋下來而不是送出去。
    fireEvent.change(select, { target: { value: "user" } });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(true));
    expect(updateAccountRole).not.toHaveBeenCalled();
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
    switchToManageTab();
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
    switchToManageTab();
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
            asr_engines: [],
          },
          defaults: {
            project_id: "project-a",
            character_id: "character-a",
            voice_provider: "indextts",
            voice_id: "voice-a",
            mascot_id: "",
            background_id: "",
          },
          admin_portal_access: false,
          kiosk: false,
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
    switchToManageTab();
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

  describe("row menu", () => {
    beforeEach(() => {
      authState.account = { id: "root-a", username: "ai360", role: "root" };
    });

    it("opens with the first item focused and walks items with the keyboard", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        formalAccount("admin-b", "operator", "admin"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      const row = (await screen.findByText("operator")).closest("article");
      const trigger = menuTrigger(row);
      expect(trigger.getAttribute("aria-expanded")).toBe("false");

      fireEvent.keyDown(trigger, { key: "ArrowDown" });
      const menu = within(row as HTMLElement).getByRole("menu");
      const items = within(menu).getAllByRole("menuitem");
      expect(trigger.getAttribute("aria-expanded")).toBe("true");
      await waitFor(() => expect(document.activeElement).toBe(items[0]));

      fireEvent.keyDown(menu, { key: "ArrowDown" });
      expect(document.activeElement).toBe(items[1]);
      fireEvent.keyDown(menu, { key: "End" });
      expect(document.activeElement).toBe(items[items.length - 1]);
      // 到底再往下會繞回第一項。
      fireEvent.keyDown(menu, { key: "ArrowDown" });
      expect(document.activeElement).toBe(items[0]);
      fireEvent.keyDown(menu, { key: "ArrowUp" });
      expect(document.activeElement).toBe(items[items.length - 1]);
      fireEvent.keyDown(menu, { key: "Home" });
      expect(document.activeElement).toBe(items[0]);

      fireEvent.keyDown(menu, { key: "Escape" });
      expect(within(row as HTMLElement).queryByRole("menu")).toBeNull();
      expect(document.activeElement).toBe(trigger);
      expect(trigger.getAttribute("aria-expanded")).toBe("false");
    });

    it("opens on ArrowUp at the last item and closes on an outside click", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        formalAccount("user-b", "viewer", "user"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      const row = (await screen.findByText("viewer")).closest("article");
      const trigger = menuTrigger(row);

      fireEvent.keyDown(trigger, { key: "ArrowUp" });
      const items = within(row as HTMLElement).getAllByRole("menuitem");
      await waitFor(() => expect(document.activeElement).toBe(items[items.length - 1]));

      // 點選單裡面不會關。
      fireEvent.pointerDown(within(row as HTMLElement).getByRole("menu"));
      expect(within(row as HTMLElement).queryByRole("menu")).not.toBeNull();
      fireEvent.pointerDown(document.body);
      expect(within(row as HTMLElement).queryByRole("menu")).toBeNull();
    });

    it("still runs disable, revoke and delete from the menu", async () => {
      const active = formalAccount("user-b", "viewer", "user");
      const disabled = { ...formalAccount("user-c", "retired", "user"), disabled: true };
      vi.mocked(listAccounts).mockResolvedValue([active, disabled]);
      vi.mocked(setAccountDisabled).mockResolvedValue({ ...active, disabled: true });
      vi.mocked(revokeAccountSessions).mockResolvedValue(undefined);
      vi.mocked(deleteAccount).mockResolvedValue(undefined);
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

      render(<Accounts />);
      switchToManageTab();
      const activeRow = (await screen.findByText("viewer")).closest("article");

      clickRowButton(activeRow, "停用");
      await waitFor(() => expect(setAccountDisabled).toHaveBeenCalledWith("user-b", true));
      expect(within(activeRow as HTMLElement).queryByRole("menu")).toBeNull();
      expect(document.activeElement).toBe(menuTrigger(activeRow));

      clickRowButton(activeRow, "登出所有裝置");
      await waitFor(() => expect(revokeAccountSessions).toHaveBeenCalledWith("user-b"));

      // 還沒停用的帳號：刪除看得到但不能按，原因直接寫在項目下。
      const activeMenu = openRowMenu(activeRow);
      const blockedDelete = within(activeMenu).getByRole("menuitem", { name: /^刪除/ });
      expect(blockedDelete.getAttribute("aria-disabled")).toBe("true");
      expect(blockedDelete.textContent).toContain("需先停用帳號才可刪除");
      fireEvent.click(blockedDelete);
      expect(confirm).not.toHaveBeenCalled();
      expect(deleteAccount).not.toHaveBeenCalled();
      fireEvent.keyDown(activeMenu, { key: "Escape" });

      const disabledRow = rowByUsername("retired");
      clickRowButton(disabledRow, "啟用");
      await waitFor(() => expect(setAccountDisabled).toHaveBeenCalledWith("user-c", false));
      clickRowButton(disabledRow, "刪除");
      expect(confirm).toHaveBeenCalledWith("確定刪除帳號「retired」？");
      await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith("user-c"));
      confirm.mockRestore();
    });

    it("asks before collapsing an admin scope panel that has unsaved changes", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        formalAccount("admin-b", "operator", "admin"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      const row = (await screen.findByText("operator")).closest("article");
      clickRowButton(row, "資源上限");
      expect(await screen.findByText("資源上限面板")).toBeTruthy();

      guard.block = true;
      clickRowButton(row, "收起資源上限");

      expect(guard.requests).toBeGreaterThan(0);
      expect(screen.getByText("資源上限面板")).toBeTruthy();
    });

    it("keeps the row being edited when a search would filter it out", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        formalAccount("admin-b", "operator", "admin"),
        formalAccount("user-c", "carol", "user"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      const row = (await screen.findByText("operator")).closest("article");
      clickRowButton(row, "資源上限");
      expect(await screen.findByText("資源上限面板")).toBeTruthy();

      fireEvent.change(screen.getByRole("searchbox", { name: "搜尋帳號" }), {
        target: { value: "carol" },
      });

      expect(screen.getByText("carol")).toBeTruthy();
      expect(screen.getByText("operator")).toBeTruthy();
      expect(screen.getByText("資源上限面板")).toBeTruthy();
    });

    it("toggles the admin scope panel from the menu", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        formalAccount("admin-b", "operator", "admin"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      const row = (await screen.findByText("operator")).closest("article");

      clickRowButton(row, "資源上限");
      expect(await screen.findByText("資源上限面板")).toBeTruthy();
      clickRowButton(row, "收起資源上限");
      expect(screen.queryByText("資源上限面板")).toBeNull();
    });
  });

  describe("activity", () => {
    beforeEach(() => {
      vi.useFakeTimers({ now: new Date("2026-10-15T12:00:00Z"), toFake: ["Date"] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows relative last login, never-logged-in and API key use", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        {
          ...formalAccount("user-a", "alice", "user", "admin-a"),
          last_login_at: "2026-10-12T12:00:00Z",
          api_key_last_used_at: "2026-10-15T09:00:00Z",
        },
        { ...formalAccount("user-b", "bob", "user", "admin-a"), last_login_at: null },
      ]);
      render(<Accounts />);
      switchToManageTab();

      const alice = rowByUsername((await screen.findByText("alice")).textContent ?? "");
      const login = within(alice as HTMLElement).getByText("3 天前");
      expect(login.tagName).toBe("TIME");
      expect(login.getAttribute("dateTime")).toBe("2026-10-12T12:00:00Z");
      expect(login.getAttribute("title")).toBe(
        new Date("2026-10-12T12:00:00Z").toLocaleString("zh-TW"),
      );
      expect(alice?.textContent).toContain("API 最近使用");
      expect(within(alice as HTMLElement).getByText("3 小時前")).toBeTruthy();

      const bob = rowByUsername("bob");
      expect(bob?.textContent).toContain("從未登入");
      expect(bob?.textContent).not.toContain("API 最近使用");
    });

    it("sorts the least recently used accounts first", async () => {
      vi.mocked(listAccounts).mockResolvedValue([
        { ...formalAccount("user-a", "alice", "user"), last_login_at: "2026-10-14T00:00:00Z" },
        {
          ...formalAccount("user-b", "bob", "user"),
          last_login_at: "2026-01-01T00:00:00Z",
          // API 仍在用，就不算閒置。
          api_key_last_used_at: "2026-10-15T00:00:00Z",
        },
        { ...formalAccount("user-c", "carol", "user"), last_login_at: "2026-05-01T00:00:00Z" },
        formalAccount("user-d", "dave", "user"),
      ]);
      render(<Accounts />);
      switchToManageTab();
      await screen.findByText("alice");

      const order = () => Array.from(document.querySelectorAll("article span.font-medium"))
        .map((element) => element.textContent);
      expect(order()).toEqual(["alice", "bob", "carol", "dave"]);
      fireEvent.change(screen.getByLabelText("排序"), { target: { value: "idle" } });
      expect(order()).toEqual(["dave", "carol", "alice", "bob"]);
    });
  });
});

function formalAccount(
  id: string,
  username: string,
  role: Account["role"],
  createdBy: string | null = null,
): Account {
  return {
    id,
    username,
    role,
    created_by: createdBy,
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
    (button) => button.getAttribute("aria-label") ?? button.textContent?.trim() ?? "",
  );
}

function rowByUsername(username: string): Element | null {
  const label = screen.getAllByText(username).find(
    (candidate) => candidate.classList.contains("font-medium"),
  );
  if (!label) throw new Error(`找不到帳號列：${username}`);
  return label.closest("article");
}

function menuTrigger(row: Element | null): HTMLButtonElement {
  const trigger = row?.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]');
  if (!trigger) throw new Error("找不到更多動作按鈕");
  return trigger;
}

function openRowMenu(row: Element | null): HTMLElement {
  fireEvent.click(menuTrigger(row));
  return within(row as HTMLElement).getByRole("menu");
}

/** 打開選單、讀出各組項目，再關掉，讓斷言不影響後續操作。 */
function menuGroups(row: Element | null): Record<string, string[]> {
  const menu = openRowMenu(row);
  const groups: Record<string, string[]> = {};
  for (const group of within(menu).getAllByRole("group")) {
    const heading = document.getElementById(group.getAttribute("aria-labelledby") ?? "");
    groups[heading?.textContent ?? ""] = within(group)
      .getAllByRole("menuitem")
      .map((item) => item.firstElementChild?.textContent?.trim() ?? "");
  }
  fireEvent.keyDown(menu, { key: "Escape" });
  return groups;
}

function clickRowButton(row: Element | null, label: string): void {
  const button = Array.from(row?.querySelectorAll("button") ?? []).find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  if (button instanceof HTMLButtonElement) {
    fireEvent.click(button);
    return;
  }
  const menu = openRowMenu(row);
  fireEvent.click(within(menu).getByRole("menuitem", { name: new RegExp(`^${label}`) }));
}

function switchToManageTab(): void {
  const manageTabBtn = screen.getByRole("tab", { name: /^編輯／管理/ });
  fireEvent.click(manageTabBtn);
}
