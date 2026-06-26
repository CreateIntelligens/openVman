import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  fetchProjects: vi.fn().mockResolvedValue({
    project_count: 1,
    projects: [
      {
        project_id: "default",
        label: "Default",
        document_count: 0,
        persona_count: 0,
      },
    ],
  }),
  setActiveProjectId: vi.fn(),
}));

vi.mock("./api/metrics", () => ({
  fetchHealth: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("./pages/Avatar", () => ({
  default: () => <div data-testid="tab-avatar">Avatar tab</div>,
}));
vi.mock("./pages/Chat", () => ({
  default: () => <div data-testid="tab-chat">Chat tab</div>,
}));
vi.mock("./pages/EmbedKeys", () => ({
  default: () => <div data-testid="tab-embed-keys">Embed keys tab</div>,
}));
vi.mock("./pages/Health", () => ({
  default: () => <div data-testid="tab-health">Health tab</div>,
}));
vi.mock("./pages/KnowledgeBase", () => ({
  default: () => <div data-testid="tab-knowledge-base">Knowledge tab</div>,
}));
vi.mock("./pages/Memory", () => ({
  default: () => <div data-testid="tab-memory">Memory tab</div>,
}));
vi.mock("./pages/Monitoring", () => ({
  default: () => <div data-testid="tab-monitoring">Monitoring tab</div>,
}));
vi.mock("./pages/Personas", () => ({
  default: () => <div data-testid="tab-personas">Personas tab</div>,
}));
vi.mock("./pages/Projects", () => ({
  default: () => <div data-testid="tab-projects">Projects tab</div>,
}));
vi.mock("./pages/Search", () => ({
  default: () => <div data-testid="tab-search">Search tab</div>,
}));
vi.mock("./pages/Tools", () => ({
  default: () => <div data-testid="tab-tools">Tools tab</div>,
}));
vi.mock("./pages/Workspace", () => ({
  default: () => <div data-testid="tab-workspace">Workspace tab</div>,
}));

import App from "./App";

describe("App tab mounting", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("mounts only the active tab content", async () => {
    window.localStorage.setItem("brain-active-tab", "Chat");

    const { unmount } = render(<App />);

    expect(await screen.findByTestId("tab-chat")).toBeTruthy();
    expect(screen.queryByTestId("tab-avatar")).toBeNull();

    unmount();
  });
});
