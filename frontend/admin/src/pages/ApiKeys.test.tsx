import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountApiKey } from "../api/apiKeys";
import type { AccountProfile } from "../api/auth";
import ApiKeys from "./ApiKeys";

const mocks = vi.hoisted(() => ({
  listAccountApiKeys: vi.fn(), createAccountApiKey: vi.fn(),
  revokeAccountApiKey: vi.fn(), listAccounts: vi.fn(), navigateTo: vi.fn(),
  account: { id: "root-1", username: "root", role: "root", disabled: false, created_at: "2026-01-01T00:00:00Z" } as AccountProfile,
}));
vi.mock("../api/apiKeys", () => mocks);
vi.mock("../api/auth", () => ({ listAccounts: mocks.listAccounts }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => ({ account: mocks.account }) }));
vi.mock("../context/NavigationContext", () => ({ useNavigation: () => ({ navigateTo: mocks.navigateTo }) }));

const row: AccountApiKey = {
  key_id: "ak_1", user_id: "root-1", label: "串接服務", created_at: "2026-01-01T00:00:00Z",
  expires_at: null, revoked_at: null, last_used_at: null, request_count: 17, token_prefix: "ovak_prefix",
};
const secret = "test-only-one-time-secret";

async function createKey() {
  await screen.findByText("串接服務");
  fireEvent.change(screen.getByLabelText("名稱"), { target: { value: "  測試串接  " } });
  fireEvent.click(screen.getByRole("button", { name: "建立 API 金鑰" }));
  await screen.findByText(secret);
}

describe("account API keys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    mocks.account = { id: "root-1", username: "root", role: "root", disabled: false, created_at: "2026-01-01T00:00:00Z" };
    mocks.listAccountApiKeys.mockResolvedValue([row]);
    mocks.listAccounts.mockResolvedValue([]);
    mocks.createAccountApiKey.mockResolvedValue({ ...row, key: secret });
    mocks.revokeAccountApiKey.mockResolvedValue(undefined);
  });

  it("shows metadata, owner, usage and masked prefix only", async () => {
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    expect(screen.getByText(/ovak_prefix…/)).toBeTruthy();
    expect(screen.getByText(/請求次數：17/)).toBeTruthy();
    expect(screen.queryByText(secret)).toBeNull();
    expect(mocks.listAccountApiKeys).toHaveBeenCalledWith("root-1");
    expect(screen.getByLabelText(/^到期時間/)).toHaveProperty("value", expect.stringMatching(/^\d{4}-/));
  });

  it("creates for the selected owner with a future ISO expiry and trimmed name", async () => {
    render(<ApiKeys />);
    await createKey();
    const payload = mocks.createAccountApiKey.mock.calls[0][0];
    expect(payload).toEqual({ user_id: "root-1", label: "測試串接", expires_at: expect.stringMatching(/Z$/) });
    expect(new Date(payload.expires_at).getTime()).toBeGreaterThan(Date.now());
    expect(screen.getByRole("button", { name: "我已保存，關閉" })).toBeTruthy();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain(secret);
    fireEvent.click(screen.getByRole("button", { name: "我已保存，關閉" }));
    expect(screen.queryByText(secret)).toBeNull();
    expect(screen.getByRole("button", { name: "建立 API 金鑰" })).toBeTruthy();
  });

  it("clears the secret on unmount and does not reload it from metadata", async () => {
    const view = render(<ApiKeys />);
    await createKey();
    view.unmount();
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    expect(screen.queryByText(secret)).toBeNull();
  });

  it("keeps the one-time secret visible if metadata reload fails", async () => {
    mocks.listAccountApiKeys.mockResolvedValueOnce([row]).mockRejectedValueOnce(new Error("列表暫時無法取得"));
    render(<ApiKeys />);
    await createKey();
    expect(await screen.findByText("列表暫時無法取得")).toBeTruthy();
    expect(screen.getByText(secret)).toBeTruthy();
  });

  it("copies only after an explicit click", async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: copy } });
    render(<ApiKeys />);
    await createKey();
    expect(copy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "複製完整金鑰" }));
    await screen.findByRole("button", { name: "已複製" });
    expect(copy).toHaveBeenCalledWith(secret);
  });

  it("supports explicit no expiry", async () => {
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    fireEvent.change(screen.getByLabelText("名稱"), { target: { value: "長期串接" } });
    fireEvent.click(screen.getByLabelText("不設到期時間"));
    fireEvent.click(screen.getByRole("button", { name: "建立 API 金鑰" }));
    await screen.findByText(secret);
    expect(mocks.createAccountApiKey).toHaveBeenCalledWith({ label: "長期串接", user_id: "root-1", expires_at: null });
  });

  it("rejects empty or past expiry before sending a request", async () => {
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    fireEvent.change(screen.getByLabelText("名稱"), { target: { value: "測試" } });
    for (const value of ["", "2000-01-01T00:00"]) {
      fireEvent.change(screen.getByLabelText(/^到期時間/), { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "建立 API 金鑰" }));
      expect(await screen.findByText("到期時間必須是有效的未來時間。")).toBeTruthy();
    }
    expect(mocks.createAccountApiKey).not.toHaveBeenCalled();
  });

  it("prevents duplicate create submits while the request is pending", async () => {
    mocks.createAccountApiKey.mockReturnValue(new Promise(() => {}));
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    fireEvent.change(screen.getByLabelText("名稱"), { target: { value: "測試" } });
    fireEvent.submit(screen.getByRole("form", { name: "建立帳號 API 金鑰" }));
    fireEvent.submit(screen.getByRole("form", { name: "建立帳號 API 金鑰" }));
    expect(mocks.createAccountApiKey).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "建立中…" })).toHaveProperty("disabled", true);
  });

  it("requires confirmation to revoke and preserves the audit row", async () => {
    mocks.listAccountApiKeys.mockResolvedValueOnce([row]).mockResolvedValueOnce([{ ...row, revoked_at: "2026-10-12T00:00:00Z" }]);
    render(<ApiKeys />);
    fireEvent.click(await screen.findByRole("button", { name: "撤銷 串接服務" }));
    expect(mocks.revokeAccountApiKey).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "確認撤銷" }));
    await waitFor(() => expect(mocks.revokeAccountApiKey).toHaveBeenCalledWith("ak_1"));
    expect(await screen.findByText("已撤銷")).toBeTruthy();
    expect(screen.getByText("串接服務")).toBeTruthy();
    expect(screen.getByRole("button", { name: "撤銷 串接服務" })).toHaveProperty("disabled", true);
  });

  it("ordinary formal users only manage themselves without requesting account lists", async () => {
    mocks.account = { ...mocks.account, role: "user" };
    render(<ApiKeys />);
    await screen.findByText("串接服務");
    expect(mocks.listAccounts).not.toHaveBeenCalled();
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "返回帳號管理" })).toBeNull();
  });

  it("filters admin owner choices to self and directly created formal accounts", async () => {
    mocks.account = { ...mocks.account, role: "admin" };
    mocks.listAccounts.mockResolvedValue([
      { ...mocks.account, id: "direct", username: "直屬", role: "user", created_by: "root-1" },
      { ...mocks.account, id: "other", username: "其他", role: "user", created_by: "elsewhere" },
      { ...mocks.account, id: "temporary", username: "臨時", kind: "temporary", created_by: "root-1" },
    ]);
    render(<ApiKeys />);
    await screen.findByRole("option", { name: "直屬（user）" });
    expect(screen.getAllByRole("option")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("所屬帳號"), { target: { value: "direct" } });
    await waitFor(() => expect(mocks.listAccountApiKeys).toHaveBeenCalledWith("direct"));
  });

  it("does not request keys or accounts for temporary accounts", () => {
    mocks.account = { ...mocks.account, kind: "temporary" };
    render(<ApiKeys />);
    expect(screen.getByText("臨時帳號不能建立 API 金鑰。")).toBeTruthy();
    expect(mocks.listAccountApiKeys).not.toHaveBeenCalled();
    expect(mocks.listAccounts).not.toHaveBeenCalled();
  });
});
