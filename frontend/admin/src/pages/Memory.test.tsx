import { useEffect, useState, type ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Memory from "./Memory";
import { NavigationProvider } from "../context/NavigationContext";
import { buildAdminPath, parseAdminRoute } from "../components/app/navigation";

vi.mock("../context/ProjectContext", () => ({ useProject: () => ({ projectId: "default" }) }));
vi.mock("../api", () => ({
  fetchMemories: vi.fn().mockResolvedValue({ memories: [], total: 0 }),
  deleteMemory: vi.fn(), postAddMemory: vi.fn(), runMemoryMaintenance: vi.fn(),
}));

function RouteHarness({ children }: { children: ReactNode }) {
  const readView = () => parseAdminRoute(location.pathname, location.search)?.subView;
  const [view, setView] = useState(readView);
  useEffect(() => {
    const update = () => setView(readView());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return <NavigationProvider currentTab="Memory" currentSubView={view} onSelectTab={(tab, next) => {
    history.pushState(null, "", buildAdminPath(tab, "default", next));
    setView(next);
  }}>{children}</NavigationProvider>;
}

beforeEach(() => { localStorage.clear(); history.replaceState(null, "", "/admin/memory"); });
describe("Memory subpage routes", () => {
  it("opens add directly and preserves it across a remount", async () => {
    history.replaceState(null, "", "/admin/memory/add");
    localStorage.setItem("admin.memory.active_tab", "browse");
    const first = render(<RouteHarness><Memory /></RouteHarness>);
    await act(async () => {});
    expect(screen.getByLabelText("記憶內容")).toBeTruthy();
    first.unmount();
    render(<RouteHarness><Memory /></RouteHarness>);
    await act(async () => {});
    expect(screen.getByLabelText("記憶內容")).toBeTruthy();
  });
  it("synchronizes clicks and follows history route changes", async () => {
    localStorage.setItem("admin.memory.active_tab", "add");
    render(<RouteHarness><Memory /></RouteHarness>);
    await act(async () => {});
    expect(screen.queryByLabelText("記憶內容")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "新增" }));
    expect(location.pathname).toBe("/admin/memory/add");
    expect(screen.getByLabelText("記憶內容")).toBeTruthy();
    history.replaceState(null, "", "/admin/memory");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.queryByLabelText("記憶內容")).toBeNull();
    history.replaceState(null, "", "/admin/memory/add");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByLabelText("記憶內容")).toBeTruthy();
  });
});
