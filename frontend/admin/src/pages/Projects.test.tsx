import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Projects from "./Projects";

const authState = vi.hoisted(() => ({
  role: "user" as "root" | "admin" | "user",
  vendorName: null as string | null,
}));

const projectsState = vi.hoisted(() => ({
  fetchProjects: vi.fn(),
  createProject: vi.fn(),
  setProjectVendor: vi.fn(),
  refreshProjects: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    account: {
      id: "account-a",
      username: "account-a",
      role: authState.role,
      vendor_name: authState.vendorName,
    },
  }),
}));

vi.mock("../api/projects", () => ({
  fetchProjects: projectsState.fetchProjects,
  createProject: projectsState.createProject,
  setProjectVendor: projectsState.setProjectVendor,
  deleteProject: vi.fn(),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({
    refreshProjects: projectsState.refreshProjects,
    setProjectId: vi.fn(),
    projectId: "project-a",
  }),
}));

const project = {
  project_id: "project-a",
  label: "專案 A",
  document_count: 2,
  persona_count: 1,
};

function mockFeatureSettings(read: Response, write?: Response) {
  const fetch = vi.fn().mockResolvedValueOnce(read);
  if (write) fetch.mockResolvedValueOnce(write);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function openFeatureSettings() {
  fireEvent.click(await screen.findByRole("button", { name: "回答功能" }));
  return within(screen.getByRole("dialog", { name: "回答功能：專案 A" }));
}

describe("Projects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "user";
    authState.vendorName = null;
    projectsState.fetchProjects.mockResolvedValue({ projects: [project] });
    projectsState.createProject.mockResolvedValue({ project_id: "project-b" });
    projectsState.setProjectVendor.mockResolvedValue(undefined);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("lets portal users view granted projects without lifecycle controls", async () => {
    const reader = render(<Projects />);

    expect(await screen.findByText("專案 A")).toBeTruthy();
    expect(screen.getByText(/可以查看下方已授權的專案/)).toBeTruthy();
    expect(screen.queryByText("建立新專案")).toBeNull();
    expect(screen.queryByRole("button", { name: "刪除專案" })).toBeNull();
    expect(screen.queryByRole("button", { name: "設定所屬廠商" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gemini 金鑰" })).toBeNull();
    expect(screen.queryByRole("button", { name: "回答功能" })).toBeNull();
    reader.unmount();

    authState.vendorName = "合作廠商甲";
    projectsState.fetchProjects.mockResolvedValue({ projects: [{ ...project, can_edit_features: true }] });
    render(<Projects />);
    await screen.findByText("專案 A");
    expect(screen.queryByRole("button", { name: "回答功能" })).toBeNull();
  });

  it("shows project lifecycle controls to administrators", async () => {
    authState.role = "admin";

    render(<Projects />);

    expect(screen.getByText("建立新專案")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "刪除專案" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Gemini 金鑰" })).toBeNull();
  });

  it("shows the Gemini credential entry only to ROOT", async () => {
    authState.role = "root";
    render(<Projects />);
    expect(await screen.findByRole("button", { name: "Gemini 金鑰" })).toBeTruthy();
  });

  it("lets administrators set the vendor when creating a project", async () => {
    authState.role = "admin";
    render(<Projects />);
    await screen.findByText("專案 A");
    fireEvent.change(screen.getByRole("textbox", { name: "專案名稱" }), { target: { value: " 新專案 " } });
    fireEvent.change(screen.getByRole("textbox", { name: "所屬廠商" }), { target: { value: " 合作廠商甲 " } });
    fireEvent.click(screen.getByRole("button", { name: "建立專案" }));
    await waitFor(() => expect(projectsState.createProject).toHaveBeenCalledWith("新專案", "合作廠商甲"));
    expect(await screen.findByText("project-b")).toBeTruthy();
  });

  it("creates a project with both switches off unless they are ticked", async () => {
    authState.role = "admin";
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<Projects />);
    await screen.findByText("專案 A");
    expect(screen.getByRole("checkbox", { name: /記憶/ })).toHaveProperty("checked", false);
    expect(screen.getByRole("checkbox", { name: /知識圖譜擴展/ })).toHaveProperty("checked", false);
    fireEvent.change(screen.getByRole("textbox", { name: "專案名稱" }), { target: { value: "展場" } });
    fireEvent.click(screen.getByRole("button", { name: "建立專案" }));
    await waitFor(() => expect(projectsState.createProject).toHaveBeenCalledWith("展場", undefined));
    await screen.findByText("project-b");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("turns on only the ticked switch right after creating the project", async () => {
    authState.role = "admin";
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      language_routes: [], reply_seconds: 20, memory_enabled: true, graph_enabled: false,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    render(<Projects />);
    await screen.findByText("專案 A");
    fireEvent.change(screen.getByRole("textbox", { name: "專案名稱" }), { target: { value: "門市客服" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /記憶/ }));
    fireEvent.click(screen.getByRole("button", { name: "建立專案" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toContain("/knowledge/features");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ project_id: "project-b", memory_enabled: true });
    expect(await screen.findByText(/已建立（ID: project-b）/)).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /記憶/ })).toHaveProperty("checked", false);
  });

  it("says where to retry when the switch could not be saved after creating", async () => {
    authState.role = "admin";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 500 })));
    render(<Projects />);
    await screen.findByText("專案 A");
    fireEvent.change(screen.getByRole("textbox", { name: "專案名稱" }), { target: { value: "門市客服" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /知識圖譜擴展/ }));
    fireEvent.click(screen.getByRole("button", { name: "建立專案" }));
    expect(await screen.findByText(/請在專案卡片按「回答功能」再設定一次/)).toBeTruthy();
  });

  it("updates an existing project vendor and refreshes the project list", async () => {
    authState.role = "admin";
    render(<Projects />);
    fireEvent.click(await screen.findByRole("button", { name: "設定所屬廠商" }));
    const dialog = screen.getByRole("dialog", { name: "設定「專案 A」的所屬廠商" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "所屬廠商" }), {
      target: { value: " 合作廠商甲 " },
    });
    projectsState.fetchProjects.mockResolvedValue({ projects: [{ ...project, vendor_name: "合作廠商甲" }] });
    fireEvent.click(within(dialog).getByRole("button", { name: "儲存所屬廠商" }));
    expect(await screen.findByText("所屬廠商：合作廠商甲")).toBeTruthy();
    expect(projectsState.setProjectVendor).toHaveBeenCalledWith("project-a", "合作廠商甲");
    expect(projectsState.refreshProjects).toHaveBeenCalledOnce();
  });

  it("shows new project switches off and saves changes only for the selected project", async () => {
    projectsState.fetchProjects.mockResolvedValue({ projects: [{ ...project, can_edit_features: true }] });
    const fetch = mockFeatureSettings(
      Response.json({ language_routes: ["zh"], memory_enabled: false, graph_enabled: false }),
      Response.json({ language_routes: ["zh"], memory_enabled: true, graph_enabled: false }),
    );
    render(<Projects />);

    const dialog = await openFeatureSettings();
    const memory = await dialog.findByRole("switch", { name: "記憶", checked: false });
    const graph = dialog.getByRole("switch", { name: "知識圖譜擴展", checked: false });
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/knowledge/settings?project_id=project-a");
    fireEvent.click(memory);
    fireEvent.click(graph);
    expect(dialog.getByRole("switch", { name: "記憶", checked: true })).toBeTruthy();
    expect(dialog.getByRole("switch", { name: "知識圖譜擴展", checked: true })).toBeTruthy();
    fireEvent.click(graph);
    fireEvent.click(dialog.getByRole("button", { name: "儲存" }));

    expect(await screen.findByText("已儲存回答功能設定。")).toBeTruthy();
    expect(fetch.mock.calls[1][0]).toBe("/api/v1/knowledge/features");
    expect(fetch.mock.calls[1][1].method).toBe("PATCH");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      project_id: "project-a", memory_enabled: true,
    });
  });

  it("shows enabled switches and saves a graph-only change after discarding a draft", async () => {
    authState.role = "admin";
    projectsState.fetchProjects.mockResolvedValue({ projects: [{ ...project, can_edit_features: true }] });
    const enabled = { language_routes: ["zh"], memory_enabled: true, graph_enabled: true };
    const fetch = mockFeatureSettings(Response.json(enabled));
    fetch.mockResolvedValueOnce(Response.json(enabled));
    fetch.mockResolvedValueOnce(Response.json({ ...enabled, graph_enabled: false }));
    render(<Projects />);

    const dialog = await openFeatureSettings();
    const graph = await dialog.findByRole("switch", { name: "知識圖譜擴展", checked: true });
    expect(dialog.getByRole("switch", { name: "記憶", checked: true })).toBeTruthy();
    fireEvent.click(graph);
    fireEvent.click(dialog.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog", { name: "回答功能：專案 A" })).toBeNull();
    expect(fetch).toHaveBeenCalledOnce();

    const reopened = await openFeatureSettings();
    fireEvent.click(await reopened.findByRole("switch", { name: "知識圖譜擴展", checked: true }));
    fireEvent.click(reopened.getByRole("button", { name: "儲存" }));
    expect(await screen.findByText("已儲存回答功能設定。")).toBeTruthy();
    expect(fetch.mock.calls[2][0]).toBe("/api/v1/knowledge/features");
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({
      project_id: "project-a", graph_enabled: false,
    });
  });

  it("keeps saving disabled when the current switches could not be loaded", async () => {
    projectsState.fetchProjects.mockResolvedValue({ projects: [{ ...project, can_edit_features: true }] });
    const fetch = mockFeatureSettings(Response.json({ detail: "讀取失敗" }, { status: 503 }));
    render(<Projects />);

    const dialog = await openFeatureSettings();
    expect((await dialog.findByRole("alert")).textContent).toContain("讀取失敗");
    expect(dialog.queryByRole("switch")).toBeNull();
    expect(dialog.getByRole<HTMLButtonElement>("button", { name: "儲存" }).disabled).toBe(true);
    expect(fetch).toHaveBeenCalledOnce();
  });
});
