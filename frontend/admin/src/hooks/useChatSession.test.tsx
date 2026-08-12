import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchChatMock = vi.fn();
const fetchChatHistoryMock = vi.fn();
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
let latestSpeechRecognition: {
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  onstart?: () => void;
  onend?: () => void;
  onspeechstart?: () => void;
  onresult?: (event: {
    resultIndex: number;
    results: Array<{
      isFinal: boolean;
      0: { transcript: string };
    }>;
  }) => void;
} | null = null;

class MockSpeechRecognition {
  continuous = false;
  interimResults = true;
  lang = "";
  maxAlternatives = 0;
  onstart?: () => void;
  onend?: () => void;
  onspeechstart?: () => void;
  onresult?: (event: {
    resultIndex: number;
    results: Array<{
      isFinal: boolean;
      0: { transcript: string };
    }>;
  }) => void;
  start = vi.fn(() => {
    this.onstart?.();
  });
  stop = vi.fn(() => {
    this.onend?.();
  });
  abort = vi.fn();

  constructor() {
    latestSpeechRecognition = this;
  }
}

function installSpeechRecognitionMock() {
  (window as typeof window & {
    webkitSpeechRecognition?: unknown;
  }).webkitSpeechRecognition = MockSpeechRecognition;
}

vi.mock("../api", () => ({
  fetchChat: (...args: unknown[]) => fetchChatMock(...args),
  fetchChatHistory: (...args: unknown[]) => fetchChatHistoryMock(...args),
  fetchKnowledgeQaEntries: () => Promise.resolve({ entries: [] }),
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
    latestSpeechRecognition = null;
    delete (window as typeof window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("prefetches the finished assistant reply after streaming completes", async () => {
    fetchChatMock.mockResolvedValue({
      session_id: "sess-1",
      reply: "助手最終回覆",
      knowledge_results: [],
      memory_results: [],
      history: [],
    });

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("使用者問題");
    });

    await waitFor(() => expect(prefetchTtsMock).toHaveBeenCalledWith("助手最終回覆"));
    expect(playTtsMock).not.toHaveBeenCalled();
  });

  it("attaches RAG citations, image, and URL to the assistant message", async () => {
    fetchChatMock.mockResolvedValue({
      session_id: "sess-media",
      reply: "請掃描 QR code",
      image_id: "B1-4",
      url: "https://example.com/line",
      citations: [
        {
          uri: "knowledge/qa/line.csv",
          title: "官方 LINE",
          text: "請掃描 QR code",
          image_id: "B1-4",
          url: "https://example.com/line",
        },
      ],
      history: [
        { role: "user", content: "官方 LINE" },
        { role: "assistant", content: "請掃描 QR code" },
      ],
    });

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("官方 LINE");
    });

    const assistant = result.current.messages[result.current.messages.length - 1];
    expect(assistant?.image_id).toBe("B1-4");
    expect(assistant?.url).toBe("https://example.com/line");
    expect(assistant?.citations?.[0].image_id).toBe("B1-4");
  });

  it("does not prefetch when the final reply is empty", async () => {
    fetchChatMock.mockResolvedValue({
      session_id: "sess-1",
      reply: "",
      knowledge_results: [],
      memory_results: [],
      history: [],
    });

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      await result.current.submit("使用者問題");
    });

    expect(prefetchTtsMock).not.toHaveBeenCalled();
    expect(playTtsMock).not.toHaveBeenCalled();
  });

  it("auto-clears the stopped reply notice after a short delay", async () => {
    vi.useFakeTimers();

    fetchChatMock.mockImplementation(
      (
        _message: string,
        _personaId: string,
        _sessionId: string | undefined,
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
    vi.useFakeTimers();

    fetchChatMock.mockResolvedValue({
      session_id: "sess-1",
      reply: "助手最終回覆",
      knowledge_results: [],
      memory_results: [],
      pii_pending: true,
      history: [
        { role: "user", content: "使用者問題" },
        { role: "assistant", content: "助手最終回覆" },
      ],
    });

    fetchChatHistoryMock.mockResolvedValue({
      session_id: "sess-1",
      persona_id: "default",
      history: [
        { role: "user", content: "使用者問題", privacy_warning: { categories: ["private_phone"], counts: { private_phone: 1 } } },
        { role: "assistant", content: "助手最終回覆" },
      ],
    });

    const { result } = renderHook(() => useChatSession());

    let submitPromise: Promise<void> | undefined;
    act(() => {
      submitPromise = result.current.submit("使用者問題");
    });

    await act(async () => {
      await submitPromise;
    });

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(result.current.messages[0].privacy_warning?.counts.private_phone).toBe(1);
  });

  it("defaults privacy warnings to visible and persists toggle changes", async () => {
    window.localStorage.removeItem("chat.privacy_warning_visible");

    const { result } = renderHook(() => useChatSession());

    expect(result.current.privacyWarningsVisible).toBe(true);

    await act(async () => {
      result.current.setPrivacyWarningsVisible(false);
    });

    expect(window.localStorage.getItem("chat.privacy_warning_visible")).toBe("false");
  });

  it("turns off ASR after 10 seconds without voice activity", async () => {
    vi.useFakeTimers();
    installSpeechRecognitionMock();

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      result.current.toggleAsr();
    });

    expect(result.current.asrListening).toBe(true);

    act(() => {
      vi.advanceTimersByTime(9999);
    });
    expect(result.current.asrListening).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.asrListening).toBe(false);
  });

  it("submits final Web Speech API transcripts", async () => {
    installSpeechRecognitionMock();
    fetchChatMock.mockResolvedValue({
      session_id: "sess-voice",
      reply: "收到",
      knowledge_results: [],
      memory_results: [],
      history: [],
    });

    const { result } = renderHook(() => useChatSession());

    act(() => {
      result.current.toggleAsr();
    });

    expect(latestSpeechRecognition?.start).toHaveBeenCalledTimes(1);

    await act(async () => {
      latestSpeechRecognition?.onresult?.({
        resultIndex: 0,
        results: [{ isFinal: true, 0: { transcript: "語音測試" } }],
      });
    });

    await waitFor(() => {
      expect(fetchChatMock).toHaveBeenCalledWith(
        "語音測試",
        "default",
        undefined,
        expect.any(AbortSignal),
      );
    });
  });

  it("resets the ASR idle timeout when Web Speech detects activity", async () => {
    vi.useFakeTimers();
    installSpeechRecognitionMock();

    const { result } = renderHook(() => useChatSession());

    await act(async () => {
      result.current.toggleAsr();
    });
    expect(result.current.asrListening).toBe(true);

    act(() => {
      vi.advanceTimersByTime(9000);
      latestSpeechRecognition?.onspeechstart?.();
    });

    act(() => {
      vi.advanceTimersByTime(9999);
    });
    expect(result.current.asrListening).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.asrListening).toBe(false);
  });

});
