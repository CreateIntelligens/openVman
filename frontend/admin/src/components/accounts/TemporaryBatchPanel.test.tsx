import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createTemporaryBatch,
  listTemporaryBatches,
  revokeTemporaryBatch,
  setTemporaryBatchAdminPortalAccess,
  type TemporaryBatchAudit,
} from "../../api/auth";
import TemporaryBatchPanel from "./TemporaryBatchPanel";

vi.mock("../../api/auth", () => ({
  createTemporaryBatch: vi.fn(),
  listTemporaryBatches: vi.fn(),
  revokeTemporaryBatch: vi.fn(),
  setTemporaryBatchAdminPortalAccess: vi.fn(),
}));

vi.mock("./AccountAccessFields", () => ({
  default: () => <div>批次資源授權表單</div>,
  useAccountAccessForm: () => ({
    complete: true,
    loading: false,
    error: null,
    access: { admin_portal_access: false },
    reload: vi.fn(),
  }),
}));

function batch(
  name: string,
  overrides: Partial<TemporaryBatchAudit> = {},
): TemporaryBatchAudit {
  return {
    batch_id: name,
    created_at: "2026-09-14T00:00:00Z",
    state: "unused",
    admin_portal_access: false,
    accounts: [{
      user_id: `${name}-user`,
      username: `tmp-${name}`,
      password: name,
      state: "unused",
      disabled: false,
      first_used_at: null,
      expires_at: null,
      remaining_seconds: null,
    }],
    ...overrides,
  };
}

const FILTER_LABELS: Record<string, string> = {
  all: "全部",
  unused: "尚未啟用",
  active: "使用中",
  expired: "已到期",
  revoked: "已撤銷",
};

function filterChip(state: string): HTMLElement {
  return within(screen.getByRole("group", { name: "批次狀態" })).getByRole("button", {
    name: new RegExp(`^${FILTER_LABELS[state]}\\d+$`),
  });
}

function filterBy(state: string) {
  fireEvent.click(filterChip(state));
}

function selectedFilter(): string | undefined {
  return Object.keys(FILTER_LABELS).find(
    (state) => filterChip(state).getAttribute("aria-pressed") === "true",
  );
}

/** 每組帳號收在批次列底下；用該批的密碼找到那一列再展開。 */
function expandBatch(password: string) {
  const row = screen.getByText(password).closest("article") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { expanded: false }));
}

describe("TemporaryBatchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTemporaryBatches).mockResolvedValue([]);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("defaults to creation and retains one-time passwords across view changes", async () => {
    const createdBatch = batch("created-batch");
    createdBatch.accounts![0].password = null;
    vi.mocked(listTemporaryBatches).mockResolvedValue([createdBatch]);
    vi.mocked(createTemporaryBatch).mockResolvedValue({
      batch_id: "created-batch",
      created_at: "2026-09-14T00:00:00Z",
      admin_portal_access: false,
      credentials: [{
        user_id: "created-batch-user",
        password: "one-time-test-password",
        expires_at: null,
      }],
    });
    const { rerender } = render(<TemporaryBatchPanel />);

    expect(screen.getByText("批次資源授權表單")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "批次紀錄" })).toBeNull();
    expect(screen.queryByRole("group", { name: "批次狀態" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "產生 5 組帳號" }));
    expect(await screen.findByText("one-time-test-password")).toBeTruthy();

    rerender(<TemporaryBatchPanel view="manage" />);
    // 剛產生的那批預設展開，不必再點一次才看得到密碼。
    expect((await screen.findByText("one-time-test-password")).closest("[hidden]")).toBeNull();
    expect(screen.getByRole("heading", { name: "批次紀錄" })).toBeTruthy();
    expect(screen.queryByText("批次資源授權表單")).toBeNull();
    expect(screen.queryByRole("button", { name: "產生 5 組帳號" })).toBeNull();
    expect(screen.queryByText("密碼未保存")).toBeNull();
    expect(screen.queryByText("tmp-created-batch")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "複製密碼" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("one-time-test-password"));

    rerender(<TemporaryBatchPanel view="create" />);
    expect(screen.getByText("one-time-test-password")).toBeTruthy();
    expect(screen.queryByText("created-batch")).toBeNull();
    expect(createTemporaryBatch).toHaveBeenCalledOnce();
  });

  it("badges kiosk batches in the history", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([
      batch("kiosk-batch", { kiosk: true }),
      batch("plain-batch"),
    ]);
    render(<TemporaryBatchPanel view="manage" />);

    const kioskRow = (await screen.findByText("kiosk-batch")).closest("article");
    const plainRow = screen.getByText("plain-batch").closest("article");
    expect(kioskRow?.textContent).toContain("展示機台");
    expect(plainRow?.textContent).not.toContain("展示機台");
  });

  it("collapses per-account details behind an accessible toggle", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([batch("collapsible", { state: "active" })]);
    render(<TemporaryBatchPanel view="manage" />);

    const password = await screen.findByText("collapsible");
    const row = password.closest("article") as HTMLElement;
    const toggle = within(row).getByRole("button", { expanded: false });
    const details = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(details?.contains(password)).toBe(true);
    expect(details?.hidden).toBe(true);
    expect(within(row).getByText("使用中")).toBeTruthy();
    expect(within(row).getByText("1 組帳號")).toBeTruthy();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(details?.hidden).toBe(false);
    expect(within(row).getByRole("button", { name: "複製密碼" })).toBeTruthy();

    fireEvent.click(toggle);
    expect(details?.hidden).toBe(true);
  });

  it("keeps a batch without account details readable instead of a disabled toggle", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([
      batch("no-details", { state: "expired", accounts: undefined, account_count: 5 }),
    ]);
    render(<TemporaryBatchPanel view="manage" />);

    const count = await screen.findByText("5 組帳號");
    const row = count.closest("article") as HTMLElement;
    expect(within(row).queryByRole("button", { expanded: false })).toBeNull();
    expect(count.closest("button")).toBeNull();
    expect(within(row).getByText("已到期", { selector: "span:not(.chip)" })).toBeTruthy();
  });

  it("hides batch actions once a batch is revoked", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([
      batch("live", { state: "active" }),
      batch("gone", { state: "active", revoked_at: "2026-09-14T02:00:00Z" }),
    ]);
    render(<TemporaryBatchPanel view="manage" />);

    const live = (await screen.findByText("live")).closest("article") as HTMLElement;
    const gone = screen.getByText("gone").closest("article") as HTMLElement;
    expect(within(live).getByRole("button", { name: "撤銷整批" })).toBeTruthy();
    expect(within(gone).queryByRole("button", { name: "撤銷整批" })).toBeNull();
    expect(within(gone).queryByRole("button", { name: /後台權限/ })).toBeNull();
    expect(within(gone).getByText(/^撤銷於/)).toBeTruthy();
  });

  it("shows a loading state on first load and an empty filter can be reset", async () => {
    let resolve: (value: TemporaryBatchAudit[]) => void = () => undefined;
    vi.mocked(listTemporaryBatches).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<TemporaryBatchPanel view="manage" />);
    expect(screen.getByRole("status").textContent).toContain("載入批次紀錄中");

    resolve([batch("only-active", { state: "active" })]);
    await screen.findByText("only-active");
    filterBy("expired");
    fireEvent.click(screen.getByRole("button", { name: "顯示全部批次" }));
    expect(selectedFilter()).toBe("all");
    expect(screen.getByText("only-active")).toBeTruthy();
  });

  it.each([
    ["unused", "尚未啟用"],
    ["active", "使用中"],
    ["expired", "已到期"],
    ["revoked", "已撤銷"],
  ] as const)("filters whole batches by %s and can restore all", async (state, label) => {
    const states = ["unused", "active", "expired", "revoked"] as const;
    vi.mocked(listTemporaryBatches).mockResolvedValue(
      states.map((value) => batch(`batch-${value}`, { state: value })),
    );
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText("batch-unused");

    expect(selectedFilter()).toBe("all");
    expect(filterChip("all").textContent).toBe("全部4");
    expect(filterChip(state).textContent).toBe(`${label}1`);
    expect(screen.getByText("4 批")).toBeTruthy();
    for (const value of states) {
      expect(screen.getByText(`batch-${value}`)).toBeTruthy();
    }

    filterBy(state);
    expect(selectedFilter()).toBe(state);
    expect(screen.getByText("1 / 4 批")).toBeTruthy();
    expect(screen.getByText(`batch-${state}`)).toBeTruthy();
    for (const other of states.filter((value) => value !== state)) {
      expect(screen.queryByText(`batch-${other}`)).toBeNull();
    }

    filterBy("all");
    for (const value of states) {
      expect(screen.getByText(`batch-${value}`)).toBeTruthy();
    }
  });

  it("uses legacy first-use fallback and gives revocation precedence over state", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([
      batch("legacy-unused", { state: undefined }),
      batch("legacy-active", {
        state: undefined,
        first_used_at: "2026-09-14T01:00:00Z",
      }),
      batch("revoked-active", {
        state: "active",
        revoked_at: "2026-09-14T02:00:00Z",
      }),
      batch("explicit-expired", {
        state: "expired",
        first_used_at: "2026-09-14T01:00:00Z",
      }),
    ]);
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText("legacy-unused");

    filterBy("unused");
    expect(screen.getByText("legacy-unused")).toBeTruthy();
    expect(screen.queryByText("legacy-active")).toBeNull();
    filterBy("active");
    expect(screen.getByText("legacy-active")).toBeTruthy();
    expect(screen.queryByText("legacy-unused")).toBeNull();
    expect(screen.queryByText("revoked-active")).toBeNull();
    expect(screen.queryByText("explicit-expired")).toBeNull();
    filterBy("revoked");
    expect(screen.getByText("revoked-active")).toBeTruthy();
    filterBy("expired");
    expect(screen.getByText("explicit-expired")).toBeTruthy();
  });

  it("does not match an individual account state when its batch has another state", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([
      batch("active-batch-unused-account", { state: "active" }),
    ]);
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText("active-batch-unused-account");

    filterBy("unused");
    expect(screen.queryByText("active-batch-unused-account")).toBeNull();
    expect(screen.getByText("沒有符合此狀態的批次紀錄")).toBeTruthy();
    expect(screen.queryByText("尚無臨時帳號批次")).toBeNull();
    filterBy("active");
    expect(screen.getByText("active-batch-unused-account")).toBeTruthy();
  });

  it("distinguishes an empty history from an empty filtered result", async () => {
    render(<TemporaryBatchPanel view="manage" />);
    expect(await screen.findByText("尚無臨時帳號批次")).toBeTruthy();

    filterBy("active");
    expect(screen.getByText("尚無臨時帳號批次")).toBeTruthy();
    expect(screen.queryByText("沒有符合此狀態的批次紀錄")).toBeNull();
  });

  it("removes a revoked batch from the active filter immediately", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([batch("revocable", { state: "active" })]);
    vi.mocked(revokeTemporaryBatch).mockResolvedValue(batch("revocable", {
      state: "active",
      revoked_at: "2026-09-14T02:00:00Z",
    }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    try {
      render(<TemporaryBatchPanel view="manage" />);
      await screen.findByText("revocable");
      filterBy("active");
      fireEvent.click(screen.getByRole("button", { name: "撤銷整批" }));

      await waitFor(() => expect(screen.queryByText("revocable")).toBeNull());
      expect(revokeTemporaryBatch).toHaveBeenCalledWith("revocable");
      expect(screen.getByText("沒有符合此狀態的批次紀錄")).toBeTruthy();
      filterBy("revoked");
      expect(screen.getByText("revocable")).toBeTruthy();
    } finally {
      confirm.mockRestore();
    }
  });

  it("reapplies the selected filter to a permission update response", async () => {
    vi.mocked(listTemporaryBatches).mockResolvedValue([batch("updatable", { state: "active" })]);
    vi.mocked(setTemporaryBatchAdminPortalAccess).mockResolvedValue(batch("updatable", {
      state: "expired",
      admin_portal_access: true,
    }));
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText("updatable");
    filterBy("active");
    fireEvent.click(screen.getByRole("button", { name: "開啟後台權限" }));

    await waitFor(() => expect(screen.queryByText("updatable")).toBeNull());
    expect(setTemporaryBatchAdminPortalAccess).toHaveBeenCalledWith("updatable", true);
    expect(selectedFilter()).toBe("active");
    filterBy("expired");
    expect(screen.getByText("updatable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "關閉後台權限" })).toBeTruthy();
  });

  it("preserves the selected filter when refreshing changed batch states", async () => {
    vi.mocked(listTemporaryBatches)
      .mockResolvedValueOnce([batch("refreshed", { state: "active" })])
      .mockResolvedValue([batch("refreshed", { state: "expired" })]);
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText("refreshed");
    filterBy("active");
    fireEvent.click(screen.getByRole("button", { name: /重新整理/ }));

    await waitFor(() => expect(screen.queryByText("refreshed")).toBeNull());
    expect(selectedFilter()).toBe("active");
    expect(screen.getByText("沒有符合此狀態的批次紀錄")).toBeTruthy();
    filterBy("expired");
    expect(screen.getByText("refreshed")).toBeTruthy();
  });

  it("shows and copies the full saved password after refreshing and remounting", async () => {
    const saved = batch("saved-login-password-with-a-long-untruncated-value");
    saved.accounts![0].state = "active";
    saved.accounts![0].remaining_seconds = 3600;
    vi.mocked(listTemporaryBatches).mockResolvedValue([saved]);
    const { unmount } = render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText(saved.accounts![0].password!);
    expect(screen.queryByText(saved.accounts![0].username)).toBeNull();
    expect(screen.getByText("剩餘 1 小時 0 分")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /重新整理/ }));
    await waitFor(() => expect(listTemporaryBatches).toHaveBeenCalledTimes(2));
    await screen.findByText(saved.accounts![0].password!);
    unmount();
    render(<TemporaryBatchPanel view="manage" />);
    await screen.findByText(saved.accounts![0].password!);
    expandBatch(saved.accounts![0].password!);
    fireEvent.click(screen.getByRole("button", { name: "複製密碼" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(saved.accounts![0].password));
    expect(await screen.findByRole("button", { name: "已複製" })).toBeTruthy();
  });

  it.each([null, undefined])("does not expose or copy an internal username when password is %s", async (password) => {
    const legacy = batch("legacy-account");
    legacy.accounts![0].password = password;
    vi.mocked(listTemporaryBatches).mockResolvedValue([legacy]);
    render(<TemporaryBatchPanel view="manage" />);

    expect(await screen.findByText("密碼未保存")).toBeTruthy();
    expect(screen.queryByText("tmp-legacy-account")).toBeNull();
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    const copyButton = screen.getByRole("button", { name: "複製密碼" });
    expect((copyButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(copyButton);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });
});
