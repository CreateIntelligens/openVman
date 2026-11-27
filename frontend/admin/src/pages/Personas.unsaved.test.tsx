import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Personas from "./Personas";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import { createPersona, deletePersona, fetchKnowledgeDocument, saveKnowledgeDocument } from "../api";

// 未存提醒用真的 NavigationGuardProvider 與編輯器，只把 API 換掉。

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: null }),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "proj-test" }),
}));

const PERSONAS = [
  { persona_id: "default", label: "預設", path: "SOUL.md", preview: "", is_default: true, avatar_char_id: null },
  { persona_id: "nurse", label: "護理師", path: "personas/nurse/SOUL.md", preview: "", is_default: false, avatar_char_id: null },
];

vi.mock("../api", () => ({
  EMPTY_CONTENT_HASH: "e3b0c44298fc1c14",
  clonePersona: vi.fn(),
  createPersona: vi.fn(),
  deletePersona: vi.fn().mockResolvedValue({ status: "ok" }),
  fetchAvatarCharacters: vi.fn().mockResolvedValue({ characters: [] }),
  fetchKnowledgeDocument: vi.fn(async (path: string) => ({ path, content: `內容：${path}`, content_hash: `hash：${path}` })),
  fetchPersonas: vi.fn(async () => ({ personas: PERSONAS })),
  fetchPersonaSoul: vi.fn(async () => ({ content: "# 預設\n\n## 角色設定\n\n小V" })),
  fetchPersonaAgents: vi.fn(async () => ({ content: "工作規則", exists: true })),
  fetchGuardrails: vi.fn(async () => ({ content: "## 範圍限制\n\n不越權" })),
  fetchProjectKnowledgeSettings: vi.fn(async () => ({ language_routes: ["zh"], reply_seconds: 20 })),
  saveKnowledgeDocument: vi.fn().mockResolvedValue({ status: "ok" }),
  setPersonaAvatar: vi.fn().mockResolvedValue({ status: "ok" }),
}));

// 這些測試針對原始文件模式（四個分頁直接編輯）；內部帳號預設是表格模式，先切過去。
function renderPage() {
  render(
    <NavigationGuardProvider>
      <Personas />
    </NavigationGuardProvider>,
  );
  return screen.findByRole("button", { name: "原始文件" }).then((button) => fireEvent.click(button));
}

async function editor(title: string) {
  return (await screen.findByRole("textbox", { name: `${title} 文件內容` })) as HTMLTextAreaElement;
}

const opened = () => vi.mocked(fetchKnowledgeDocument).mock.calls.map(([path]) => path);

describe("Personas unsaved changes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("creates a persona from its name alone and names documents in plain words", async () => {
    vi.mocked(createPersona).mockResolvedValue({
      status: "ok",
      persona: { persona_id: "persona-x", label: "客服小幫手", path: "personas/persona-x/SOUL.md", preview: "", is_default: false, avatar_char_id: null },
    } as Awaited<ReturnType<typeof createPersona>>);
    await renderPage();

    expect(await screen.findByRole("button", { name: /個性與說話方式/ })).toBeTruthy();
    expect(screen.queryByText("SOUL.md")).toBeNull();

    fireEvent.change(screen.getByLabelText("角色名稱"), { target: { value: "客服小幫手" } });
    fireEvent.click(screen.getByRole("button", { name: "建立角色" }));

    await waitFor(() => expect(createPersona).toHaveBeenCalledOnce());
    const [personaId, label] = vi.mocked(createPersona).mock.calls[0];
    expect(personaId).toMatch(/^persona-[a-z0-9]+$/);
    expect(label).toBe("客服小幫手");
  });

  it("asks before switching persona and keeps the draft when the user stays", async () => {
    await renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));
    fireEvent.change(draft, { target: { value: "還沒存的修改" } });

    const switcher = screen.getByRole("combobox", { name: "切換角色" });
    fireEvent.change(switcher, { target: { value: "nurse" } });
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    expect(opened()).not.toContain("personas/nurse/SOUL.md");

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect((await editor("預設")).value).toBe("還沒存的修改");
    expect((switcher as HTMLSelectElement).value).toBe("default");

    fireEvent.change(switcher, { target: { value: "nurse" } });
    fireEvent.click(await screen.findByRole("button", { name: "捨棄並離開" }));
    await waitFor(() => expect(opened()).toContain("personas/nurse/SOUL.md"));
    expect((await editor("護理師")).value).toBe("內容：personas/nurse/SOUL.md");
  });

  it("keeps the phone drawer open when the user stays, closes it after switching", async () => {
    await renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));
    fireEvent.change(draft, { target: { value: "還沒存的修改" } });

    const opener = screen.getByRole("button", { name: "管理角色" });
    fireEvent.click(opener);
    fireEvent.click(within(screen.getByRole("dialog", { name: "角色清單" })).getByText("護理師"));
    fireEvent.click(await screen.findByRole("button", { name: "取消" }));
    // 選了留下：抽屜還開著，可以改點別的角色。
    expect(screen.getByRole("dialog", { name: "角色清單" })).toBeTruthy();

    fireEvent.click(within(screen.getByRole("dialog", { name: "角色清單" })).getByText("護理師"));
    fireEvent.click(await screen.findByRole("button", { name: "捨棄並離開" }));
    await waitFor(() => expect(opened()).toContain("personas/nurse/SOUL.md"));
    expect(screen.queryByRole("dialog", { name: "角色清單" })).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("asks before switching document tabs with unsaved edits", async () => {
    await renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));
    fireEvent.change(draft, { target: { value: "還沒存的修改" } });

    fireEvent.click(screen.getByRole("button", { name: /工作規則/ }));
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    expect(opened()).not.toContain("AGENTS.md");
  });

  it("stays on AGENTS.md after saving it instead of jumping back to SOUL.md", async () => {
    await renderPage();
    await waitFor(() => expect(opened()).toEqual(["SOUL.md"]));
    fireEvent.click(screen.getByRole("button", { name: /工作規則/ }));
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：AGENTS.md"));

    fireEvent.change(draft, { target: { value: "新的 AGENTS" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledWith("AGENTS.md", "新的 AGENTS", "hash：AGENTS.md"));
    await waitFor(() => expect(screen.getByText("已儲存「工作規則」")).toBeTruthy());
    expect((await editor("預設")).value).toBe("新的 AGENTS");
    expect(opened()).toEqual(["SOUL.md", "AGENTS.md"]);
  });

  it("saves raw documents against the loaded version and keeps the draft when someone else saved first", async () => {
    const stale = "這份文件在你編輯時被改過了，請重新載入後再存檔";
    vi.mocked(saveKnowledgeDocument)
      .mockResolvedValueOnce({ status: "ok", content_hash: "hash-2", document: { path: "SOUL.md" } as never })
      .mockRejectedValueOnce(new Error(stale));
    await renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));

    fireEvent.change(draft, { target: { value: "第一次" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(screen.getByText("已儲存「個性與說話方式」")).toBeTruthy());

    fireEvent.change(await editor("預設"), { target: { value: "第二次，別人先存了" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(screen.getByText(stale)).toBeTruthy());
    expect(vi.mocked(saveKnowledgeDocument).mock.calls.map((call) => call[2])).toEqual(["hash：SOUL.md", "hash-2"]);
    expect((await editor("預設")).value).toBe("第二次，別人先存了");
    expect(opened()).toEqual(["SOUL.md"]);
  });

  it("opens the first persona after deleting the selected one", async () => {
    await renderPage();
    const switcher = await screen.findByRole("combobox", { name: "切換角色" });
    await waitFor(() => expect(opened()).toEqual(["SOUL.md"]));
    fireEvent.change(switcher, { target: { value: "nurse" } });
    await waitFor(() => expect(opened()).toContain("personas/nurse/SOUL.md"));

    fireEvent.click(screen.getByRole("button", { name: "刪除角色 nurse" }));
    fireEvent.click(await screen.findByRole("button", { name: "刪除" }));
    await waitFor(() => expect(deletePersona).toHaveBeenCalledWith("nurse"));
    await waitFor(() => {
      const paths = opened();
      expect(paths[paths.length - 1]).toBe("SOUL.md");
    });
  });

  it("holds persona switching and disables discard while a raw document save is in flight", async () => {
    let resolveSave!: (value: { status: string }) => void;
    const savePromise = new Promise<{ status: string }>((done) => { resolveSave = done; });
    vi.mocked(saveKnowledgeDocument).mockReturnValueOnce(savePromise as never);

    await renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));
    fireEvent.change(draft, { target: { value: "儲存中的內容" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledTimes(1));

    expect((screen.getByRole("button", { name: "捨棄修改" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByRole("combobox", { name: "切換角色" }), { target: { value: "nurse" } });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opened()).not.toContain("personas/nurse/SOUL.md");

    await act(async () => { resolveSave({ status: "ok" }); });
    await waitFor(() => expect(opened()).toContain("personas/nurse/SOUL.md"));
  });

  it("does not leak a stale raw document save error after switching to another persona", async () => {
    let rejectSave!: (reason: unknown) => void;
    const savePromise = new Promise<never>((_res, rej) => { rejectSave = rej; });
    vi.mocked(saveKnowledgeDocument).mockReturnValueOnce(savePromise);

    await renderPage();
    await waitFor(() => expect(opened()).toEqual(["SOUL.md"]));
    fireEvent.change(screen.getByRole("combobox", { name: "切換角色" }), { target: { value: "nurse" } });
    const draft = await editor("護理師");
    await waitFor(() => expect(draft.value).toBe("內容：personas/nurse/SOUL.md"));
    fireEvent.change(draft, { target: { value: "修改後失敗" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledTimes(1));

    // Delete the currently saving persona so the page opens default SOUL.md while savePromise is still pending.
    fireEvent.click(screen.getByRole("button", { name: "刪除角色 nurse" }));
    fireEvent.click(await screen.findByRole("button", { name: "刪除" }));
    await waitFor(() => expect(opened().at(-1)).toBe("SOUL.md"));

    await act(async () => { rejectSave(new Error("舊文件寫入失敗")); });
    expect(screen.queryByText(/舊文件寫入失敗/)).toBeNull();
  });
});
