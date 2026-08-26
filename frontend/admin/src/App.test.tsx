import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

vi.mock("./api/auth", () => ({
  AdminPortalAccessError: class AdminPortalAccessError extends Error {},
  getCurrentAccount: vi.fn().mockResolvedValue({
    id: "admin-1",
    username: "admin",
    role: "admin",
    disabled: false,
    created_at: "2026-08-17T00:00:00Z",
  }),
  login: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
  temporaryLogin: vi.fn(),
  isAtLeastAdmin: (role: string) => role === "root" || role === "admin",
}));

vi.mock("./pages/Avatar", () => ({
  default: () => <div data-testid="tab-avatar">Avatar tab</div>,
}));
vi.mock("./pages/Accounts", () => ({
  default: () => <div data-testid="tab-accounts">Accounts tab</div>,
}));
vi.mock("./pages/Chat", () => ({
  default: () => <div data-testid="tab-chat">Chat tab</div>,
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
import { fetchProjects } from "./api";
import {
  AdminPortalAccessError,
  getCurrentAccount,
  temporaryLogin,
} from "./api/auth";
import { allTabs } from "./components/app/navigation";

describe("App tab mounting", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/admin/");
    vi.clearAllMocks();
    vi.mocked(getCurrentAccount).mockResolvedValue({
      id: "admin-1",
      username: "admin",
      role: "admin",
      disabled: false,
      created_at: "2026-08-17T00:00:00Z",
    });
    vi.mocked(temporaryLogin).mockResolvedValue({
      id: "temporary-1",
      username: "臨時帳號",
      role: "user",
      kind: "temporary",
      disabled: false,
      created_at: "2026-08-26T00:00:00Z",
      admin_portal_access: true,
    });
    vi.mocked(fetchProjects).mockResolvedValue({
      project_count: 1,
      projects: [
        {
          project_id: "default",
          label: "Default",
          document_count: 0,
          persona_count: 0,
        },
      ],
    });
  });

  it("mounts only the active tab content", async () => {
    window.localStorage.setItem("brain-active-tab", "Chat");

    const { unmount } = render(<App />);

    expect(await screen.findByTestId("tab-chat")).toBeTruthy();
    expect(screen.queryByTestId("tab-avatar")).toBeNull();

    unmount();
  });

  it("does not expose Embed Keys navigation", () => {
    expect(allTabs.some((tab) => String(tab.key) === "EmbedKeys")).toBe(false);
  });

  it("restores a deep-linked tab and keeps tab changes in the URL", async () => {
    window.history.replaceState(null, "", "/admin/health?project=default");
    render(<App />);

    expect(await screen.findByTestId("tab-health")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /Chat/ })[0]);

    expect(await screen.findByTestId("tab-chat")).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/chat");
  });

  it("shows a project loading error and retries without hiding the active project", async () => {
    vi.mocked(fetchProjects)
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce({
        project_count: 1,
        projects: [
          {
            project_id: "default",
            label: "Default",
            document_count: 0,
            persona_count: 0,
          },
        ],
      });
    render(<App />);

    const trigger = await screen.findByRole("button", {
      name: "目前專案：default",
    });
    fireEvent.click(trigger);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "network unavailable",
    );

    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    await waitFor(() => expect(fetchProjects).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("button", { name: "目前專案：Default" }),
    ).toBeTruthy();
  });

  it("blocks the account page for a normal user", async () => {
    window.history.replaceState(null, "", "/admin/accounts");
    vi.mocked(getCurrentAccount).mockResolvedValue({
      id: "user-1",
      username: "viewer",
      role: "user",
      disabled: false,
      created_at: "2026-08-17T00:00:00Z",
    });

    render(<App />);

    expect(await screen.findByText("權限不足")).toBeTruthy();
    expect(screen.queryByTestId("tab-accounts")).toBeNull();
  });

  it("blocks Admin portal bootstrap without discarding the frontend session", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(
      new AdminPortalAccessError("Admin portal access required"),
    );

    render(<App />);

    expect(await screen.findByText("無法進入管理後台")).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往虛擬人前台" })).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/");
  });

  it("lets an authorized temporary account log in directly", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(new Error("not signed in"));
    vi.mocked(temporaryLogin).mockResolvedValue({
      id: "temporary-1",
      username: "臨時帳號",
      role: "user",
      kind: "temporary",
      disabled: false,
      created_at: "2026-08-26T00:00:00Z",
      admin_portal_access: true,
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "臨時密碼" }));
    fireEvent.change(screen.getByLabelText("臨時密碼"), {
      target: { value: "temporary-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登入" }));

    await waitFor(() => expect(temporaryLogin).toHaveBeenCalledWith(
      "temporary-password",
    ));
    expect(await screen.findByTestId("tab-chat")).toBeTruthy();
  });

  it("grants ROOT the existing administrator navigation and account route", async () => {
    window.history.replaceState(null, "", "/admin/accounts");
    vi.mocked(getCurrentAccount).mockResolvedValue({
      id: "root-1",
      username: "ai360",
      role: "root",
      disabled: false,
      created_at: "2026-08-24T00:00:00Z",
    });

    render(<App />);

    expect(await screen.findByTestId("tab-accounts")).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: /Accounts/ }).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("權限不足")).toBeNull();
  });

  it("keeps the mascot from covering account administration controls", async () => {
    window.history.replaceState(null, "", "/admin/accounts");

    render(<App />);

    expect(await screen.findByTestId("tab-accounts")).toBeTruthy();
    expect(screen.queryByTitle("AI 虛擬人小助理")).toBeNull();
  });
});
