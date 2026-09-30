import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NavigationProvider } from "../context/NavigationContext";
import { useAdminSubView } from "./useAdminSubView";
const views = ["characters", "backgrounds", "mascots"] as const;
describe("useAdminSubView", () => {
  it("uses the route over stale storage and follows route changes", () => {
    localStorage.setItem("admin.avatar.assets_tab", "mascots");
    const navigate = vi.fn();
    let routeView: string | undefined = "backgrounds";
    function Wrapper({ children }: { children: ReactNode }) {
      return <NavigationProvider currentTab="Avatar" currentSubView={routeView} onSelectTab={navigate}>{children}</NavigationProvider>;
    }
    const { result, rerender } = renderHook(() => useAdminSubView("Avatar", "characters", views), { wrapper: Wrapper });
    expect(result.current[0]).toBe("backgrounds");
    routeView = "mascots";
    rerender();
    expect(result.current[0]).toBe("mascots");
    routeView = undefined;
    rerender();
    expect(result.current[0]).toBe("characters");
    expect(navigate).not.toHaveBeenCalled();
    localStorage.removeItem("admin.avatar.assets_tab");
  });
  it("requests app navigation and waits for the route to change", () => {
    const navigate = vi.fn();
    const { result } = renderHook(() => useAdminSubView("Avatar", "characters", views), {
      wrapper: ({ children }) => <NavigationProvider currentTab="Avatar" onSelectTab={navigate}>{children}</NavigationProvider>,
    });
    act(() => result.current[1]("backgrounds"));
    expect(navigate).toHaveBeenCalledWith("Avatar", "backgrounds");
    expect(result.current[0]).toBe("characters");
    act(() => result.current[1]("characters"));
    expect(navigate).toHaveBeenCalledTimes(1);
  });
  it("uses the default panel for an invalid subview", () => {
    const { result } = renderHook(() => useAdminSubView("Avatar", "characters", views), {
      wrapper: ({ children }) => <NavigationProvider currentTab="Avatar" currentSubView="unexpected" onSelectTab={vi.fn()}>{children}</NavigationProvider>,
    });
    expect(result.current[0]).toBe("characters");
  });
});
