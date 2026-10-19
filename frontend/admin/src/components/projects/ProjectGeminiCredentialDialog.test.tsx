import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectGeminiCredentialDialog from "./ProjectGeminiCredentialDialog";

const state = vi.hoisted(() => ({ role: "root" }));
const api = vi.hoisted(() => ({
  fetchProjectGeminiCredential: vi.fn(),
  saveProjectGeminiCredential: vi.fn(),
  deleteProjectGeminiCredential: vi.fn(),
}));

vi.mock("../../api/projects", () => api);
vi.mock("../../context/AuthContext", () => ({ useAuth: () => ({ account: { role: state.role } }) }));

const SHARED = { project_id: "project-a", source: "shared", configured: true, label: null, masked: null, credential_id: null, updated_at: null };
const PROJECT = { ...SHARED, source: "project", label: "醫院專案", masked: "••••abcd", credential_id: "gcred-1", updated_at: "2026-10-16T00:00:00Z" };

function renderDialog() {
  const onClose = vi.fn();
  render(<ProjectGeminiCredentialDialog projectId="project-a" projectLabel="專案 A" onClose={onClose} />);
  return { onClose };
}

function inputKey(value = "test-private-key") {
  const input = screen.getByLabelText(/Gemini API key/) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  return input;
}

describe("ProjectGeminiCredentialDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.role = "root";
    api.fetchProjectGeminiCredential.mockResolvedValue(SHARED);
    api.saveProjectGeminiCredential.mockResolvedValue(PROJECT);
    api.deleteProjectGeminiCredential.mockResolvedValue(SHARED);
  });

  it.each(["admin", "user"])("does not render or read settings for %s", (role) => {
    state.role = role;
    renderDialog();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.fetchProjectGeminiCredential).not.toHaveBeenCalled();
  });

  it("shows shared state and keeps the key input empty and masked", async () => {
    renderDialog();
    expect(await screen.findByText("目前使用：共用金鑰")).toBeTruthy();
    const input = screen.getByLabelText("Gemini API key") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.value).toBe("");
    expect(screen.queryByRole("button", { name: "改用共用金鑰" })).toBeNull();
    expect(screen.getByText(/不會自動改用共用金鑰/)).toBeTruthy();
  });

  it("shows project metadata without refilling the key", async () => {
    api.fetchProjectGeminiCredential.mockResolvedValue(PROJECT);
    renderDialog();
    expect(await screen.findByText("目前使用：專案專屬金鑰")).toBeTruthy();
    expect(screen.getByText("••••abcd")).toBeTruthy();
    expect((screen.getByLabelText("金鑰名稱") as HTMLInputElement).value).toBe("醫院專案");
    expect((screen.getByLabelText("新的 Gemini API key") as HTMLInputElement).value).toBe("");
  });

  it("rejects whitespace-only keys even when the form is submitted directly", async () => {
    renderDialog();
    await screen.findByText("目前使用：共用金鑰");
    fireEvent.change(screen.getByLabelText("金鑰名稱"), { target: { value: "醫院專案" } });
    inputKey("   ");
    const save = screen.getByRole("button", { name: "儲存專屬金鑰" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.submit(save.closest("form")!);
    expect(api.saveProjectGeminiCredential).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("請輸入金鑰名稱");
  });

  it("trims the PUT payload, updates metadata and clears the input after success", async () => {
    renderDialog();
    await screen.findByText("目前使用：共用金鑰");
    fireEvent.change(screen.getByLabelText("金鑰名稱"), { target: { value: " 醫院專案 " } });
    const input = inputKey(" test-private-key ");
    fireEvent.click(screen.getByRole("button", { name: "儲存專屬金鑰" }));
    await waitFor(() => expect(api.saveProjectGeminiCredential).toHaveBeenCalledWith("project-a", { label: "醫院專案", api_key: "test-private-key" }));
    expect(await screen.findByText("已儲存專案專屬金鑰。")).toBeTruthy();
    expect(screen.getByText("目前使用：專案專屬金鑰")).toBeTruthy();
    expect(input.value).toBe("");
    expect(document.body.textContent).not.toContain("test-private-key");
  });

  it("keeps the masked input for retry while suppressing raw error details", async () => {
    api.saveProjectGeminiCredential.mockRejectedValueOnce(new Error("upstream rejected test-private-key"));
    renderDialog();
    await screen.findByText("目前使用：共用金鑰");
    fireEvent.change(screen.getByLabelText("金鑰名稱"), { target: { value: "醫院專案" } });
    const input = inputKey();
    fireEvent.click(screen.getByRole("button", { name: "儲存專屬金鑰" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("儲存失敗，請確認設定後重試。");
    expect(input.value).toBe("test-private-key");
    expect(input.type).toBe("password");
    expect(document.body.textContent).not.toContain("test-private-key");
    fireEvent.click(screen.getByRole("button", { name: "儲存專屬金鑰" }));
    expect(await screen.findByText("已儲存專案專屬金鑰。")).toBeTruthy();
    expect(input.value).toBe("");
  });

  it("reports saved credentials that are still waiting for runtime refresh", async () => {
    api.saveProjectGeminiCredential.mockResolvedValue({ ...PROJECT, runtime_refreshed: false });
    renderDialog();
    await screen.findByText("目前使用：共用金鑰");
    fireEvent.change(screen.getByLabelText("金鑰名稱"), { target: { value: "醫院專案" } });
    const input = inputKey();
    fireEvent.click(screen.getByRole("button", { name: "儲存專屬金鑰" }));
    expect(await screen.findByText(/已儲存專案專屬金鑰，但執行中服務尚未更新/)).toBeTruthy();
    expect(input.value).toBe("");
  });

  it("deletes the binding to return to shared credentials and clears pending input", async () => {
    api.fetchProjectGeminiCredential.mockResolvedValue(PROJECT);
    renderDialog();
    await screen.findByText("目前使用：專案專屬金鑰");
    const input = inputKey();
    fireEvent.click(screen.getByRole("button", { name: "改用共用金鑰" }));
    expect(await screen.findByText("目前使用：共用金鑰")).toBeTruthy();
    expect(api.deleteProjectGeminiCredential).toHaveBeenCalledWith("project-a");
    expect(input.value).toBe("");
    expect(screen.queryByRole("button", { name: "改用共用金鑰" })).toBeNull();
  });

  it("retains the project binding after DELETE fails and allows retry", async () => {
    api.fetchProjectGeminiCredential.mockResolvedValue(PROJECT);
    api.deleteProjectGeminiCredential.mockRejectedValueOnce(new Error("test-private-key"));
    renderDialog();
    const useShared = await screen.findByRole("button", { name: "改用共用金鑰" });
    fireEvent.click(useShared);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("目前使用：專案專屬金鑰")).toBeTruthy();
    expect(document.body.textContent).not.toContain("test-private-key");
    fireEvent.click(useShared);
    expect(await screen.findByText("目前使用：共用金鑰")).toBeTruthy();
  });

  it.each(["button", "escape"])("clears pending key on close via %s", async (method) => {
    const { onClose } = renderDialog();
    await screen.findByText("目前使用：共用金鑰");
    const input = inputKey();
    if (method === "button") fireEvent.click(screen.getByRole("button", { name: "關閉" }));
    else fireEvent.keyDown(document, { key: "Escape" });
    expect(input.value).toBe("");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not expose failed GET details and can reload", async () => {
    api.fetchProjectGeminiCredential.mockRejectedValueOnce(new Error("test-private-key"));
    renderDialog();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(document.body.textContent).not.toContain("test-private-key");
    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
    expect(await screen.findByText("目前使用：共用金鑰")).toBeTruthy();
  });
});
