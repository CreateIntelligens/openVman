import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TabGroup from "./TabGroup";
import { workspaceTabs } from "./navigation";

describe("collapsible navigation group", () => {
  it("hides collapsed links and exposes a disclosure controlling the group", () => {
    const onToggle = vi.fn();
    const props = { label: "Workspace", tabs: workspaceTabs, active: "Chat" as const, projectId: "default", onSelect: vi.fn(), isExpanded: true, onToggle };
    const { rerender } = render(<TabGroup {...props} isCollapsed />);
    const toggle = screen.getByRole("button", { name: "Workspace" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)?.hidden).toBe(true);
    expect(screen.queryByRole("link", { name: /語音$/ })).toBeNull();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledOnce();
    rerender(<TabGroup {...props} isCollapsed={false} />);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("link", { name: /對話$/ }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("link", { name: /語音$/ }));
    expect(props.onSelect).toHaveBeenCalledWith("Tts");
    expect(screen.getByRole("link", { name: /語音$/ }).getAttribute("href")).toBe("/admin/tts");
  });

  it("keeps the group reachable in the narrow icon sidebar", () => {
    const onToggle = vi.fn();
    render(<TabGroup label="Workspace" tabs={workspaceTabs} active="Chat" projectId="default" onSelect={vi.fn()}
      isExpanded={false} isCollapsed onToggle={onToggle} />);
    const toggle = screen.getByRole("button", { name: "Workspace" });
    expect(toggle.textContent).toBe("W");
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("omits a group when all of its tabs are unavailable", () => {
    render(<TabGroup label="Workspace" tabs={[]} active="Chat" projectId="default" onSelect={vi.fn()}
      isExpanded isCollapsed={false} onToggle={vi.fn()} />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});


it("uses the active project and public prefix for links opened in a new tab", () => {
  window.history.replaceState(null, "", "/openvman/admin/chat");
  render(<TabGroup label="Workspace" tabs={workspaceTabs} active="Chat" projectId="demo" onSelect={vi.fn()}
    isExpanded isCollapsed={false} onToggle={vi.fn()} />);
  expect(screen.getByRole("link", { name: /語音$/ }).getAttribute("href")).toBe("/openvman/admin/tts?project=demo");
  window.history.replaceState(null, "", "/admin/chat");
});
