import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Tools from "./Tools";
import { fetchSkillFiles, updateSkillFiles } from "../api";
import {
  NavigationGuardProvider,
  useNavigationGuard,
} from "../context/NavigationGuardContext";

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "test-project" }),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { role: "root" } }),
}));

vi.mock("../api", () => ({
  createSkill: vi.fn(),
  deleteSkill: vi.fn(),
  fetchTools: vi.fn(async () => ({
    tools: [],
    skill_tools: [],
    skills: ["alpha", "beta"].map((id) => ({
      id,
      name: id,
      description: "測試技能",
      version: "1",
      // 共用技能在後台唯讀，草稿保護只會發生在專案技能。
      scope: "project",
      project_id: "test-project",
      enabled: true,
      tools: [],
      warnings: [],
    })),
  })),
  fetchSkillFiles: vi.fn(async (id: string) => ({
    skill_id: id,
    files: { "skill.yaml": `name: ${id}`, "main.py": "pass" },
  })),
  reloadAllSkills: vi.fn(),
  skillKey: (skill: { id: string }) => `project:test-project:${skill.id}`,
  toggleSkill: vi.fn(),
  updateSkillFiles: vi.fn().mockResolvedValue({ status: "ok" }),
}));

function PageNavigation({ onNavigate }: { onNavigate: () => void }) {
  const { requestNavigation } = useNavigationGuard();
  return <button onClick={() => requestNavigation(onNavigate)}>切換頁面</button>;
}

function renderPage(onNavigate = vi.fn()) {
  render(
    <NavigationGuardProvider>
      <Tools />
      <PageNavigation onNavigate={onNavigate} />
    </NavigationGuardProvider>,
  );
  return onNavigate;
}

async function editAlpha() {
  const buttons = await screen.findAllByRole("button", { name: "編輯" });
  fireEvent.click(buttons[0]);
  const editor = await screen.findByRole("textbox", { name: "alpha skill.yaml 內容" });
  await waitFor(() => expect((editor as HTMLTextAreaElement).value).toBe("name: alpha"));
  fireEvent.change(editor, { target: { value: "未儲存的草稿" } });
  return editor as HTMLTextAreaElement;
}

describe("Tools draft protection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("keeps a draft on cancel and closes only after discard is confirmed", async () => {
    renderPage();
    const editor = await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /關閉/ }));
    expect(screen.getByText("尚有未儲存的變更")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(editor.value).toBe("未儲存的草稿");

    fireEvent.click(screen.getByRole("button", { name: /關閉/ }));
    fireEvent.click(screen.getByRole("button", { name: "捨棄並離開" }));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "alpha skill.yaml 內容" })).toBeNull());
    expect(updateSkillFiles).not.toHaveBeenCalled();
  });

  it("guards switching skills and global navigation", async () => {
    const onNavigate = renderPage();
    await editAlpha();
    fireEvent.click(screen.getAllByRole("button", { name: "編輯" })[1]);
    expect(fetchSkillFiles).not.toHaveBeenCalledWith("beta", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    fireEvent.click(screen.getByRole("button", { name: "切換頁面" }));
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    fireEvent.click(screen.getAllByRole("button", { name: "編輯" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "捨棄並離開" }));
    expect(await screen.findByRole("textbox", { name: "beta skill.yaml 內容" })).toBeTruthy();
  });

  it("clears protection after saving successfully", async () => {
    const onNavigate = renderPage();
    await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));
    await waitFor(() => expect(updateSkillFiles).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByText("未儲存")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "切換頁面" }));
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("protects a draft in a new file absent from the original response", async () => {
    vi.mocked(fetchSkillFiles).mockResolvedValueOnce({
      skill_id: "alpha",
      files: { "main.py": "pass" },
    });
    renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: "編輯" }))[0]);
    const editor = await screen.findByRole("textbox", { name: "alpha skill.yaml 內容" });
    fireEvent.change(editor, { target: { value: "name: alpha" } });
    fireEvent.click(screen.getByRole("button", { name: /關閉/ }));
    expect(screen.getByText("尚有未儲存的變更")).toBeTruthy();
  });

  // Brain 收到 main.py 就整包拒絕；以前整包送出，連只改 skill.yaml 都存不了。
  it("saves only the changed files and never main.py", async () => {
    renderPage();
    await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: "main.py" }));
    const code = screen.getByRole("textbox", { name: "alpha main.py 內容" }) as HTMLTextAreaElement;
    expect(code.readOnly).toBe(true);
    expect(screen.getByText(/main\.py）不能在這裡修改/)).toBeTruthy();
    fireEvent.change(code, { target: { value: "print('pwned')" } });
    expect(code.value).toBe("pass");

    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));
    await waitFor(() => expect(updateSkillFiles).toHaveBeenCalledOnce());
    expect(vi.mocked(updateSkillFiles).mock.calls[0][1]).toEqual({ "skill.yaml": "未儲存的草稿" });
  });

  it("blocks editing and saving when the skill files fail to load", async () => {
    vi.mocked(fetchSkillFiles).mockRejectedValueOnce(new Error("讀取失敗"));
    const onNavigate = renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: "編輯" }))[0]);

    expect(await screen.findByText(/無法載入技能檔案/)).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "alpha skill.yaml 內容" })).toBeNull();
    const save = screen.getByRole("button", { name: /儲存並重載/ }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(updateSkillFiles).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "切換頁面" }));
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("does not offer to discard a draft while its save is still running", async () => {
    let finishSave!: () => void;
    vi.mocked(updateSkillFiles).mockImplementationOnce(() => new Promise((resolve) => {
      finishSave = () => resolve({ status: "ok", skill_id: "alpha", enabled: true });
    }));
    renderPage();
    await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));

    const close = screen.getByRole("button", { name: /儲存完才能關閉/ }) as HTMLButtonElement;
    expect(close.disabled).toBe(true);
    fireEvent.click(close);
    expect(screen.queryByRole("dialog", { name: "尚有未儲存的變更" })).toBeNull();

    finishSave();
    await waitFor(() => expect(screen.queryByText("未儲存")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /關閉/ }));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "alpha skill.yaml 內容" })).toBeNull());
    expect(screen.queryByRole("dialog", { name: "尚有未儲存的變更" })).toBeNull();
  });

  it("keeps protecting edits made while an earlier save is pending", async () => {
    let finishSave!: () => void;
    vi.mocked(updateSkillFiles).mockImplementationOnce(() => new Promise((resolve) => {
      finishSave = () => resolve({ status: "ok", skill_id: "alpha", enabled: true });
    }));
    const onNavigate = renderPage();
    const editor = await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));
    fireEvent.change(editor, { target: { value: "儲存期間的新草稿" } });
    finishSave();
    await waitFor(() => expect(screen.getByRole("button", { name: /儲存並重載/ })).toBeTruthy());
    expect(editor.value).toBe("儲存期間的新草稿");
    expect(screen.getByText("未儲存")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "切換頁面" }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByText("尚有未儲存的變更")).toBeTruthy();
  });

  it("switches skills after a pending save succeeds without asking to discard", async () => {
    let finishSave!: () => void;
    vi.mocked(updateSkillFiles).mockImplementationOnce(() => new Promise((resolve) => {
      finishSave = () => resolve({ status: "ok", skill_id: "alpha", enabled: true });
    }));
    renderPage();
    await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "編輯" })[1]);
    expect(screen.queryByRole("dialog", { name: "尚有未儲存的變更" })).toBeNull();
    expect(fetchSkillFiles).not.toHaveBeenCalledWith("beta", expect.anything());

    finishSave();
    expect(await screen.findByRole("textbox", { name: "beta skill.yaml 內容" })).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "尚有未儲存的變更" })).toBeNull();
  });

  it("asks before leaving when a pending save fails", async () => {
    let failSave!: () => void;
    vi.mocked(updateSkillFiles).mockImplementationOnce(() => new Promise((_, reject) => {
      failSave = () => reject(new Error("寫入失敗"));
    }));
    const onNavigate = renderPage();
    const editor = await editAlpha();
    fireEvent.click(screen.getByRole("button", { name: /儲存並重載/ }));
    fireEvent.click(screen.getByRole("button", { name: "切換頁面" }));
    expect(screen.queryByRole("dialog", { name: "尚有未儲存的變更" })).toBeNull();

    failSave();
    expect(await screen.findByRole("dialog", { name: "尚有未儲存的變更" })).toBeTruthy();
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(editor.value).toBe("未儲存的草稿");
    expect(screen.getByText(/寫入失敗/)).toBeTruthy();
  });
});
