import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchProjectsMock = vi.hoisted(() => vi.fn());
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  fetchProjects: fetchProjectsMock,
}));

import { ProjectProvider, useProject } from "./ProjectContext";

function Probe() {
  const { projectId, hasLoadedProjects } = useProject();
  return <span>{hasLoadedProjects ? `selected:${projectId}` : "loading"}</span>;
}

const summary = (project_id: string, is_default = false) => ({
  project_id, label: project_id, document_count: 0, persona_count: 0, is_default,
});

describe("ProjectProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/admin/chat");
    fetchProjectsMock.mockReset();
  });

  it("falls back to the deployment's default project, not the first one listed", async () => {
    // default 專案拔掉後，存的 "default" 已不在清單裡；要落到醫院專案而不是字母序第一個。
    fetchProjectsMock.mockResolvedValue({
      projects: [summary("aws-dev"), summary("hospital", true), summary("test")],
      project_count: 3,
    });
    render(<ProjectProvider><Probe /></ProjectProvider>);
    expect(await screen.findByText("selected:hospital")).toBeTruthy();
  });

  it("keeps the first project when no project is marked default", async () => {
    fetchProjectsMock.mockResolvedValue({
      projects: [summary("aws-dev"), summary("test")],
      project_count: 2,
    });
    render(<ProjectProvider><Probe /></ProjectProvider>);
    expect(await screen.findByText("selected:aws-dev")).toBeTruthy();
  });
});
