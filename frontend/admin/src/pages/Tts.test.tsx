import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchTtsProviders, synthesizeSpeechPreview, type SpeechPreview } from "../api/tts";
import Tts from "./Tts";

vi.mock("../api/tts", () => ({ fetchTtsProviders: vi.fn(), synthesizeSpeechPreview: vi.fn() }));

const providers = [
  { id: "edge", name: "Edge TTS", default_voice: "voice-a", voices: ["voice-a", "voice-b"] },
  { id: "gemini", name: "Gemini", default_voice: "Kore", voices: ["Kore"] },
];
const result: SpeechPreview = { audio: new Blob(["audio"], { type: "audio/wav" }), provider: "edge", fallback: false };

beforeEach(() => {
  vi.mocked(fetchTtsProviders).mockReset().mockResolvedValue(providers);
  vi.mocked(synthesizeSpeechPreview).mockReset().mockResolvedValue(result);
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn().mockReturnValue("blob:preview"), revokeObjectURL: vi.fn(),
  }));
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function ready() {
  render(<Tts />);
  await waitFor(() => expect((screen.getByRole("button", { name: "試聽" }) as HTMLButtonElement).disabled).toBe(false));
}

describe("TTS preview", () => {
  it("synthesizes the selected voice without a chat request and releases audio on exit", async () => {
    const view = render(<Tts />);
    await screen.findByText("Edge TTS");
    fireEvent.click(screen.getByRole("combobox", { name: "聲音" }));
    fireEvent.mouseDown(screen.getByRole("option", { name: "voice-b" }));
    fireEvent.change(screen.getByLabelText("試聽文字"), { target: { value: " 測試聲音 " } });
    fireEvent.click(screen.getByRole("button", { name: "試聽" }));
    await screen.findByLabelText("試聽播放器");
    expect(synthesizeSpeechPreview).toHaveBeenCalledWith("測試聲音", "edge", "voice-b", expect.any(AbortSignal));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("resets the voice when switching providers and blocks blank input", async () => {
    await ready();
    fireEvent.click(screen.getByRole("combobox", { name: "供應商" }));
    fireEvent.mouseDown(screen.getByRole("option", { name: "Gemini" }));
    expect(screen.getByRole("combobox", { name: "聲音" }).textContent).toContain("Kore");
    fireEvent.change(screen.getByLabelText("試聽文字"), { target: { value: "   " } });
    expect((screen.getByRole("button", { name: "試聽" }) as HTMLButtonElement).disabled).toBe(true);
    expect(synthesizeSpeechPreview).not.toHaveBeenCalled();
  });

  it("cancels generation and ignores a late response", async () => {
    let resolve!: (value: SpeechPreview) => void;
    vi.mocked(synthesizeSpeechPreview).mockReturnValue(new Promise((done) => { resolve = done; }));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "試聽" }));
    const signal = vi.mocked(synthesizeSpeechPreview).mock.calls[0][3];
    fireEvent.click(screen.getByRole("button", { name: "停止試聽" }));
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(result));
    expect(screen.queryByLabelText("試聽播放器")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("shows generation failure and allows retry", async () => {
    vi.mocked(synthesizeSpeechPreview).mockRejectedValueOnce(new Error("語音暫時無法使用"));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "試聽" }));
    expect((await screen.findByRole("alert")).textContent).toContain("語音暫時無法使用");
    fireEvent.click(screen.getByRole("button", { name: "試聽" }));
    await screen.findByLabelText("試聽播放器");
  });

  it("shows fallback and manual playback guidance when autoplay is blocked", async () => {
    vi.mocked(synthesizeSpeechPreview).mockResolvedValue({ ...result, fallback: true });
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(new DOMException("blocked", "NotAllowedError"));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "試聽" }));
    await screen.findByText(/Edge TTS 備援產生.*請按下方播放鍵/);
  });

  it("offers a reload after provider lookup fails", async () => {
    vi.mocked(fetchTtsProviders).mockRejectedValueOnce(new Error("offline"));
    render(<Tts />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "重新載入聲音" }));
    await screen.findByText("Edge TTS");
  });

  it("explains missing voice grants and disables generation", async () => {
    vi.mocked(fetchTtsProviders).mockResolvedValue([]);
    render(<Tts />);
    await screen.findByText(/目前沒有可試聽的聲音/);
    expect((screen.getByRole("button", { name: "試聽" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
