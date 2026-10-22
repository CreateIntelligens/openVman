import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Personas from "./Personas";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import { deletePersona, fetchKnowledgeDocument, saveKnowledgeDocument } from "../api";

// 未存提醒用真的 NavigationGuardProvider 與編輯器，只把 API 換掉。

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "proj-test" }),
}));

const PERSONAS = [
  { persona_id: "default", label: "預設", path: "SOUL.md", preview: "", is_default: true, avatar_char_id: null },
  { persona_id: "nurse", label: "護理師", path: "personas/nurse/SOUL.md", preview: "", is_default: false, avatar_char_id: null },
];

vi.mock("../api", () => ({
  clonePersona: vi.fn(),
  createPersona: vi.fn(),
  deletePersona: vi.fn().mockResolvedValue({ status: "ok" }),
  fetchAvatarCharacters: vi.fn().mockResolvedValue({ characters: [] }),
  fetchAvatarMascots: vi.fn().mockResolvedValue({ mascots: [] }),
  fetchKnowledgeDocument: vi.fn(async (path: string) => ({ path, content: `內容：${path}` })),
  fetchPersonas: vi.fn(async () => ({ personas: PERSONAS })),
  saveKnowledgeDocument: vi.fn().mockResolvedValue({ status: "ok" }),
  setPersonaAvatar: vi.fn().mockResolvedValue({ status: "ok" }),
}));

function renderPage() {
  render(
    <NavigationGuardProvider>
      <Personas />
    </NavigationGuardProvider>,
  );
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

  it("asks before switching persona and keeps the draft when the user stays", async () => {
    renderPage();
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

  it("asks before switching document tabs with unsaved edits", async () => {
    renderPage();
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：SOUL.md"));
    fireEvent.change(draft, { target: { value: "還沒存的修改" } });

    fireEvent.click(screen.getByRole("button", { name: /AGENTS\.md/ }));
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    expect(opened()).not.toContain("AGENTS.md");
  });

  it("stays on AGENTS.md after saving it instead of jumping back to SOUL.md", async () => {
    renderPage();
    await waitFor(() => expect(opened()).toEqual(["SOUL.md"]));
    fireEvent.click(screen.getByRole("button", { name: /AGENTS\.md/ }));
    const draft = await editor("預設");
    await waitFor(() => expect(draft.value).toBe("內容：AGENTS.md"));

    fireEvent.change(draft, { target: { value: "新的 AGENTS" } });
    fireEvent.click(screen.getByRole("button", { name: /儲存設定/ }));
    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledWith("AGENTS.md", "新的 AGENTS"));
    await waitFor(() => expect(screen.getByText("已儲存 AGENTS.md")).toBeTruthy());
    expect((await editor("預設")).value).toBe("新的 AGENTS");
    expect(opened()).toEqual(["SOUL.md", "AGENTS.md"]);
  });

  it("opens the first persona after deleting the selected one", async () => {
    renderPage();
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
});
