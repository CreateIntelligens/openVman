import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLocalStorageState } from "./useLocalStorageState";

const tabValues = ["documents", "graph"] as const;
type Tab = (typeof tabValues)[number];

describe("useLocalStorageState", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("initializes from a valid stored value", () => {
    window.localStorage.setItem("test.active_tab", "graph");

    const { result } = renderHook(() =>
      useLocalStorageState<Tab>("test.active_tab", "documents", tabValues),
    );

    expect(result.current[0]).toBe("graph");
  });

  it("falls back to the default for invalid stored values", () => {
    window.localStorage.setItem("test.active_tab", "unknown");

    const { result } = renderHook(() =>
      useLocalStorageState<Tab>("test.active_tab", "documents", tabValues),
    );

    expect(result.current[0]).toBe("documents");
  });

  it("persists direct and functional updates", () => {
    const { result } = renderHook(() =>
      useLocalStorageState<Tab>("test.active_tab", "documents", tabValues),
    );

    act(() => {
      result.current[1]("graph");
    });

    expect(result.current[0]).toBe("graph");
    expect(window.localStorage.getItem("test.active_tab")).toBe("graph");

    act(() => {
      result.current[1]((current) => current === "graph" ? "documents" : "graph");
    });

    expect(result.current[0]).toBe("documents");
    expect(window.localStorage.getItem("test.active_tab")).toBe("documents");
  });

  it("keeps rendering if localStorage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const { result } = renderHook(() =>
      useLocalStorageState<Tab>("test.active_tab", "documents", tabValues),
    );

    expect(result.current[0]).toBe("documents");

    act(() => {
      result.current[1]("graph");
    });

    expect(result.current[0]).toBe("graph");
  });
});
