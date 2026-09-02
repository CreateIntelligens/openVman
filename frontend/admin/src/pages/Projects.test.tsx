import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Projects from "./Projects";

const authState = vi.hoisted(() => ({
  role: "user" as "root" | "admin" | "user",
}));

const projectsState = vi.hoisted(() => ({
  handleCreate: vi.fn(),
  handleDelete: vi.fn(),
  loadProjects: vi.fn(),
  setDeleteTargetId: vi.fn(),
  setNewProjectLabel: vi.fn(),
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

vi.mock("../hooks/useProjectsAdmin", () => ({
  useProjectsAdmin: () => ({
    canCreateProject: true,
    creating: false,
    deleteTargetId: "",
    deletingId: "",
    handleCreate: projectsState.handleCreate,
    handleDelete: projectsState.handleDelete,
    lastCreatedId: "",
    loadProjects: projectsState.loadProjects,
    loading: false,
    newProjectLabel: "",
    projects: [
      {
        project_id: "project-a",
        label: "專案 A",
        document_count: 2,
        persona_count: 1,
      },
    ],
    setDeleteTargetId: projectsState.setDeleteTargetId,
    setNewProjectLabel: projectsState.setNewProjectLabel,
    status: null,
  }),
}));

describe("Projects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "user";
  });

  it("lets portal users view granted projects without lifecycle controls", () => {
    render(<Projects />);

    expect(screen.getByText("專案 A")).toBeTruthy();
    expect(screen.getByText(/可以編輯下方已授權專案的內容/)).toBeTruthy();
    expect(screen.queryByText("建立新專案")).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete Project" })).toBeNull();
  });

  it("shows project lifecycle controls to administrators", () => {
    authState.role = "admin";

    render(<Projects />);

    expect(screen.getByText("建立新專案")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete Project" })).toBeTruthy();
  });
});
