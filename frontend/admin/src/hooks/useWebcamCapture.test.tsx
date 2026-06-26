import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWebcamCapture } from "./useWebcamCapture";

function installMediaMocks() {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  const drawImage = vi.fn();
  const toDataURL = vi.fn(() => "data:image/jpeg;base64,ZmFrZQ==");
  const originalCreateElement = document.createElement.bind(document);

  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });

  vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
    const element = originalCreateElement(tagName, options);

    if (tagName === "canvas") {
      Object.defineProperties(element, {
        height: { configurable: true, value: 0, writable: true },
        width: { configurable: true, value: 0, writable: true },
      });
      Object.defineProperty(element, "getContext", {
        configurable: true,
        value: vi.fn(() => ({ drawImage })),
      });
      Object.defineProperty(element, "toDataURL", {
        configurable: true,
        value: toDataURL,
      });
    }

    if (tagName === "video") {
      Object.defineProperty(element, "play", {
        configurable: true,
        value: vi.fn().mockResolvedValue(undefined),
      });
    }

    return element;
  });

  return { drawImage, getUserMedia, stop, toDataURL };
}

describe("useWebcamCapture", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("captures scaled jpeg frames on the configured interval", async () => {
    const mocks = installMediaMocks();
    const onFrame = vi.fn();
    const { result } = renderHook(() => useWebcamCapture({ onFrame }));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(result.current.active).toBe(true);
    expect(mocks.getUserMedia).toHaveBeenCalledWith({ video: true });
    expect(mocks.drawImage).toHaveBeenCalled();
    expect(mocks.toDataURL).toHaveBeenCalledWith("image/jpeg", 0.7);
    expect(onFrame).toHaveBeenCalledWith("ZmFrZQ==", "image/jpeg", expect.any(Number));
  });

  it("stops interval and media tracks", async () => {
    const mocks = installMediaMocks();
    const onFrame = vi.fn();
    const { result } = renderHook(() => useWebcamCapture({ onFrame }));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.stop();
      vi.advanceTimersByTime(1000);
    });

    expect(result.current.active).toBe(false);
    expect(mocks.stop).toHaveBeenCalledTimes(1);
    expect(onFrame).not.toHaveBeenCalled();
  });

  it("sets an error when camera permission is denied", async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    const { result } = renderHook(() => useWebcamCapture({ onFrame: vi.fn() }));

    await act(async () => {
      await expect(result.current.start()).rejects.toThrow("無法存取攝影機");
    });

    expect(result.current.active).toBe(false);
    expect(result.current.error).toBe("無法存取攝影機");
  });
});
