import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EmbedKeys from "./EmbedKeys";
import type { EmbedKey } from "../api/embedKeys";

const api = vi.hoisted(() => ({
  listEmbedKeys: vi.fn(),
  createEmbedKey: vi.fn(),
  updateEmbedKey: vi.fn(),
  setEmbedKeyDisabled: vi.fn(),
  deleteEmbedKey: vi.fn(),
  fetchProjects: vi.fn(),
}));

vi.mock("../api/embedKeys", async () => {
  const actual = await vi.importActual<typeof import("../api/embedKeys")>(
    "../api/embedKeys",
  );
  return {
    ...actual,
    listEmbedKeys: api.listEmbedKeys,
    createEmbedKey: api.createEmbedKey,
    updateEmbedKey: api.updateEmbedKey,
    setEmbedKeyDisabled: api.setEmbedKeyDisabled,
    deleteEmbedKey: api.deleteEmbedKey,
  };
});

vi.mock("../api/projects", () => ({
  fetchProjects: api.fetchProjects,
}));

function makeKey(overrides: Partial<EmbedKey> = {}): EmbedKey {
  return {
    key_id: "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    label: "夥伴官網",
    project_id: "default",
    allowed_origins: ["https://partner.example"],
    default_character_id: "aria",
    allowed_character_ids: [],
    default_persona_id: "",
    default_tts_provider: "indextts",
    default_tts_voice: "hayley",
    rate_limit_per_minute: 60,
    daily_request_quota: 1000,
    disabled: false,
    created_by: "admin-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_used_at: null,
    requests_today: 12,
    ...overrides,
  };
}

describe("EmbedKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listEmbedKeys.mockResolvedValue([makeKey()]);
    api.fetchProjects.mockResolvedValue({
      projects: [
        { project_id: "default", label: "預設專案", document_count: 0, persona_count: 0 },
      ],
      project_count: 1,
    });
    api.createEmbedKey.mockResolvedValue(makeKey());
    api.updateEmbedKey.mockResolvedValue(makeKey());
    api.setEmbedKeyDisabled.mockResolvedValue(makeKey({ disabled: true }));
    api.deleteEmbedKey.mockResolvedValue(undefined);
  });

  it("lists each key with its id, project, origins, limits and today's usage", async () => {
    render(<EmbedKeys />);

    expect(await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa")).toBeTruthy();
    expect(screen.getByText("夥伴官網")).toBeTruthy();
    expect(await screen.findByText("預設專案")).toBeTruthy();
    expect(screen.getByText("https://partner.example")).toBeTruthy();
    expect(screen.getByText("60/分、1000/日")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("啟用中")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /複製 ovk_aaaaaaaaaaaaaaaaaaaaaaaa/ }),
    ).toBeTruthy();
  });

  it("shows a disabled key as such", async () => {
    api.listEmbedKeys.mockResolvedValue([makeKey({ disabled: true })]);

    render(<EmbedKeys />);

    expect(await screen.findByText("已停用")).toBeTruthy();
    expect(screen.getByRole("button", { name: "啟用" })).toBeTruthy();
  });

  it("creates a key from the modal with the parsed origin list", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "建立金鑰" }));
    fireEvent.change(screen.getByLabelText("名稱"), {
      target: { value: "新網站" },
    });
    fireEvent.change(
      screen.getByLabelText(/允許的來源網域/),
      { target: { value: "https://a.example\nhttps://b.example" } },
    );
    const webSearch = screen.getByRole("checkbox", { name: "可用網路搜尋" }) as HTMLInputElement;
    expect(webSearch.checked).toBe(false);
    fireEvent.click(webSearch);
    fireEvent.click(screen.getByRole("button", { name: "建立" }));

    await waitFor(() => expect(api.createEmbedKey).toHaveBeenCalledTimes(1));
    expect(api.createEmbedKey.mock.calls[0][0]).toMatchObject({
      label: "新網站",
      project_id: "default",
      allowed_origins: ["https://a.example", "https://b.example"],
      web_search_access: true,
    });
    await waitFor(() => expect(api.listEmbedKeys).toHaveBeenCalledTimes(2));
  });

  it("loads stored web search access and can disable it on edit", async () => {
    const key = makeKey({ web_search_access: true });
    api.listEmbedKeys.mockResolvedValue([key]);
    render(<EmbedKeys />);
    fireEvent.click(await screen.findByRole("button", { name: "編輯" }));
    const checkbox = screen.getByRole("checkbox", { name: "可用網路搜尋" }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);

    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    await waitFor(() => expect(api.updateEmbedKey).toHaveBeenCalledWith(
      key.key_id, expect.objectContaining({ web_search_access: false }),
    ));
  });

  it("refuses to submit an empty origin list", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "建立金鑰" }));
    fireEvent.click(screen.getByRole("button", { name: "建立" }));

    const dialog = screen.getByRole("dialog", { name: "建立 網站嵌入金鑰" });
    const error = within(dialog).getByRole("alert");
    expect(error.textContent).toBe("至少需要一個允許的來源網域。");
    expect(document.activeElement).toBe(error);
    const submit = within(dialog).getByRole("button", { name: "建立" });
    submit.focus();
    fireEvent.click(submit);
    expect(document.activeElement).toBe(error);
    expect(api.createEmbedKey).not.toHaveBeenCalled();
  });

  it("opens a named modal with form focus and restores the trigger on cancel", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    const trigger = screen.getByRole("button", { name: "建立金鑰" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "建立 網站嵌入金鑰" });
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog.hasAttribute("open")).toBe(true);
    expect(document.activeElement).toBe(within(dialog).getByLabelText("名稱"));
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes through the native cancel event and restores the edit trigger", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    const trigger = screen.getByRole("button", { name: "編輯" });
    trigger.focus();
    fireEvent.click(trigger);

    fireEvent(screen.getByRole("dialog", { name: "編輯 網站嵌入金鑰" }),
      new Event("cancel", { cancelable: true }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("synchronizes an idle native close so the form can be opened again", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    const trigger = screen.getByRole("button", { name: "建立金鑰" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("closedby")).toBe("closerequest");
    dialog.removeAttribute("open");
    fireEvent(dialog, new Event("close"));
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog").hasAttribute("open")).toBe(true);
  });

  it.each(["create", "edit"])("keeps %s API errors inside the open form and clears them on reopen", async (mode) => {
    if (mode === "create") api.createEmbedKey.mockRejectedValueOnce(new Error("來源格式錯誤"));
    else api.updateEmbedKey.mockRejectedValueOnce(new Error("來源格式錯誤"));
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    const trigger = screen.getByRole("button", { name: mode === "create" ? "建立金鑰" : "編輯" });
    fireEvent.click(trigger);
    fireEvent.change(screen.getByLabelText(/允許的來源網域/), {
      target: { value: "https://partner.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: mode === "create" ? "建立" : "儲存" }));

    const dialog = screen.getByRole("dialog", { name: mode === "create" ? "建立 網站嵌入金鑰" : "編輯 網站嵌入金鑰" });
    const error = await within(dialog).findByRole("alert");
    expect(error.textContent).toBe("來源格式錯誤");
    expect(document.activeElement).toBe(error);
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    fireEvent.click(trigger);
    expect(within(screen.getByRole("dialog")).queryByRole("alert")).toBeNull();
  });

  it.each(["create", "edit"])("keeps the %s form locked until a pending submission finishes", async (mode) => {
    let resolveSubmission!: (key: EmbedKey) => void;
    const pending = new Promise<EmbedKey>((resolve) => { resolveSubmission = resolve; });
    const submitApi = mode === "create" ? api.createEmbedKey : api.updateEmbedKey;
    submitApi.mockReturnValueOnce(pending);
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    const trigger = screen.getByRole("button", { name: mode === "create" ? "建立金鑰" : "編輯" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    const form = within(dialog).getByRole("form");
    fireEvent.change(within(dialog).getByLabelText(/允許的來源網域/), {
      target: { value: "https://partner.example" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: mode === "create" ? "建立" : "儲存" }));

    expect(form.getAttribute("aria-busy")).toBe("true");
    expect(dialog.getAttribute("closedby")).toBe("none");
    expect((within(dialog).getByRole("button", { name: mode === "create" ? "建立中…" : "儲存中…" }) as HTMLButtonElement).disabled).toBe(true);
    for (const field of dialog.querySelectorAll("input, textarea, [role=combobox]")) {
      expect(field.matches(":disabled")).toBe(true);
    }
    const cancel = within(dialog).getByRole("button", { name: "取消" }) as HTMLButtonElement;
    expect(cancel.disabled).toBe(true);
    fireEvent.click(cancel);
    const cancelEvent = new Event("cancel", { cancelable: true });
    fireEvent(dialog, cancelEvent);
    expect(cancelEvent.defaultPrevented).toBe(true);
    expect(screen.getByRole("dialog")).toBe(dialog);
    // 模擬忽略 closedby 的瀏覽器強制關閉原生 dialog。
    dialog.removeAttribute("closedby");
    dialog.removeAttribute("open");
    fireEvent(dialog, new Event("close"));
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(within(dialog).getByRole("form")).toBe(form);
    expect((within(dialog).getByLabelText(/允許的來源網域/) as HTMLTextAreaElement).value).toBe("https://partner.example");
    expect(form.getAttribute("aria-busy")).toBe("true");
    fireEvent.submit(form);
    expect(submitApi).toHaveBeenCalledTimes(1);

    await act(async () => { resolveSubmission(makeKey()); });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("edits an existing key through PATCH rather than creating a new one", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    const trigger = screen.getByRole("button", { name: "編輯" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.change(screen.getByLabelText("名稱"), {
      target: { value: "改名後" },
    });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    await waitFor(() => expect(api.updateEmbedKey).toHaveBeenCalledTimes(1));
    expect(api.updateEmbedKey.mock.calls[0][0]).toBe(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    );
    expect(api.updateEmbedKey.mock.calls[0][1]).toMatchObject({
      label: "改名後",
      allowed_origins: ["https://partner.example"],
    });
    expect(api.createEmbedKey).not.toHaveBeenCalled();
    await screen.findByText("已更新 網站嵌入金鑰。");
    expect(document.activeElement).toBe(trigger);
  });

  it("closes the form but reports a failed list refresh after saving", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    api.listEmbedKeys.mockRejectedValueOnce(new Error("後端掛了"));

    fireEvent.click(screen.getByRole("button", { name: "編輯" }));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    expect(await screen.findByText("已更新 網站嵌入金鑰，但清單刷新失敗，請重新整理頁面。")).toBeTruthy();
    expect(api.updateEmbedKey).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("已更新 網站嵌入金鑰。")).toBeNull();
  });

  it("keeps the form open when Escape only closes the project list", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");
    fireEvent.click(screen.getByRole("button", { name: "建立金鑰" }));
    const dialog = screen.getByRole("dialog", { name: "建立 網站嵌入金鑰" });
    fireEvent.change(within(dialog).getByLabelText("名稱"), { target: { value: "草稿" } });
    // jsdom 不會把 Esc 轉成 cancel；照瀏覽器的行為，keydown 派送完沒被擋下才送出關閉要求。
    const pressEscape = (target: HTMLElement) => {
      if (fireEvent.keyDown(target, { key: "Escape" })) {
        fireEvent(dialog, new Event("cancel", { cancelable: true }));
      }
    };
    const project = within(dialog).getByRole("combobox", { name: "專案" });
    fireEvent.click(project);
    expect(within(dialog).getByRole("listbox")).toBeTruthy();

    pressEscape(project);

    expect(within(dialog).queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect((within(dialog).getByLabelText("名稱") as HTMLInputElement).value).toBe("草稿");

    pressEscape(project);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("disables a key from the row action", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "停用" }));

    await waitFor(() => expect(api.setEmbedKeyDisabled).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
      true,
    ));
  });

  it("re-enables a disabled key", async () => {
    api.listEmbedKeys.mockResolvedValue([makeKey({ disabled: true })]);

    render(<EmbedKeys />);
    await screen.findByText("已停用");

    fireEvent.click(screen.getByRole("button", { name: "啟用" }));

    await waitFor(() => expect(api.setEmbedKeyDisabled).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
      false,
    ));
  });

  it("deletes a key only after the confirmation is accepted", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(
      screen.getByRole("button", { name: /刪除 ovk_aaaaaaaaaaaaaaaaaaaaaaaa/ }),
    );
    expect(api.deleteEmbedKey).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^刪除$/ }));

    await waitFor(() => expect(api.deleteEmbedKey).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    ));
  });

  it("surfaces a failure from the API", async () => {
    api.listEmbedKeys.mockRejectedValueOnce(new Error("後端掛了"));

    render(<EmbedKeys />);

    expect(await screen.findByText("後端掛了")).toBeTruthy();
  });
});
