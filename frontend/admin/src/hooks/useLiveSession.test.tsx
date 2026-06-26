import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  let webcamOnFrame:
    | ((base64: string, mimeType: string, timestamp: number) => void)
    | undefined;

  const managerInstances: any[] = [];
  const webcamControls = {
    active: false,
    error: "",
    start: vi.fn(async () => {
      webcamControls.active = true;
      webcamOnFrame?.("ZmFrZQ==", "image/jpeg", 1234);
    }),
    stop: vi.fn(() => {
      webcamControls.active = false;
    }),
  };

  class MockLiveWebSocketManager {
    callbacks: Record<string, (...args: any[]) => void> = {};
    sentEvents: unknown[] = [];

    constructor() {
      managerInstances.push(this);
    }

    setCallbacks(callbacks: Record<string, (...args: any[]) => void>): void {
      this.callbacks = callbacks;
    }

    updateConfig(): void {}

    connect(): void {}

    disconnect(): void {}

    restart(): void {}

    dispose(): void {}

    sendEvent(payload: unknown): boolean {
      this.sentEvents.push(payload);
      return true;
    }
  }

  return {
    managerInstances,
    MockLiveWebSocketManager,
    useVad: vi.fn(),
    useWebcamCapture: vi.fn((options: {
      onFrame: (base64: string, mimeType: string, timestamp: number) => void;
    }) => {
      webcamOnFrame = options.onFrame;
      return webcamControls;
    }),
    webcamControls,
  };
});

vi.mock("../utils/live-websocket-manager", () => ({
  LiveWebSocketManager: mocks.MockLiveWebSocketManager,
}));
vi.mock("./useVad", () => ({ useVad: mocks.useVad }));
vi.mock("./useWebcamCapture", () => ({ useWebcamCapture: mocks.useWebcamCapture }));

import { useLiveSession } from "./useLiveSession";

function renderLiveSession() {
  return renderHook(() => useLiveSession({
    enabled: false,
    clientId: "client-1",
    projectId: "project-a",
  }));
}

describe("useLiveSession camera capture", () => {
  beforeEach(() => {
    mocks.managerInstances.length = 0;
    mocks.webcamControls.active = false;
    mocks.webcamControls.error = "";
    mocks.webcamControls.start.mockClear();
    mocks.webcamControls.stop.mockClear();
  });

  it("sends webcam frames as client_video_frame events when live is connected", async () => {
    const { result } = renderLiveSession();
    const manager = mocks.managerInstances[0];

    act(() => {
      manager.callbacks.onStateChange("connected");
      manager.callbacks.onSessionIdChange("session-1");
    });
    await act(async () => {
      await result.current.startCamera();
    });

    expect(mocks.webcamControls.start).toHaveBeenCalledTimes(1);
    expect(manager.sentEvents).toContainEqual({
      event: "client_video_frame",
      frame_base64: "ZmFrZQ==",
      mime_type: "image/jpeg",
      timestamp: 1234,
    });
  });

  it("starts camera and connects websocket when startCamera is called while disconnected", async () => {
    const { result } = renderLiveSession();
    const manager = mocks.managerInstances[0];
    const connectSpy = vi.spyOn(manager, "connect");

    await act(async () => {
      await result.current.startCamera();
    });

    expect(mocks.webcamControls.start).toHaveBeenCalledTimes(1);
    expect(connectSpy).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBe("");
  });

  it("stops camera on websocket disconnect", () => {
    renderLiveSession();
    const manager = mocks.managerInstances[0];

    act(() => {
      manager.callbacks.onDisconnected();
    });

    expect(mocks.webcamControls.stop).toHaveBeenCalledTimes(1);
  });

  it("shows backend camera frame status events", () => {
    const { result } = renderLiveSession();
    const manager = mocks.managerInstances[0];

    act(() => {
      manager.callbacks.onServerEvent({
        event: "server_camera_frame_status",
        session_id: "session-1",
        status: "processed",
        timestamp: 1235,
        frame_timestamp: 1234,
      });
    });

    expect(result.current.cameraStatus).toBe("VLM 已分析影像");
  });
});
