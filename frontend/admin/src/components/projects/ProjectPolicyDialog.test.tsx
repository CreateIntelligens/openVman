import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectPolicyDialog from "./ProjectPolicyDialog";

const api = vi.hoisted(() => ({
  fetchProjectPolicy: vi.fn(),
  saveProjectPolicy: vi.fn(),
  fetchAccountAccessOptions: vi.fn(),
}));

vi.mock("../../api/projects", async () => {
  const actual = await vi.importActual<typeof import("../../api/projects")>("../../api/projects");
  return {
    ...actual,
    fetchProjectPolicy: api.fetchProjectPolicy,
    saveProjectPolicy: api.saveProjectPolicy,
  };
});

vi.mock("../../api/auth", async () => {
  const actual = await vi.importActual<typeof import("../../api/auth")>("../../api/auth");
  return { ...actual, fetchAccountAccessOptions: api.fetchAccountAccessOptions };
});

const UNRESTRICTED = {
  project_id: "proj-a",
  allowed_asr_engines: [],
  default_asr_engine: null,
  taiwanese_asr_engine: null,
  allowed_tts_voices: [],
  default_tts_voice: null,
  allowed_characters: [],
  default_character_id: null,
  allowed_backgrounds: [],
  default_background_id: null,
  allowed_mascots: [],
  default_mascot_id: null,
  updated_by: null,
  updated_at: null,
};

function renderDialog() {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <ProjectPolicyDialog
      projectId="proj-a"
      projectLabel="示例專案"
      onClose={onClose}
      onSaved={onSaved}
    />,
  );
  return { onSaved, onClose };
}

describe("ProjectPolicyDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchProjectPolicy.mockResolvedValue(UNRESTRICTED);
    api.saveProjectPolicy.mockImplementation(async (_id, policy) => ({ ...UNRESTRICTED, ...policy }));
    api.fetchAccountAccessOptions.mockResolvedValue({
      projects: [],
      avatar_characters: [
        { id: "0713", label: "角色 0713" },
        { id: "0714", label: "角色 0714" },
      ],
      avatar_backgrounds: [
        { id: "bg-office", label: "辦公室" },
      ],
      avatar_mascots: [
        { id: "qqman", label: "QQMan" },
      ],
      custom_voices: [
        { id: "hayley", label: "Hayley", provider: "indextts" },
        { id: "edge-yun", label: "雲哲", provider: "edge-tts" },
      ],
      asr_engines: [
        { id: "breeze", label: "Breeze" },
        { id: "openai", label: "Whisper" },
        { id: "gemini-live", label: "Gemini 串流" },
      ],
    });
  });

  it("shows empty lists as unrestricted", async () => {
    renderDialog();
    expect(await screen.findByText("允許的語音辨識引擎")).toBeTruthy();
    expect(screen.getAllByText("不限制")).toHaveLength(5);
  });

  it("saves allowlists and defaults, keeping defaults inside the list", async () => {
    const { onSaved } = renderDialog();
    fireEvent.click(await screen.findByLabelText("Breeze"));
    fireEvent.click(screen.getByLabelText("Gemini 串流"));
    fireEvent.change(screen.getByLabelText("預設引擎"), { target: { value: "gemini-live" } });
    fireEvent.change(screen.getByLabelText("台語分流引擎"), { target: { value: "breeze" } });
    fireEvent.click(screen.getByLabelText(/^雲哲/));
    fireEvent.change(screen.getByLabelText("預設聲音"), { target: { value: "edge-yun" } });

    // 角色設定
    fireEvent.click(screen.getByLabelText("角色 0713"));
    fireEvent.change(screen.getByLabelText("預設人物"), { target: { value: "0713" } });

    // 串流引擎不能當台語分流引擎。
    const taiwanese = screen.getByLabelText("台語分流引擎") as HTMLSelectElement;
    expect(Array.from(taiwanese.options).map((option) => option.value)).toEqual(["", "breeze"]);

    // 取消勾選預設引擎時，預設值一起清掉，免得送出後被後端擋。
    fireEvent.click(screen.getByLabelText("Gemini 串流"));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    await waitFor(() => expect(api.saveProjectPolicy).toHaveBeenCalledWith("proj-a", {
      allowed_asr_engines: ["breeze"],
      default_asr_engine: null,
      taiwanese_asr_engine: "breeze",
      allowed_tts_voices: ["edge-yun"],
      default_tts_voice: "edge-yun",
      allowed_characters: ["0713"],
      default_character_id: "0713",
      allowed_backgrounds: [],
      default_background_id: null,
      allowed_mascots: [],
      default_mascot_id: null,
    }));
    expect(onSaved).toHaveBeenCalledWith("專案「示例專案」的設定已更新");
  });

  it("lists stale ids so they can be removed", async () => {
    api.fetchProjectPolicy.mockResolvedValue({
      ...UNRESTRICTED,
      allowed_asr_engines: ["xiaomi"],
    });
    renderDialog();
    const stale = await screen.findByLabelText("xiaomi（已不存在）");
    expect((stale as HTMLInputElement).checked).toBe(true);
  });

  it("shows the server's validation error", async () => {
    api.saveProjectPolicy.mockRejectedValue(new Error("default_tts_voice must be one of allowed_tts_voices"));
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "儲存" }));
    expect((await screen.findByRole("alert")).textContent).toContain("default_tts_voice");
  });
});
