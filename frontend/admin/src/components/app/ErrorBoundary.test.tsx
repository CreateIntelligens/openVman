import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reload = vi.fn();
const CHUNK_ERROR = new TypeError(
  "Failed to fetch dynamically imported module: https://x/admin/assets/Chat-1.js",
);

function Thrower({ error }: { error: Error | null }) {
  if (error) throw error;
  return <div>頁面內容</div>;
}

async function renderBoundary(error: Error | null) {
  vi.resetModules();
  const { default: ErrorBoundary } = await import("./ErrorBoundary");
  const guard = await import("@shared/staleChunkReload");
  const view = render(
    <ErrorBoundary variant="page" resetKey="a">
      <Thrower error={error} />
    </ErrorBoundary>,
  );
  return { ErrorBoundary, guard, ...view };
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    reload.mockClear();
    vi.stubGlobal("location", { reload });
    // React 會把被接住的錯誤印到 console，測試輸出不需要這些。
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders children when nothing throws", async () => {
    await renderBoundary(null);
    expect(screen.getByText("頁面內容")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the fallback without reloading or leaking the message on a render error", async () => {
    await renderBoundary(new Error("token=secret-value"));

    expect(screen.getByRole("alert").textContent).toContain("畫面無法顯示");
    expect(document.body.textContent).not.toContain("secret-value");
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads once on a chunk error and says so instead of showing the failure", async () => {
    await renderBoundary(CHUNK_ERROR);

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toContain("正在重新載入");
  });

  it("shows the fallback once the guard has tripped", async () => {
    await renderBoundary(CHUNK_ERROR);
    cleanup();
    reload.mockClear();

    await renderBoundary(CHUNK_ERROR);

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("畫面無法顯示");
  });

  it("shows the fallback when the guard cannot use storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    await renderBoundary(CHUNK_ERROR);

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("畫面無法顯示");
  });

  it("reports a reload already started by vite:preloadError", async () => {
    vi.resetModules();
    const guard = await import("@shared/staleChunkReload");
    guard.reloadOnceForStaleChunk();
    reload.mockClear();
    const { default: ErrorBoundary } = await import("./ErrorBoundary");

    render(
      <ErrorBoundary variant="page">
        <Thrower error={CHUNK_ERROR} />
      </ErrorBoundary>,
    );

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("正在重新載入");
  });

  it("reloads from the button whatever the guard says", async () => {
    window.sessionStorage.setItem(
      "openvman-stale-chunk-reload-at",
      String(Date.now()),
    );
    await renderBoundary(CHUNK_ERROR);
    expect(reload).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("clears the error when resetKey changes", async () => {
    const { ErrorBoundary, rerender } = await renderBoundary(new Error("boom"));
    expect(screen.getByRole("alert")).toBeTruthy();

    rerender(
      <ErrorBoundary variant="page" resetKey="b">
        <Thrower error={null} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("頁面內容")).toBeTruthy();
  });

  it("has the preload listener installed before the admin renders", () => {
    const main = readFileSync(resolve(__dirname, "../../main.tsx"), "utf8");
    expect(main.indexOf("installStaleChunkRecovery();")).toBeGreaterThan(-1);
    expect(main.indexOf("installStaleChunkRecovery();")).toBeLessThan(
      main.indexOf("createRoot("),
    );
  });
});
