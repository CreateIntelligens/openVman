import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PersonaForm from "./PersonaForm";
import { NavigationGuardProvider, useNavigationGuard } from "../../context/NavigationGuardContext";
import {
  fetchGuardrails,
  fetchPersonaAgents,
  fetchPersonaSoul,
  saveKnowledgeDocument,
  savePersonaAgents,
  savePersonaSoul,
  saveReplySeconds,
} from "../../api";

// 存檔流程：鎖定專案與角色、等待中不吃掉輸入、各份分開存、字數只改長度。

const SOUL = "# 預設\n\n## 角色設定\n\n你是小V。\n";
const AGENTS = "## 角色與任務\n\n回答問題\n";
const GUARDRAILS = "# 保護規則\n\n## 範圍限制\n\n- 不越權\n";

vi.mock("../../api", () => ({
  GUARDRAILS_PATH: "GUARDRAILS.md",
  EMPTY_CONTENT_HASH: "empty-hash",
  fetchPersonaSoul: vi.fn(async () => ({ content: SOUL, content_hash: "soul-1" })),
  fetchPersonaAgents: vi.fn(async () => ({ content: AGENTS, exists: true, content_hash: "agents-1" })),
  fetchGuardrails: vi.fn(async () => ({ content: GUARDRAILS, content_hash: "hash-1", max_chars: 5000 })),
  fetchProjectKnowledgeSettings: vi.fn(async () => ({
    language_routes: ["zh", "en"], reply_seconds: 20,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
  // 舊版表格用的讀寫函式也放進來，基準版本上測試才會照斷言失敗而不是直接當掉。
  fetchKnowledgeSettings: vi.fn(async () => ({
    language_routes: ["zh", "en"], reply_seconds: 20,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
  saveKnowledgeSettings: vi.fn(async (settings: Record<string, unknown>) => ({
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 }, ...settings,
  })),
  saveKnowledgeDocument: vi.fn().mockResolvedValue({ status: "ok" }),
  savePersonaAgents: vi.fn().mockResolvedValue({ status: "ok" }),
  savePersonaSoul: vi.fn().mockResolvedValue({ status: "ok" }),
  saveReplySeconds: vi.fn(async (_projectId: string, replySeconds: number) => ({
    language_routes: ["zh", "en"], reply_seconds: replySeconds,
    speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
  })),
}));

const PERSONA = { persona_id: "default", label: "預設", is_default: true };

function deferred() {
  let resolve!: (value: { status: string }) => void;
  const promise = new Promise<{ status: string }>((done) => { resolve = done; });
  return { promise, resolve };
}

let navigate: (action: () => void) => boolean = () => false;
let guardDirty = false;
function GuardProbe() {
  const guard = useNavigationGuard();
  navigate = guard.requestNavigation;
  guardDirty = guard.hasUnsavedChanges;
  return null;
}

function form(props: Partial<Parameters<typeof PersonaForm>[0]> = {}) {
  return (
    <NavigationGuardProvider>
      <GuardProbe />
      <PersonaForm
        persona={PERSONA}
        projectId="project-a"
        canEditKnowledge
        canEditGuardrails={false}
        {...props}
      />
    </NavigationGuardProvider>
  );
}

const field = (name: string) => screen.findByRole("textbox", { name }) as Promise<HTMLTextAreaElement>;
const saveButton = () => screen.getByRole("button", { name: /儲存設定|儲存中/ });

describe("PersonaForm saving", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("keeps writing to the project and persona it started with, and holds navigation until done", async () => {
    const first = deferred();
    vi.mocked(savePersonaSoul).mockReturnValueOnce(first.promise);
    const view = render(form());
    fireEvent.change(await field("角色設定"), { target: { value: "A 專案的人設" } });
    fireEvent.change(await field("角色與任務"), { target: { value: "A 專案的任務" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));
    await screen.findByText("儲存中…");

    // 存檔中想離開：不跳「捨棄」對話框，等存完才走。
    const leave = vi.fn();
    act(() => { navigate(leave); });
    expect(leave).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();

    view.rerender(form({ projectId: "project-b" }));
    await act(async () => { first.resolve({ status: "ok" }); });
    await waitFor(() => expect(savePersonaAgents).toHaveBeenCalled());
    expect(savePersonaSoul).toHaveBeenCalledWith("default", expect.stringContaining("A 專案的人設"), "project-a", "soul-1");
    expect(savePersonaAgents).toHaveBeenCalledWith("default", "## 角色與任務\n\nA 專案的任務\n", "project-a", "agents-1");
    await waitFor(() => expect(leave).toHaveBeenCalled());
  });

  it("keeps what the user typed while the save was in flight", async () => {
    const pending = deferred();
    vi.mocked(savePersonaSoul).mockReturnValueOnce(pending.promise);
    render(form());
    const role = await field("角色設定");
    fireEvent.change(role, { target: { value: "第一版" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));
    fireEvent.change(role, { target: { value: "第一版，再加一句" } });
    await act(async () => { pending.resolve({ status: "ok" }); });
    await waitFor(() => expect(screen.getByText(/尚未儲存/)).toBeTruthy());
    expect((await field("角色設定")).value).toBe("第一版，再加一句");
    expect(savePersonaSoul).toHaveBeenCalledWith("default", "# 預設\n\n## 角色設定\n\n第一版\n", "project-a", "soul-1");
  });

  it("loads each document on its own so one failure does not blank the page", async () => {
    vi.mocked(fetchPersonaSoul).mockRejectedValueOnce(new Error("沒有權限使用這個功能。"));
    render(form());
    const duties = await field("角色與任務");
    expect(duties.readOnly).toBe(false);
    expect((await field("角色設定")).readOnly).toBe(true);
    expect(screen.getByText(/這一份讀不到/)).toBeTruthy();
    fireEvent.change(duties, { target: { value: "還是可以改" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(savePersonaAgents).toHaveBeenCalled());
    expect(savePersonaSoul).not.toHaveBeenCalled();
  });

  it("saves each document separately and reports which ones failed", async () => {
    vi.mocked(saveKnowledgeDocument).mockRejectedValueOnce(new Error("沒有修改此工作區路徑的權限"));
    render(form({ canEditGuardrails: true }));
    fireEvent.change(await field("角色設定"), { target: { value: "新的人設" } });
    fireEvent.change(await field("範圍限制"), { target: { value: "- 新規則" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getByText(/「保護規則」沒有存成功/)).toBeTruthy());
    expect(screen.getByText(/已儲存「個性與說話方式」/)).toBeTruthy();
    expect(saveKnowledgeDocument).toHaveBeenCalledWith(
      "GUARDRAILS.md", "# 保護規則\n\n## 範圍限制\n\n- 新規則\n", "hash-1", false, "project-a",
    );
  });

  it("shows read-only fields to internal accounts without edit permission", async () => {
    render(form({ canEditKnowledge: false }));
    expect((await field("角色設定")).readOnly).toBe(true);
    expect((screen.getByRole("spinbutton", { name: "回覆字數" }) as HTMLInputElement).readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /儲存設定/ })).toBeNull();
  });

  it.each([["1", 1], ["5", 2], ["120", 30], ["0", 0]])(
    "saves %s characters as %i seconds without touching language routes",
    async (typed, seconds) => {
      render(form());
      fireEvent.change(await screen.findByRole("spinbutton", { name: "回覆字數" }), { target: { value: typed } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(saveReplySeconds).toHaveBeenCalledWith("project-a", seconds));
    },
  );

  it("refuses guardrails over the length limit and explains linked files", async () => {
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({
      content: GUARDRAILS, content_hash: "hash-1", max_chars: 40,
    });
    render(form({ canEditGuardrails: true }));
    fireEvent.change(await field("範圍限制"), { target: { value: "字".repeat(60) } });
    fireEvent.click(saveButton());
    expect(await screen.findByText(/保護規則最多 40 字/)).toBeTruthy();
    expect(saveKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("does not offer to edit or fill in guardrails that are a linked file", async () => {
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({
      content: "", linked: true, template: GUARDRAILS, content_hash: "",
    });
    render(form({ canEditGuardrails: true }));
    const section = await screen.findByRole("region", { name: "保護規則" });
    expect(within(section).getByText(/檔案是連結/)).toBeTruthy();
    expect(within(section).queryByRole("button", { name: "帶入建議內容" })).toBeNull();
    expect(within(section).queryByRole("textbox")).toBeNull();
  });

  it("disables discard while a save is in flight", async () => {
    const pending = deferred();
    vi.mocked(savePersonaSoul).mockReturnValueOnce(pending.promise);
    render(form());
    const role = await field("角色設定");
    fireEvent.change(role, { target: { value: "新版本" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));

    const discardBtn = screen.getByRole("button", { name: "捨棄修改" }) as HTMLButtonElement;
    expect(discardBtn.disabled).toBe(true);
    fireEvent.click(discardBtn);
    expect(role.value).toBe("新版本");

    await act(async () => { pending.resolve({ status: "ok" }); });
    await waitFor(() => expect(screen.getByText(/已儲存「個性與說話方式」/)).toBeTruthy());
  });

  it("keeps unsaved state until guardrails hash refresh completes", async () => {
    let resolveFresh!: (value: { content: string; content_hash: string }) => void;
    const freshPromise = new Promise<{ content: string; content_hash: string }>((done) => { resolveFresh = done; });
    vi.mocked(fetchGuardrails)
      .mockResolvedValueOnce({ content: GUARDRAILS, content_hash: "hash-1", max_chars: 5000 })
      .mockReturnValueOnce(freshPromise);

    render(form({ canEditGuardrails: true }));
    fireEvent.change(await field("範圍限制"), { target: { value: "- 新規則" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(fetchGuardrails).toHaveBeenCalledTimes(2));

    expect(guardDirty).toBe(true);

    await act(async () => { resolveFresh({ content: GUARDRAILS, content_hash: "hash-2" }); });
    await waitFor(() => expect(guardDirty).toBe(false));
  });

  it("warns and prevents resaving with a stale hash when post-save guardrails refresh fails", async () => {
    vi.mocked(fetchGuardrails)
      .mockResolvedValueOnce({ content: GUARDRAILS, content_hash: "hash-1", max_chars: 5000 })
      .mockRejectedValueOnce(new Error("network blip"));

    render(form({ canEditGuardrails: true }));
    fireEvent.change(await field("範圍限制"), { target: { value: "- 規則 1" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.getAllByText(/重新整理/).length).toBeGreaterThan(0));
    const section = screen.getByRole("region", { name: "保護規則" });
    expect(within(section).queryByRole("textbox")).toBeNull();
  });

  it("does not leak status or onSaved when projectId changes mid-save", async () => {
    const pending = deferred();
    vi.mocked(savePersonaSoul).mockReturnValueOnce(pending.promise);
    const onSaved = vi.fn();
    const view = render(form({ onSaved }));
    fireEvent.change(await field("角色設定"), { target: { value: "A 改動" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));

    view.rerender(form({ projectId: "project-b", onSaved }));
    await act(async () => { pending.resolve({ status: "ok" }); });
    await waitFor(() => expect(screen.queryByText("儲存中…")).toBeNull());

    expect(screen.queryByText(/已儲存「個性與說話方式」/)).toBeNull();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("uses accurate read-only copy for missing agents and guardrails-only editors", async () => {
    vi.mocked(fetchPersonaAgents).mockResolvedValueOnce({ content: "", exists: false });
    const view = render(form({ canEditKnowledge: false, canEditGuardrails: false }));
    expect(await screen.findByText(/還沒有自己的工作規則/)).toBeTruthy();
    expect(screen.queryByText(/填寫並儲存後/)).toBeNull();

    view.rerender(form({ canEditKnowledge: false, canEditGuardrails: true }));
    expect(screen.queryByText(/你的帳號只能查看/)).toBeNull();
    expect(screen.getByText(/保護規則/, { selector: "header p" })).toBeTruthy();
  });

  it("applies word-wrapping classes to title, load error, and read-only guardrails paragraphs", async () => {
    vi.mocked(fetchPersonaSoul).mockRejectedValueOnce(new Error("read failed"));
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({
      content: "# 保護規則\n\n## 範圍限制\n\n- https://example.com/long\n\n## 備註\n\nhttps://example.com/extra\n",
    });
    render(form({ canEditGuardrails: false }));
    const heading = await screen.findByRole("heading", { level: 3, name: "預設" });
    const loadError = screen.getByRole("alert");
    const section = screen.getByRole("region", { name: "保護規則" });
    const fieldParagraph = within(section).getByText("- https://example.com/long");
    const extraParagraph = within(section).getByText("https://example.com/extra", { exact: false });

    for (const el of [heading, loadError, fieldParagraph, extraParagraph]) {
      expect(el.className).toMatch(/break-words|\[overflow-wrap:anywhere\]/);
    }
  });

  it("shows a heading-only GUARDRAILS.md line in read-only view instead of hiding it", async () => {
    vi.mocked(fetchGuardrails).mockResolvedValueOnce({ content: "# 禁止談論政治\n" });
    render(form({ canEditGuardrails: false }));
    const section = await screen.findByRole("region", { name: "保護規則" });
    expect(within(section).getByText(/禁止談論政治/)).toBeTruthy();
  });
});

describe("PersonaForm other content", () => {
  beforeEach(() => vi.clearAllMocks());

  it("hides the other-content box when the files only carry their leading title", async () => {
    vi.mocked(fetchPersonaSoul).mockResolvedValueOnce({ content: "# 鶴記顧問\n\n## 角色設定\n\n你是顧問。\n\n## 回應風格\n\n- 簡短\n" } as never);
    vi.mocked(fetchPersonaAgents).mockResolvedValueOnce({ content: "# 諮詢工作流程 (AGENTS)\n\n## 角色與任務\n\n- 查型錄\n", exists: true } as never);
    render(form());
    await field("角色設定");
    expect(screen.queryByText("其他內容（一般不用改）")).toBeNull();
  });

  it("still shows paragraphs that belong to no field", async () => {
    vi.mocked(fetchPersonaSoul).mockResolvedValueOnce({ content: "# 鶴記顧問\n\n## 角色設定\n\n你是顧問。\n\n## 備註\n\n展場限定\n" } as never);
    render(form());
    await field("角色設定");
    expect(await screen.findByText("其他內容（一般不用改）")).toBeTruthy();
  });

  describe("version checks (base_hash)", () => {
    const STALE = "這份文件在你編輯時被改過了，請重新載入後再存檔";

    it("saves with the loaded version and uses the returned one next time, even if the user typed meanwhile", async () => {
      let finish!: (value: { status: string; content_hash: string }) => void;
      vi.mocked(savePersonaSoul)
        .mockReturnValueOnce(new Promise((done) => { finish = done; }))
        .mockResolvedValueOnce({ status: "ok", content_hash: "soul-3" });
      render(form());
      const role = await field("角色設定");
      fireEvent.change(role, { target: { value: "第一版" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(1));
      expect(vi.mocked(savePersonaSoul).mock.calls[0][3]).toBe("soul-1");
      fireEvent.change(role, { target: { value: "第二版" } });
      await act(async () => { finish({ status: "ok", content_hash: "soul-2" }); });
      await waitFor(() => expect(screen.getByText(/尚未儲存/)).toBeTruthy());

      fireEvent.click(saveButton());
      await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(2));
      expect(vi.mocked(savePersonaSoul).mock.calls[1][3]).toBe("soul-2");
    });

    it("keeps the draft and the old version when the file changed elsewhere (409)", async () => {
      vi.mocked(savePersonaSoul)
        .mockRejectedValueOnce(new Error(STALE))
        .mockResolvedValueOnce({ status: "ok", content_hash: "soul-2" });
      render(form());
      fireEvent.change(await field("角色設定"), { target: { value: "我打了很久的人設" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(screen.getByText(new RegExp(STALE))).toBeTruthy());
      expect((await field("角色設定")).value).toBe("我打了很久的人設");
      expect(guardDirty).toBe(true);
      expect(fetchPersonaSoul).toHaveBeenCalledTimes(1);

      fireEvent.click(saveButton());
      await waitFor(() => expect(savePersonaSoul).toHaveBeenCalledTimes(2));
      expect(vi.mocked(savePersonaSoul).mock.calls[1][3]).toBe("soul-1");
    });

    it("sends the empty-file version when work rules or guardrails do not exist yet", async () => {
      vi.mocked(fetchPersonaAgents).mockResolvedValueOnce({ content: "", exists: false, content_hash: "empty-hash" });
      vi.mocked(fetchGuardrails).mockResolvedValueOnce({
        content: "", content_hash: "", template: GUARDRAILS, max_chars: 5000,
      });
      vi.mocked(saveKnowledgeDocument).mockResolvedValueOnce({
        status: "ok", content_hash: "rules-2", document: { path: "GUARDRAILS.md" } as never,
      });
      render(form({ canEditGuardrails: true }));
      fireEvent.change(await field("角色與任務"), { target: { value: "新的任務" } });
      fireEvent.change(await field("範圍限制"), { target: { value: "- 新規則" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalled());
      expect(vi.mocked(savePersonaAgents).mock.calls[0][3]).toBe("empty-hash");
      expect(vi.mocked(saveKnowledgeDocument).mock.calls[0][2]).toBe("empty-hash");
    });

    it("takes the new guardrails version from the save response instead of reading it again", async () => {
      vi.mocked(saveKnowledgeDocument)
        .mockResolvedValueOnce({ status: "ok", content_hash: "hash-2", document: { path: "GUARDRAILS.md" } as never })
        .mockResolvedValueOnce({ status: "ok", content_hash: "hash-3", document: { path: "GUARDRAILS.md" } as never });
      render(form({ canEditGuardrails: true }));
      const rules = await field("範圍限制");
      fireEvent.change(rules, { target: { value: "- 第一次" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(screen.getByText(/已儲存「保護規則」/)).toBeTruthy());
      fireEvent.change(rules, { target: { value: "- 第二次" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledTimes(2));
      expect(vi.mocked(saveKnowledgeDocument).mock.calls.map((call) => call[2])).toEqual(["hash-1", "hash-2"]);
      expect(fetchGuardrails).toHaveBeenCalledTimes(1);
    });

    it("refuses to save when the written file would not read back as the form shows it", async () => {
      vi.mocked(fetchPersonaSoul).mockResolvedValueOnce({ content: "你是小V。\n", content_hash: "soul-1" });
      render(form());
      fireEvent.change(await field("角色設定"), { target: { value: "---\na: 1\n---\n你是小安。" } });
      fireEvent.click(saveButton());
      await waitFor(() => expect(screen.getByText(/再讀回來會和畫面上的欄位不一樣/)).toBeTruthy());
      expect(savePersonaSoul).not.toHaveBeenCalled();
      expect((await field("角色設定")).value).toBe("---\na: 1\n---\n你是小安。");
    });
  });
});
