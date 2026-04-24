import type { ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChatInput from "./ChatInput";

function renderChatInput(overrides: Partial<ComponentProps<typeof ChatInput>> = {}) {
  const props: ComponentProps<typeof ChatInput> = {
    mode: "text",
    input: "hello",
    sending: false,
    error: "",
    slashOpen: false,
    slashMatches: [],
    clampedSlashIndex: 0,
    ttsProviders: [],
    ttsProvider: "auto",
    ttsVoice: "",
    activeTtsProvider: undefined,
    ttsFallbackToast: "",
    asrListening: false,
    asrSupported: true,
    vadSpeaking: false,
    privacyWarningsVisible: true,
    onInputChange: vi.fn(),
    onSubmit: vi.fn(),
    onStopStreaming: vi.fn(),
    onPickSlash: vi.fn(),
    onSlashIndex: vi.fn(),
    onSlashClose: vi.fn(),
    onTtsProviderChange: vi.fn(),
    onTtsVoiceChange: vi.fn(),
    onDismissError: vi.fn(),
    onDismissFallbackToast: vi.fn(),
    onToggleAsr: vi.fn(),
    onPrivacyWarningsVisibleChange: vi.fn(),
    liveWsState: "connected",
    liveMicActive: false,
    onLiveToggleMic: vi.fn(),
    ...overrides,
  };

  render(<ChatInput {...props} />);
  return props;
}

describe("ChatInput", () => {
  it("uses the primary send button to submit when not sending", () => {
    const props = renderChatInput();

    fireEvent.click(screen.getByRole("button", { name: "送出訊息" }));

    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onStopStreaming).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "停止回覆" })).toBeNull();
  });

  it("morphs the send button into the stop action while sending", () => {
    const props = renderChatInput({ sending: true });

    fireEvent.click(screen.getByRole("button", { name: "停止回覆" }));

    expect(props.onStopStreaming).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTitle("停止回覆")).not.toBeNull();
  });

  it("does not show the legacy regex privacy warning anymore", () => {
    renderChatInput({ input: "call me at 0912345678" });

    expect(screen.queryByText("This message may contain personal information.")).toBeNull();
  });

  it("renders the privacy warning toggle and forwards changes", () => {
    const props = renderChatInput({ privacyWarningsVisible: true });

    fireEvent.click(screen.getByRole("checkbox", { name: "顯示隱私警告" }));

    expect(props.onPrivacyWarningsVisibleChange).toHaveBeenCalledWith(false);
  });

});
