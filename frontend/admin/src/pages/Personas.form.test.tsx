import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Personas from "./Personas";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import {
  fetchGuardrails,
  fetchKnowledgeDocument,
  fetchPersonaAgents,
  fetchPersonas,
  fetchPersonaSoul,
  saveKnowledgeDocument,
  savePersonaAgents,
  savePersonaSoul,
  saveReplySeconds,
} from "../api";

// 角色管理的表格模式：欄位對應文件裡的固定標題，存回同一份文件。

const auth = vi.hoisted(() => ({ account: null as null | Record<string, unknown> }));
const project = vi.hoisted(() => ({ can_edit_knowledge: true, can_edit_features: false }));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: auth.account }),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({
    projectId: "proj-test",
    projects: [{ project_id: "proj-test", label: "測試", document_count: 0, persona_count: 2, ...project }],
  }),
}));

const PERSONAS = [
  { persona_id: "default", label: "預設", path: "SOUL.md", preview: "", is_default: true, avatar_char_id: null },
  { persona_id: "nurse", label: "護理師", path: "personas/nurse/SOUL.md", preview: "", is_default: false, avatar_char_id: null },
];

const SOUL = "# 預設\n\n## 角色設定\n\n你是小V。\n\n## 服務範圍\n\n回答問題\n";
const GUARDRAILS = "# 保護規則\n\n## 範圍限制\n\n- 不越權\n\n## 回覆格式\n\n- 不用 emoji\n\n## 知識庫規則\n\n- 只依資料\n";

vi.mock("../api", () => ({
  clonePersona: vi.fn(),
  createPersona: vi.fn(),
  deletePersona: vi.fn(),
  fetchAvatarCharacters: vi.fn().mockResolvedValue({ characters: [] }),
  fetchKnowledgeDocument: vi.fn(async (path: string) => ({ path, content: `內容：${path}` })),
  fetchPersonas: vi.fn(async () => ({ personas: PERSONAS })),
  fetchPersonaSoul: vi.fn(async () => ({ content: SOUL, content_hash: "soul-1" })),
  fetchPersonaAgents: vi.fn(async () => ({ content: "- 先查資料再回答\n", exists: true, content_hash: "agents-1" })),
  fetchGuardrails: vi.fn(async () => ({ content: GUARDRAILS })),
  fetchKnowledgeSettings: vi.fn(async () => ({
    language_routes: ["zh", "en"],
    reply_seconds: 20,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
  saveKnowledgeSettings: vi.fn(async (settings: Record<string, unknown>) => ({
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 }, ...settings,
  })),
  fetchProjectKnowledgeSettings: vi.fn(async () => ({
    language_routes: ["zh", "en"],
    reply_seconds: 20,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
  saveKnowledgeDocument: vi.fn().mockResolvedValue({ status: "ok" }),
  saveReplySeconds: vi.fn(async (_projectId: string, replySeconds: number) => ({
    language_routes: ["zh", "en"],
    reply_seconds: replySeconds,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
  savePersonaAgents: vi.fn().mockResolvedValue({ status: "ok" }),
  savePersonaSoul: vi.fn().mockResolvedValue({ status: "ok" }),
  setPersonaAvatar: vi.fn().mockResolvedValue({ status: "ok" }),
  GUARDRAILS_PATH: "GUARDRAILS.md",
  EMPTY_CONTENT_HASH: "e3b0c44298fc1c14",
}));

const VENDOR = { id: "v1", username: "vendor", role: "user", kind: "formal", vendor_name: "甲商" };

function renderPage() {
  render(
    <NavigationGuardProvider>
      <Personas />
    </NavigationGuardProvider>,
  );
}

const field = (name: string) => screen.findByRole("textbox", { name }) as Promise<HTMLTextAreaElement>;

describe("Personas table mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    auth.account = null;
    project.can_edit_knowledge = true;
    project.can_edit_features = false;
    vi.mocked(fetchPersonas).mockImplementation(async () => ({ personas: PERSONAS, persona_count: PERSONAS.length }));
    vi.mocked(fetchPersonaSoul).mockImplementation(async () => ({ content: SOUL, content_hash: "soul-1" }));
  });

  it("opens internal accounts in table mode and writes the field back under its heading", async () => {
    renderPage();
    const role = await field("角色設定");
    expect(role.value).toBe("你是小V。");
    expect((await field("回應風格")).value).toBe("");
    expect((await field("角色與任務")).value).toBe("- 先查資料再回答");
    expect(screen.getByText("名字", { exact: false })).toBeTruthy();
    expect(role.getAttribute("placeholder")).toContain("例：");
    // 表格模式不讀原始文件，也不顯示工具說明與長期記憶。
    expect(fetchKnowledgeDocument).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /工具使用說明/ })).toBeNull();

    fireEvent.change(await field("回應風格"), { target: { value: "語氣溫和" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledWith(
      "default",
      "# 預設\n\n## 角色設定\n\n你是小V。\n\n## 回應風格\n\n語氣溫和\n\n## 服務範圍\n\n回答問題\n",
      "proj-test",
      "soul-1",
    ));
    expect(savePersonaAgents).not.toHaveBeenCalled();
    expect(await screen.findByText("已儲存「個性與說話方式」")).toBeTruthy();
  });

  it("asks before leaving with unsaved fields and can switch to the raw documents", async () => {
    renderPage();
    fireEvent.change(await field("角色設定"), { target: { value: "還沒存" } });
    fireEvent.change(screen.getByRole("combobox", { name: "切換角色" }), { target: { value: "nurse" } });
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect((await field("角色設定")).value).toBe("還沒存");

    fireEvent.click(screen.getByRole("button", { name: "原始文件" }));
    fireEvent.click(await screen.findByRole("button", { name: "捨棄並離開" }));
    await waitFor(() => expect(fetchKnowledgeDocument).toHaveBeenCalledWith("SOUL.md"));
    expect(await screen.findByRole("button", { name: /長期記憶/ })).toBeTruthy();
  });

  it("gives read-only vendors the table without save, raw documents or guardrail editing", async () => {
    auth.account = VENDOR;
    project.can_edit_knowledge = false;
    renderPage();
    const role = await field("角色設定");
    expect(role.readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /儲存設定/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "原始文件" })).toBeNull();
    const guardrails = screen.getByRole("region", { name: "保護規則" });
    expect(within(guardrails).getByText("- 不越權")).toBeTruthy();
    expect(within(guardrails).queryByRole("textbox")).toBeNull();
    expect(within(guardrails).queryByText("其他規則")).toBeNull();
  });

  it("shows internal read-only accounts the table and raw documents without editing", async () => {
    project.can_edit_knowledge = false;
    renderPage();
    expect((await field("角色設定")).readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /儲存設定/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "原始文件" }));
    const raw = await screen.findByRole("textbox", { name: "預設 文件內容" }) as HTMLTextAreaElement;
    expect(raw.readOnly).toBe(true);
  });

  it("lets vendor editors save work rules but never the guardrails", async () => {
    auth.account = VENDOR;
    renderPage();
    fireEvent.change(await field("角色與任務"), { target: { value: "回答保固問題" } });
    const guardrails = screen.getByRole("region", { name: "保護規則" });
    expect(within(guardrails).queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(savePersonaAgents).toHaveBeenCalledWith(
      "default", "回答保固問題\n", "proj-test", "agents-1",
    ));
    expect(saveKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("lets internal accounts with settings permission edit the guardrails", async () => {
    project.can_edit_features = true;
    renderPage();
    fireEvent.change(await field("範圍限制"), { target: { value: "- 不越權\n- 不談政治" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledWith(
      "GUARDRAILS.md",
      "# 保護規則\n\n## 範圍限制\n\n- 不越權\n- 不談政治\n\n## 回覆格式\n\n- 不用 emoji\n\n## 知識庫規則\n\n- 只依資料\n",
      undefined,
      false,
      "proj-test",
    ));
  });

  it("tells vendors when the project has no guardrails yet instead of showing empty rules", async () => {
    auth.account = VENDOR;
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({ content: "", template: GUARDRAILS });
    renderPage();
    const guardrails = await screen.findByRole("region", { name: "保護規則" });
    expect(within(guardrails).getByText(/還沒有設定保護規則/)).toBeTruthy();
    expect(within(guardrails).queryByText("範圍限制")).toBeNull();
    expect(within(guardrails).queryByRole("button", { name: "帶入建議內容" })).toBeNull();
  });

  it("lets internal accounts start the guardrails from the suggested content", async () => {
    project.can_edit_features = true;
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({ content: "", template: GUARDRAILS });
    renderPage();
    const guardrails = await screen.findByRole("region", { name: "保護規則" });
    expect((await field("範圍限制")).value).toBe("");
    fireEvent.click(within(guardrails).getByRole("button", { name: "帶入建議內容" }));
    expect((await field("範圍限制")).value).toBe("- 不越權");
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledWith(
      "GUARDRAILS.md", GUARDRAILS, undefined, false, "proj-test",
    ));
  });

  it("shows the reply length in characters and saves it back as seconds", async () => {
    renderPage();
    const chars = await screen.findByRole("spinbutton", { name: "回覆字數" }) as HTMLInputElement;
    expect(chars.value).toBe("80");
    fireEvent.change(chars, { target: { value: "120" } });
    expect(screen.getByText(/約 30 秒念完/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveReplySeconds).toHaveBeenCalledWith("proj-test", 30));
    expect(savePersonaSoul).not.toHaveBeenCalled();
  });

  it("explains when a persona has no work rules of its own yet", async () => {
    vi.mocked(fetchPersonaAgents).mockResolvedValueOnce({ content: "", exists: false });
    renderPage();
    expect(await screen.findByText(/還沒有自己的工作規則/)).toBeTruthy();
  });

  it("does not snap back to the saved persona when a delayed reload resolves after switching", async () => {
    let resolveSave!: (value: { status: string }) => void;
    const savePromise = new Promise<{ status: string }>((done) => { resolveSave = done; });
    let resolveReload!: (value: { personas: typeof PERSONAS; persona_count: number }) => void;
    const reloadPromise = new Promise<{ personas: typeof PERSONAS; persona_count: number }>((done) => {
      resolveReload = done;
    });
    vi.mocked(savePersonaSoul).mockReturnValueOnce(savePromise);
    vi.mocked(fetchPersonas)
      .mockResolvedValueOnce({ personas: PERSONAS, persona_count: 2 })
      .mockReturnValueOnce(reloadPromise);
    vi.mocked(fetchPersonaSoul).mockImplementation(async (personaId: string) => ({
      content: personaId === "nurse" ? "# 護理師\n\n## 角色設定\n\n我是護理師。\n" : SOUL,
    }));

    renderPage();
    fireEvent.change(await field("角色設定"), { target: { value: "更新後的預設" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));

    const aside = screen.getByLabelText("角色清單");
    fireEvent.click(within(aside).getByText("護理師"));

    await act(async () => { resolveSave({ status: "ok" }); });
    await waitFor(async () => expect((await field("角色設定")).value).toBe("我是護理師。"));

    fireEvent.change(await field("角色設定"), { target: { value: "護理師未存檔草稿" } });

    await act(async () => {
      resolveReload({
        personas: [
          PERSONAS[0],
          { ...PERSONAS[1], label: "資深護理師" },
        ],
        persona_count: 2,
      });
    });

    expect(screen.getByRole("heading", { level: 3, name: "資深護理師" })).toBeTruthy();
    expect((await field("角色設定")).value).toBe("護理師未存檔草稿");
  });

  it("ignores stale fetchPersonas responses when a newer refresh finishes first", async () => {
    let resolveFirst!: (value: { personas: typeof PERSONAS; persona_count: number }) => void;
    const first = new Promise<{ personas: typeof PERSONAS; persona_count: number }>((done) => { resolveFirst = done; });
    let resolveSecond!: (value: { personas: typeof PERSONAS; persona_count: number }) => void;
    const second = new Promise<{ personas: typeof PERSONAS; persona_count: number }>((done) => { resolveSecond = done; });
    vi.mocked(fetchPersonas)
      .mockResolvedValueOnce({ personas: PERSONAS, persona_count: 2 })
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(second);

    renderPage();
    await field("角色設定");
    const refresh = screen.getByRole("button", { name: "重新整理角色清單" });
    fireEvent.click(refresh);
    // Re-trigger via second click by temporarily resolving? Refresh disables while loadingList;
    // instead trigger second loadPersonas via onSaved while first refresh is in flight.
    fireEvent.change(await field("角色設定"), { target: { value: "新設定" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(fetchPersonas).toHaveBeenCalledTimes(3));

    const newer = [PERSONAS[0], { ...PERSONAS[1], label: "最新名稱" }];
    const older = [PERSONAS[0], { ...PERSONAS[1], label: "舊版名稱" }];
    await act(async () => { resolveSecond({ personas: newer, persona_count: 2 }); });
    const aside = screen.getByLabelText("角色清單");
    expect(within(aside).getByText("最新名稱")).toBeTruthy();

    await act(async () => { resolveFirst({ personas: older, persona_count: 2 }); });
    expect(within(aside).getByText("最新名稱")).toBeTruthy();
    expect(within(aside).queryByText("舊版名稱")).toBeNull();
  });

  it("asks before replacing the current persona when refresh finds it was deleted", async () => {
    vi.mocked(fetchPersonas)
      .mockResolvedValueOnce({ personas: PERSONAS, persona_count: 2 })
      .mockResolvedValueOnce({ personas: [PERSONAS[0]], persona_count: 1 });
    vi.mocked(fetchPersonaSoul).mockImplementation(async (personaId: string) => ({
      content: personaId === "nurse" ? "# 護理師\n\n## 角色設定\n\n我是護理師。\n" : SOUL,
    }));

    renderPage();
    await field("角色設定");
    fireEvent.click(within(screen.getByLabelText("角色清單")).getByText("護理師"));
    await waitFor(async () => expect((await field("角色設定")).value).toBe("我是護理師。"));

    fireEvent.change(await field("角色設定"), { target: { value: "未儲存的護理師修改" } });
    fireEvent.click(screen.getByRole("button", { name: "重新整理角色清單" }));

    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    expect((await field("角色設定")).value).toBe("未儲存的護理師修改");
  });

  it("hides persona creation, deletion, and avatar binding for read-only internal accounts", async () => {
    project.can_edit_knowledge = false;
    renderPage();
    await field("角色設定");

    expect(screen.queryByRole("button", { name: "建立角色" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "虛擬人" })).toBeNull();

    fireEvent.click(within(screen.getByLabelText("角色清單")).getByText("護理師"));
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: "護理師" })).toBeTruthy());
    expect(screen.queryByRole("button", { name: "刪除角色 nurse" })).toBeNull();
  });

  it("makes MEMORY.md read-only when the internal account lacks settings permission", async () => {
    project.can_edit_knowledge = true;
    project.can_edit_features = false;
    renderPage();
    await field("角色設定");

    fireEvent.click(screen.getByRole("button", { name: "原始文件" }));
    const soulRaw = (await screen.findByRole("textbox", { name: "預設 文件內容" })) as HTMLTextAreaElement;
    expect(soulRaw.readOnly).toBe(false);
    expect(screen.getByRole("button", { name: /儲存設定/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /長期記憶/ }));
    await waitFor(() => expect(fetchKnowledgeDocument).toHaveBeenCalledWith("MEMORY.md"));
    await waitFor(() => expect(soulRaw.value).toBe("內容：MEMORY.md"));
    expect(soulRaw.readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /儲存設定/ })).toBeNull();
  });
});
