import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Tools from "./Tools";
import { createSkill, fetchSkillFiles, toggleSkill, updateSkillFiles } from "../api";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";

const auth = vi.hoisted(() => ({ role: "admin" }));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { role: auth.role } }),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "test-project" }),
}));

vi.mock("../api", () => ({
  createSkill: vi.fn(async () => ({ status: "ok" })),
  deleteSkill: vi.fn(),
  fetchTools: vi.fn(async () => ({
    tools: [],
    skill_tools: [],
    skills: [
      {
        id: "joke", name: "笑話", description: "", version: "1", scope: "shared",
        project_id: null, enabled: true, tools: [], warnings: [],
      },
      {
        id: "menu", name: "菜單", description: "", version: "1", scope: "project",
        project_id: "test-project", enabled: true, tools: [], warnings: [],
      },
    ],
  })),
  fetchSkillFiles: vi.fn(async (id: string) => ({
    skill_id: id,
    files: { "skill.yaml": `name: ${id}`, "main.py": "pass" },
  })),
  reloadAllSkills: vi.fn(),
  skillKey: (skill: { id: string; scope?: string }) => `${skill.scope}:${skill.id}`,
  toggleSkill: vi.fn(async () => ({ enabled: false })),
  updateSkillFiles: vi.fn(),
}));

function renderPage() {
  render(
    <NavigationGuardProvider>
      <Tools />
    </NavigationGuardProvider>,
  );
}

function section(title: string): HTMLElement {
  return screen.getByRole("heading", { name: new RegExp(title) }).closest("section") as HTMLElement;
}

async function expectSharedSkillsViewOnly() {
  const shared = within(section("共用技能"));
  expect(shared.getByText(/內容要更新系統才能修改/)).toBeTruthy();
  expect(shared.queryByRole("button", { name: "編輯" })).toBeNull();
  expect(shared.queryByRole("button", { name: /刪除/ })).toBeNull();

  fireEvent.click(shared.getByRole("button", { name: "檢視" }));
  const editor = await screen.findByRole("textbox", { name: "joke skill.yaml 內容" });
  expect((editor as HTMLTextAreaElement).readOnly).toBe(true);
  expect(screen.queryByRole("button", { name: /儲存並重載/ })).toBeNull();
  expect(fetchSkillFiles).toHaveBeenCalledWith("joke", { scope: "shared", project_id: undefined });
  expect(updateSkillFiles).not.toHaveBeenCalled();
  return shared;
}

describe("Tools permissions for shared skills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows shared skills view-only to a non-root account, switch included", async () => {
    auth.role = "admin";
    renderPage();
    await screen.findByText("笑話");

    const shared = await expectSharedSkillsViewOnly();
    expect(shared.getByText(/要啟用或停用請找最高管理員/)).toBeTruthy();
    const toggle = shared.getByRole("switch") as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    fireEvent.click(toggle);
    expect(toggleSkill).not.toHaveBeenCalled();
  });

  // 2026-11-18：正式環境共用技能目錄唯讀，ROOT 也只能檢視，只多一個開關。
  it("lets root only view and switch shared skills on or off", async () => {
    auth.role = "root";
    renderPage();
    await screen.findByText("笑話");

    const shared = await expectSharedSkillsViewOnly();
    expect(shared.getByText(/這裡只能查看，以及啟用或停用/)).toBeTruthy();
    const toggle = shared.getByRole("switch") as HTMLButtonElement;
    expect(toggle.disabled).toBe(false);
    fireEvent.click(toggle);
    expect(toggleSkill).toHaveBeenCalledWith("joke", { scope: "shared", project_id: undefined });
  });

  it.each(["user", "root"])("keeps project skills editable for %s", async (role) => {
    auth.role = role;
    renderPage();
    await screen.findByText("菜單");

    const project = within(section("專案技能"));
    expect(project.getByRole("button", { name: "編輯" })).toBeTruthy();
    expect(project.getByRole("button", { name: "刪除 菜單" })).toBeTruthy();
    expect((project.getByRole("switch") as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["admin", "root"])("creates skills only in the current project for %s", async (role) => {
    auth.role = role;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /建立技能/ }));

    expect(screen.queryByRole("button", { name: "共用" })).toBeNull();
    expect(screen.getByText(/建立在目前專案（test-project）/)).toBeTruthy();
  });

  it("asks for a safe skill ID when the name cannot become one", async () => {
    auth.role = "user";
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /建立技能/ }));
    fireEvent.change(screen.getByPlaceholderText("我的技能"), { target: { value: "笑話" } });

    const create = screen.getByRole("button", { name: /建立$/ }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    expect(screen.getByText(/不能以數字開頭/)).toBeTruthy();
    const idInput = screen.getByLabelText("技能 ID");
    fireEvent.change(idInput, { target: { value: "9lives" } });
    expect(create.disabled).toBe(true);
    fireEvent.change(idInput, { target: { value: "joke_2" } });
    expect(create.disabled).toBe(false);

    fireEvent.click(create);
    expect(createSkill).toHaveBeenCalledWith("joke_2", "笑話", "", "test-project");
  });
});
