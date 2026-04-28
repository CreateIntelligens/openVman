import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const streamChatMock = vi.fn();
const prefetchTtsMock = vi.fn();
const playTtsMock = vi.fn();
const stopAudioMock = vi.fn();
const setTtsFallbackToastMock = vi.fn();
const clearTtsPrefetchStateMock = vi.fn();
const handleTtsProviderChangeMock = vi.fn();
const handleTtsVoiceChangeMock = vi.fn();
const loadSessionsMock = vi.fn();
const loadSessionHistoryMock = vi.fn();
const handlePersonaChangeMock = vi.fn();
const confirmDeleteSessionMock = vi.fn();
const persistSessionIdMock = vi.fn();
const setErrorMock = vi.fn();
const setDeleteSessionTargetMock = vi.fn();
const setSlashIndexMock = vi.fn();
const setSlashOpenMock = vi.fn();
const pickSlashMock = vi.fn();
const handleInputChangeMock = vi.fn();
const toggleAsrMock = vi.fn();
const restartAsrMock = vi.fn();

vi.mock("../api", () => ({
  streamChat: (...args: unknown[]) => streamChatMock(...args),
  starterPrompts: [],
}));

vi.mock("./useTts", () => ({
  useTts: () => ({
    ttsProviders: [],
    ttsProvider: "auto",
    ttsVoice: "",
    ttsFallbackToast: "",
    ttsPrefetching: false,
    playingIndex: null,
    activeTtsProvider: undefined,
    setTtsFallbackToast: setTtsFallbackToastMock,
    clearTtsPrefetchState: clearTtsPrefetchStateMock,
    stopAudio: stopAudioMock,
    prefetchTts: prefetchTtsMock,
    playTts: playTtsMock,
    handleTtsProviderChange: handleTtsProviderChangeMock,
    handleTtsVoiceChange: handleTtsVoiceChangeMock,
  }),
}));

vi.mock("./useChatHistory", async () => {
  const React = await vi.importActual<typeof import("react")>("react");

  return {
    useChatHistory: () => {
      const [messages, setMessages] = React.useState<any[]>([]);
      const [error, setErrorState] = React.useState("");
      const setError = React.useCallback((next: React.SetStateAction<string>) => {
        setErrorMock(next);
        setErrorState((current) => (typeof next === "function" ? next(current) : next));
      }, []);

      return {
        messages,
        setMessages,
        personas: [],
        selectedPersonaId: "default",
        sessionId: "",
        loadingPersonas: false,
        loadingHistory: false,
        sessions: [],
        loadingSessions: false,
        deleteSessionTarget: null,
        setDeleteSessionTarget: setDeleteSessionTargetMock,
        error,
        setError,
        persistSessionId: persistSessionIdMock,
        resetViewState: vi.fn(),
        loadSessions: loadSessionsMock,
        loadSessionHistory: loadSessionHistoryMock,
        handlePersonaChange: handlePersonaChangeMock,
        confirmDeleteSession: confirmDeleteSessionMock,
      };
    },
  };
});

vi.mock("./useSpeechRecognition", () => ({
  useSpeechRecognition: () => ({
    listening: false,
    supported: true,
    toggle: toggleAsrMock,
    restart: restartAsrMock,
  }),
}));

vi.mock("./useVad", () => ({
  useVad: () => ({
    speaking: false,
  }),
}));

vi.mock("./useSlashAutocomplete", () => ({
  useSlashAutocomplete: (_input: string, setInput: (value: string) => void) => ({
    slashOpen: false,
    slashMatches: [],
    clampedSlashIndex: 0,
    handleInputChange: (value: string) => {
      handleInputChangeMock(value);
      setInput(value);
    },
    pickSlash: pickSlashMock,
    setSlashIndex: setSlashIndexMock,
    setSlashOpen: setSlashOpenMock,
  }),
}));

import { useChatSession } from "./useChatSession";

describe("useChatSession TTS prefetch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("prefetches the finished assistant reply after streaming completes", async () => {
    streamChatMock.mockImplementation(
      async (
        _message: string,
        _personaId: string,
        _sessionId: string | undefined,
        handlers: {
          onDone?: (payload: {
            session_id: string;
            reply: string;
            knowledge_results: [];
            memory_results: [];
          }) => void;
        },
      ) => {
        await Promise.resolve();
        handlers.onDone?.({
          session_id: "sess-1",
          reply: "助手最終回覆",
          knowledge_results: [],
          memory_results: [],
        });
      },
    );

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("使用者問題");
    });

    await waitFor(() => expect(prefetchTtsMock).toHaveBeenCalledWith("助手最終回覆"));
    expect(playTtsMock).not.toHaveBeenCalled();
  });

  it("does not prefetch when the final reply is empty", async () => {
    streamChatMock.mockImplementation(
      async (
        _message: string,
        _personaId: string,
        _sessionId: string | undefined,
        handlers: {
          onDone?: (payload: {
            session_id: string;
            reply: string;
            knowledge_results: [];
            memory_results: [];
          }) => void;
        },
      ) => {
        await Promise.resolve();
        handlers.onDone?.({
          session_id: "sess-1",
          reply: "",
          knowledge_results: [],
          memory_results: [],
        });
      },
    );

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("使用者問題");
    });

    expect(prefetchTtsMock).not.toHaveBeenCalled();
    expect(playTtsMock).not.toHaveBeenCalled();
  });

  it("auto-clears the stopped reply notice after a short delay", async () => {
    vi.useFakeTimers();

    streamChatMock.mockImplementation(
      (
        _message: string,
        _personaId: string,
        _sessionId: string | undefined,
        _handlers: unknown,
        signal?: AbortSignal,
      ) => new Promise<void>((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
    );

    const { result } = renderHook(() => useChatSession());

    let submitPromise: Promise<void> | undefined;
    act(() => {
      submitPromise = result.current.submit("中止測試");
    });
    act(() => {
      result.current.stopStreaming();
    });
    await act(async () => {
      await submitPromise;
    });

    expect(result.current.error).toBe("已停止回覆");

    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(result.current.error).toBe("");
  });

  it("stores backend pii warnings on the latest user message and keeps them after done history", async () => {
    streamChatMock.mockImplementation(
      async (
        _message: string,
        _personaId: string,
        _sessionId: string | undefined,
        handlers: {
          onPiiWarning?: (payload: {
            categories: string[];
            counts: Record<string, number>;
          }) => void;
          onDone?: (payload: {
            session_id: string;
            reply: string;
            knowledge_results: [];
            memory_results: [];
            history: Array<{ role: string; content: string }>;
          }) => void;
        },
      ) => {
        await Promise.resolve();
        handlers.onPiiWarning?.({
          categories: ["private_phone"],
          counts: { private_phone: 1 },
        });
        handlers.onDone?.({
          session_id: "sess-1",
          reply: "助手最終回覆",
          knowledge_results: [],
          memory_results: [],
          history: [
            { role: "user", content: "使用者問題" },
            { role: "assistant", content: "助手最終回覆" },
          ],
        });
      },
    );

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("使用者問題");
    });

    await waitFor(() => expect(result.current.messages[0].privacy_warning?.counts.private_phone).toBe(1));
  });

  it("defaults privacy warnings to visible and persists toggle changes", () => {
    window.localStorage.removeItem("chat.privacy_warning_visible");

    const { result } = renderHook(() => useChatSession());

    expect(result.current.privacyWarningsVisible).toBe(true);

    act(() => {
      result.current.setPrivacyWarningsVisible(false);
    });

    expect(window.localStorage.getItem("chat.privacy_warning_visible")).toBe("false");
  });

});
