import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tab } from "../components/app/navigation";
import { setStorageScope } from "../utils/scopedStorage";
import { useNavigationGroups } from "./useNavigationGroups";

beforeEach(() => {
  window.localStorage.clear();
  setStorageScope("account-a");
});

afterEach(() => {
  vi.restoreAllMocks();
  setStorageScope("");
  window.localStorage.clear();
});

describe("navigation group preferences", () => {
  it("initially expands only the active group and keeps manual collapse until navigation", () => {
    const { result, rerender } = renderHook(({ active }: { active: Tab }) => useNavigationGroups(active), {
      initialProps: { active: "Chat" },
    });
    expect(result.current.collapsedGroups).toEqual({ Workspace: false, Knowledge: true, System: true });
    act(() => result.current.toggleGroup("Workspace"));
    rerender({ active: "Chat" });
    expect(result.current.collapsedGroups.Workspace).toBe(true);
    rerender({ active: "Health" });
    expect(result.current.collapsedGroups).toEqual({ Workspace: true, Knowledge: true, System: false });
    rerender({ active: "Chat" });
    expect(result.current.collapsedGroups.Workspace).toBe(false);
  });

  it("restores independent group preferences without sharing them across accounts", () => {
    const first = renderHook(() => useNavigationGroups("Chat"));
    act(() => first.result.current.toggleGroup("Knowledge"));
    act(() => first.result.current.toggleGroup("Workspace"));
    first.unmount();
    const reload = renderHook(() => useNavigationGroups("Chat"));
    expect(reload.result.current.collapsedGroups).toEqual({ Workspace: false, Knowledge: false, System: true });
    reload.unmount();
    setStorageScope("account-b");
    const other = renderHook(() => useNavigationGroups("Chat"));
    expect(other.result.current.collapsedGroups.Knowledge).toBe(true);
  });

  it("keeps toggles usable when browser storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const { result } = renderHook(() => useNavigationGroups("Chat"));
    act(() => result.current.toggleGroup("Knowledge"));
    expect(result.current.collapsedGroups.Knowledge).toBe(false);
  });
});
