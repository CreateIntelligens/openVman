import { StrictMode, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionStorageKey } from "../components/chat/helpers";
import { createChatTestRequest } from "../context/NavigationContext";
import { writeScoped } from "../utils/scopedStorage";
import { useChatSession } from "./useChatSession";

function strictMode({ children }: { children: ReactNode }) {
  return <StrictMode>{children}</StrictMode>;
}

function mockChatApi() {
  const questions: object[] = [];
  const requests = vi.fn(async (input: string, init?: RequestInit) => {
    switch (new URL(input, window.location.origin).pathname) {
      case "/api/v1/personas":
        return Response.json({ personas: [{ persona_id: "default", label: "接待角色", is_default: true }] });
      case "/api/v1/sessions":
        return Response.json({ sessions: [] });
      case "/api/v1/chat/history":
        return Response.json({ session_id: "old-session", history: [] });
      case "/api/v1/knowledge/qa/entries":
        return Response.json({ entries: [] });
      case "/api/v1/chat": {
        const payload = JSON.parse(String(init?.body));
        questions.push(payload);
        return Response.json({ session_id: "test-session", reply: "回覆", history: [] });
      }
      default:
        throw new Error(`Unexpected request: ${input}`);
    }
  });
  vi.stubGlobal("fetch", requests);
  return { requests, questions };
}

describe("knowledge base chat test", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/admin/chat");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the saved question once in a new conversation, even when Chat mounts again", async () => {
    const { requests, questions } = mockChatApi();
    writeScoped(getSessionStorageKey("default"), "old-session");
    const chatTest = createChatTestRequest({ question: "  Where is my order?  ", language: "en" });
    const first = renderHook(() => useChatSession(true, chatTest), { wrapper: strictMode });

    await waitFor(() => expect(first.result.current.sessionId).toBe("test-session"));
    expect(requests.mock.calls.some(([url]) => url.startsWith("/api/v1/chat/history"))).toBe(false);
    expect(questions).toEqual([expect.objectContaining({
      message: "Where is my order?",
      preferred_language: "en",
      project_id: "default",
    })]);
    expect(questions[0]).not.toHaveProperty("session_id");

    first.unmount();
    const second = renderHook(() => useChatSession(true, chatTest), { wrapper: strictMode });
    await waitFor(() => expect(second.result.current.loadingPersonas).toBe(false));
    expect(questions).toHaveLength(1);
  });

  it("carries the language to manual requests without sending a question", async () => {
    const { questions } = mockChatApi();
    const chatTest = createChatTestRequest({ language: "ja" });
    const { result } = renderHook(() => useChatSession(true, chatTest), { wrapper: strictMode });
    await waitFor(() => expect(result.current.loadingPersonas).toBe(false));
    expect(questions).toEqual([]);
    await act(() => result.current.submit("OK"));
    expect(questions).toEqual([expect.objectContaining({
      message: "OK",
      preferred_language: "ja",
    })]);
  });
});
