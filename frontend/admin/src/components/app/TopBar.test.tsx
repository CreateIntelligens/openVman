import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AccountProfile } from "../../api/auth";
import type { CollapsedGroups } from "../../hooks/useNavigationGroups";
import TopBar, { MobileNavDrawer } from "./TopBar";

const account: AccountProfile = {
  id: "user-1",
  username: "王小明",
  role: "user",
  kind: "formal",
  disabled: false,
  created_at: "2026-01-01T00:00:00Z",
  admin_portal_access: true,
};

function renderTopBar(overrides: Partial<Parameters<typeof TopBar>[0]> = {}) {
  return render(
    <TopBar
      active="KnowledgeBase"
      projectId="p1"
      projects={[{ project_id: "p1", label: "一個名稱很長很長的測試專案" }]}
      loadingProjects={false}
      projectError={null}
      theme="light"
      account={account}
      onSelectProject={vi.fn()}
      onRetryProjects={vi.fn()}
      onToggleTheme={vi.fn()}
      onOpenMobileNav={vi.fn()}
      onLogout={vi.fn()}
      onOpenApiKeys={vi.fn()}
      {...overrides}
    />,
  );
}

function isBefore(first: HTMLElement, second: HTMLElement): boolean {
  return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("TopBar", () => {
  it("puts the project switcher first and the account controls on the right", () => {
    renderTopBar();
    const project = screen.getByRole("button", { name: /目前專案/ });
    const apiKeys = screen.getByRole("button", { name: "管理帳號 API 金鑰" });
    const username = screen.getByText("王小明");
    const logout = screen.getByRole("button", { name: "登出" });
    const theme = screen.getByRole("button", { name: "切換深色模式" });

    expect(isBefore(project, apiKeys)).toBe(true);
    expect(isBefore(apiKeys, username)).toBe(true);
    expect(isBefore(username, logout)).toBe(true);
    expect(isBefore(logout, theme)).toBe(true);
  });

  it("lets a long project name shrink instead of pushing the bar wider", () => {
    renderTopBar();
    const project = screen.getByRole("button", { name: /目前專案/ });
    const name = within(project).getByText("一個名稱很長很長的測試專案");

    expect(name.className).toContain("max-w-[16rem]");
    expect(name.className).toContain("truncate");
    expect(name.className).toContain("min-w-0");
    expect(project.parentElement!.className).toContain("min-w-0");
  });

  it("shows the logout button with its text and calls logout", () => {
    const onLogout = vi.fn();
    renderTopBar({ onLogout });
    const logout = screen.getByRole("button", { name: "登出" });

    expect(logout.textContent).toContain("登出");
    fireEvent.click(logout);
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("hides the API key entry from temporary accounts", () => {
    renderTopBar({ account: { ...account, kind: "temporary" } });
    expect(screen.queryByRole("button", { name: "管理帳號 API 金鑰" })).toBeNull();
    expect(screen.getByRole("button", { name: "登出" })).toBeTruthy();
  });

  it("only shows internal project ids when two projects share a name", () => {
    const { unmount } = renderTopBar({
      projects: [
        { project_id: "proj-a", label: "鶴記" },
        { project_id: "proj-b", label: "醫院" },
      ],
      projectId: "proj-a",
    });
    fireEvent.click(screen.getByRole("button", { name: /目前專案/ }));
    expect(screen.getByRole("listbox", { name: "切換專案" })).toBeTruthy();
    expect(screen.queryByText("proj-a")).toBeNull();
    unmount();

    renderTopBar({
      projects: [
        { project_id: "proj-a", label: "鶴記" },
        { project_id: "proj-b", label: "鶴記" },
      ],
      projectId: "proj-a",
    });
    fireEvent.click(screen.getByRole("button", { name: /目前專案/ }));
    expect(screen.getByText("proj-a")).toBeTruthy();
    expect(screen.getByText("proj-b")).toBeTruthy();
  });
});

describe("MobileNavDrawer", () => {
  const collapsed: CollapsedGroups = { Workspace: false, Knowledge: true, Character: true, System: true };

  it("keeps the account name, API keys and logout on phones", () => {
    const onLogout = vi.fn();
    const onOpenApiKeys = vi.fn();
    const onClose = vi.fn();
    render(
      <MobileNavDrawer
        open
        active="Chat"
        projectId="p1"
        onClose={onClose}
        onSelectTab={vi.fn()}
        access="admin"
        canManageApiKeys
        onOpenApiKeys={onOpenApiKeys}
        username="王小明"
        onLogout={onLogout}
        collapsedGroups={collapsed}
        onToggleGroup={vi.fn()}
      />,
    );
    const drawer = within(screen.getByRole("dialog", { name: "主要導覽" }));

    expect(drawer.getByText("王小明")).toBeTruthy();
    fireEvent.click(drawer.getByRole("button", { name: "登出" }));
    expect(onLogout).toHaveBeenCalledOnce();
    fireEvent.click(drawer.getByRole("button", { name: "API 金鑰" }));
    expect(onOpenApiKeys).toHaveBeenCalledOnce();
  });

  it("names the groups in Chinese and toggles them by their saved key", () => {
    const onToggleGroup = vi.fn();
    render(
      <MobileNavDrawer
        open
        active="Chat"
        projectId="p1"
        onClose={vi.fn()}
        onSelectTab={vi.fn()}
        access="admin"
        canManageApiKeys
        onOpenApiKeys={vi.fn()}
        username="王小明"
        onLogout={vi.fn()}
        collapsedGroups={collapsed}
        onToggleGroup={onToggleGroup}
      />,
    );
    const drawer = within(screen.getByRole("dialog", { name: "主要導覽" }));

    for (const title of ["互動", "知識", "角色", "系統"]) {
      expect(drawer.getByRole("button", { name: title })).toBeTruthy();
    }
    fireEvent.click(drawer.getByRole("button", { name: "知識" }));
    expect(onToggleGroup).toHaveBeenCalledWith("Knowledge");
  });
});
