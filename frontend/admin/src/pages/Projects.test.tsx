import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Projects from "./Projects";

const authState = vi.hoisted(() => ({
  role: "user" as "root" | "admin" | "user",
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

describe("Projects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "user";
    projectsState.fetchProjects.mockResolvedValue({ projects: [project] });
    projectsState.createProject.mockResolvedValue({ project_id: "project-b" });
    projectsState.setProjectVendor.mockResolvedValue(undefined);
  });

  it("lets portal users view granted projects without lifecycle controls", async () => {
    render(<Projects />);

    expect(await screen.findByText("專案 A")).toBeTruthy();
    expect(screen.getByText(/可以查看下方已授權的專案/)).toBeTruthy();
    expect(screen.queryByText("建立新專案")).toBeNull();
    expect(screen.queryByRole("button", { name: "刪除專案" })).toBeNull();
    expect(screen.queryByRole("button", { name: "設定所屬廠商" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gemini 金鑰" })).toBeNull();
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
});
