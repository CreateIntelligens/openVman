import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QaSyncStatusResponse } from "../api/knowledge";
import {
  QA_SYNC_POLL_INTERVAL_MS,
  QA_SYNC_RETRY_INTERVAL_MS,
  useQaSyncStatus,
} from "./useQaSyncStatus";

const fetchQaSyncStatusMock = vi.fn<(projectId?: string) => Promise<QaSyncStatusResponse>>();

vi.mock("../api/knowledge", () => ({
  fetchQaSyncStatus: (projectId?: string) => fetchQaSyncStatusMock(projectId),
}));

async function settle() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useQaSyncStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchQaSyncStatusMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("retries a failed first read instead of waiting for the next edit", async () => {
    fetchQaSyncStatusMock
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ categories: { a: "synced" } });

    const { result } = renderHook(() => useQaSyncStatus("p1"));
    await settle();
    expect(result.current.statuses).toEqual({});

    await advance(QA_SYNC_RETRY_INTERVAL_MS);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(result.current.statuses).toEqual({ a: "synced" });
  });

  it("fetches once on mount and does not poll when no category is updating", async () => {
    fetchQaSyncStatusMock.mockResolvedValue({
      categories: { a: "synced", b: "failed" },
    });

    const { result } = renderHook(() => useQaSyncStatus("p1"));
    await settle();

    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledWith("p1");
    expect(result.current.statuses).toEqual({ a: "synced", b: "failed" });

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);
  });

  it("polls every 3 seconds while any category is updating and stops once synced", async () => {
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { a: "updating", b: "synced" } })
      .mockResolvedValueOnce({ categories: { a: "updating", b: "synced" } })
      .mockResolvedValueOnce({ categories: { a: "synced", b: "synced" } });

    const { result } = renderHook(() => useQaSyncStatus("p1"));
    await settle();

    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);
    expect(result.current.statuses).toEqual({ a: "updating", b: "synced" });

    await advance(QA_SYNC_POLL_INTERVAL_MS - 1);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);

    await advance(1);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(result.current.statuses).toEqual({ a: "updating", b: "synced" });

    await advance(QA_SYNC_POLL_INTERVAL_MS);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
    expect(result.current.statuses).toEqual({ a: "synced", b: "synced" });

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
  });

  it("stops polling when unmounted", async () => {
    fetchQaSyncStatusMock.mockResolvedValue({ categories: { a: "updating" } });

    const { unmount } = renderHook(() => useQaSyncStatus("p1"));
    await settle();
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);

    unmount();
    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);
  });

  it("stops polling for the old project and ignores stale responses on project switch", async () => {
    let resolveStale: (value: QaSyncStatusResponse) => void = () => {};
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { a: "updating" } })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStale = resolve; }))
      .mockResolvedValueOnce({ categories: { b: "synced" } });

    const { result, rerender } = renderHook(
      ({ projectId }) => useQaSyncStatus(projectId),
      { initialProps: { projectId: "p1" } },
    );
    await settle();
    expect(result.current.statuses).toEqual({ a: "updating" });

    // Start p1's 3s poll without resolving it yet.
    await advance(QA_SYNC_POLL_INTERVAL_MS);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(fetchQaSyncStatusMock).toHaveBeenLastCalledWith("p1");

    // Switch to p2 before p1's request settles.
    rerender({ projectId: "p2" });
    expect(result.current.statuses).toEqual({});
    await settle();
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
    expect(fetchQaSyncStatusMock).toHaveBeenLastCalledWith("p2");
    expect(result.current.statuses).toEqual({ b: "synced" });

    // Resolving p1's stale response must not overwrite p2 or restart polling.
    await act(async () => {
      resolveStale({ categories: { a: "updating" } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.statuses).toEqual({ b: "synced" });

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
  });

  it("clears status on poll failure and silently retries on the next 3-second cycle", async () => {
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { a: "updating" } })
      .mockRejectedValueOnce(new Error("502"))
      .mockResolvedValueOnce({ categories: { a: "synced" } });

    const { result } = renderHook(() => useQaSyncStatus("p1"));
    await settle();
    expect(result.current.statuses).toEqual({ a: "updating" });

    await advance(QA_SYNC_POLL_INTERVAL_MS);
    expect(result.current.statuses).toEqual({});

    await advance(QA_SYNC_POLL_INTERVAL_MS);
    expect(result.current.statuses).toEqual({ a: "synced" });

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
  });

  it("re-fetches immediately on refresh and ignores older in-flight responses", async () => {
    let resolveOlder: (value: QaSyncStatusResponse) => void = () => {};
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { a: "updating" } })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOlder = resolve; }))
      .mockResolvedValueOnce({ categories: { a: "failed" } });

    const { result } = renderHook(() => useQaSyncStatus("p1"));
    await settle();

    // Trigger the scheduled poll, keep it in flight.
    await advance(QA_SYNC_POLL_INTERVAL_MS);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);

    // Explicit refresh after a mutation takes precedence.
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.statuses).toEqual({ a: "failed" });

    // Older response resolves late and must be ignored.
    await act(async () => {
      resolveOlder({ categories: { a: "updating" } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.statuses).toEqual({ a: "failed" });

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
  });
});
