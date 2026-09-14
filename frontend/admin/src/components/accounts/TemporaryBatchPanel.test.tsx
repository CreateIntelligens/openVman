import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function filterBy(state: string) {
  fireEvent.change(screen.getByLabelText("批次狀態"), {
    target: { value: state },
  });
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
    expect(screen.queryByLabelText("批次狀態")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "產生 5 組帳號" }));
    expect(await screen.findByText("one-time-test-password")).toBeTruthy();

    rerender(<TemporaryBatchPanel view="manage" />);
    expect(await screen.findByText("one-time-test-password")).toBeTruthy();
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

    expect((screen.getByLabelText("批次狀態") as HTMLSelectElement).value).toBe("all");
    expect(screen.getByRole("option", { name: "全部狀態" })).toBeTruthy();
    expect((screen.getByRole("option", { name: label }) as HTMLOptionElement).value).toBe(state);
    for (const value of states) {
      expect(screen.getByText(`batch-${value}`)).toBeTruthy();
    }

    filterBy(state);
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
    expect((screen.getByLabelText("批次狀態") as HTMLSelectElement).value).toBe("active");
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
    expect((screen.getByLabelText("批次狀態") as HTMLSelectElement).value).toBe("active");
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
    const copyButton = screen.getByRole("button", { name: "複製密碼" });
    expect((copyButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(copyButton);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });
});
