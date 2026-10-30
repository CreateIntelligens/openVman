import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectPolicyDialog from "./ProjectPolicyDialog";

const api = vi.hoisted(() => ({
  fetchProjectPolicy: vi.fn(),
  saveProjectPolicy: vi.fn(),
  fetchAccountAccessOptions: vi.fn(),
  getCurrentAccount: vi.fn(),
  fetchProjectResources: vi.fn(),
  assignProjectResource: vi.fn(),
  unassignProjectResource: vi.fn(),
}));

vi.mock("../../api/projects", async () => {
  const actual = await vi.importActual<typeof import("../../api/projects")>("../../api/projects");
  return {
    ...actual,
    fetchProjectPolicy: api.fetchProjectPolicy,
    saveProjectPolicy: api.saveProjectPolicy,
    fetchProjectResources: api.fetchProjectResources,
    assignProjectResource: api.assignProjectResource,
    unassignProjectResource: api.unassignProjectResource,
  };
});

vi.mock("../../api/auth", async () => {
  const actual = await vi.importActual<typeof import("../../api/auth")>("../../api/auth");
  return {
    ...actual,
    fetchAccountAccessOptions: api.fetchAccountAccessOptions,
    getCurrentAccount: api.getCurrentAccount,
  };
});

const UNRESTRICTED = {
  project_id: "proj-a",
  allowed_asr_engines: [],
  asr_engine_order: [],
  default_asr_engine: null,
  taiwanese_asr_engine: null,
  allowed_tts_voices: [],
  tts_engine_order: [],
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
    api.getCurrentAccount.mockResolvedValue({ id: "admin-1", username: "admin", role: "admin" });
    api.fetchProjectResources.mockResolvedValue({
      project_id: "proj-a",
      avatar_character: [],
      avatar_background: [],
      avatar_mascot: [],
      custom_voice: [],
      asr_engine: [],
    });
    api.assignProjectResource.mockResolvedValue({});
    api.unassignProjectResource.mockResolvedValue({});
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
      asr_engine_order: [],
      default_asr_engine: null,
      taiwanese_asr_engine: "breeze",
      allowed_tts_voices: ["edge-yun"],
      tts_engine_order: [],
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

  it("renders both engine orders from the loaded policy", async () => {
    api.fetchProjectPolicy.mockResolvedValue({
      ...UNRESTRICTED,
      tts_engine_order: ["cosyvoice", "voxcpm", "gemini-tts"],
      asr_engine_order: ["r2t2-dev", "sensevoice", "openai"],
    });
    renderDialog();

    const tts = await screen.findByRole("list", { name: "TTS 引擎順位清單" });
    const asr = screen.getByRole("list", { name: "批次 ASR 引擎順位清單" });
    expect(within(tts).getAllByRole("listitem").map((row) => row.firstChild?.textContent))
      .toEqual(["1. CosyVoice", "2. VoxCPM", "3. Gemini TTS"]);
    expect(within(asr).getAllByRole("listitem").map((row) => row.firstChild?.textContent))
      .toEqual(["1. R2T2 dev", "2. SenseVoice", "3. OpenAI"]);
    expect(screen.getByText("沒指定引擎與聲音時照這個順序試；空白用部署順序")).toBeTruthy();
    expect(screen.getByText("指定引擎之後的備援順序；空白用部署順序")).toBeTruthy();
  });

  it("adds, moves and removes engines in both orders and saves the edited order", async () => {
    api.fetchProjectPolicy.mockResolvedValue({
      ...UNRESTRICTED,
      tts_engine_order: ["indextts", "voxcpm"],
      asr_engine_order: ["breeze", "openai"],
    });
    renderDialog();
    await screen.findByRole("list", { name: "TTS 引擎順位清單" });

    for (const { label, first, second, added, addedId } of [
      { label: "TTS 引擎順位", first: "IndexTTS", second: "VoxCPM", added: "CosyVoice", addedId: "cosyvoice" },
      { label: "批次 ASR 引擎順位", first: "Breeze", second: "OpenAI", added: "R2T2", addedId: "r2t2" },
    ]) {
      const list = within(screen.getByRole("list", { name: `${label}清單` }));
      const select = screen.getByRole("combobox", { name: `新增${label}` });
      expect((list.getByRole("button", { name: `${first}上移` }) as HTMLButtonElement).disabled).toBe(true);
      expect((list.getByRole("button", { name: `${second}下移` }) as HTMLButtonElement).disabled).toBe(true);
      expect(within(select).queryByRole("option", { name: first })).toBeNull();
      fireEvent.change(select, { target: { value: addedId } });
      expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent))
        .toEqual([`1. ${first}`, `2. ${second}`, `3. ${added}`]);
      expect(within(select).queryByRole("option", { name: added })).toBeNull();

      fireEvent.click(list.getByRole("button", { name: `${first}下移` }));
      expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent))
        .toEqual([`1. ${second}`, `2. ${first}`, `3. ${added}`]);
      fireEvent.click(list.getByRole("button", { name: `${added}上移` }));
      expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent))
        .toEqual([`1. ${second}`, `2. ${added}`, `3. ${first}`]);
      fireEvent.click(list.getByRole("button", { name: `${second}移除` }));
      expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent))
        .toEqual([`1. ${added}`, `2. ${first}`]);
      expect(within(select).getByRole("option", { name: second })).toBeTruthy();
    }

    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() => expect(api.saveProjectPolicy).toHaveBeenCalledWith("proj-a", expect.objectContaining({
      tts_engine_order: ["cosyvoice", "indextts"],
      asr_engine_order: ["r2t2", "breeze"],
    })));
  });

  it("offers exactly the supported engine ids when unrestricted and saves empty orders", async () => {
    renderDialog();
    const tts = await screen.findByRole("combobox", { name: "新增TTS 引擎順位" }) as HTMLSelectElement;
    const asr = screen.getByRole("combobox", { name: "新增批次 ASR 引擎順位" }) as HTMLSelectElement;
    expect(Array.from(tts.options).map((option) => [option.value, option.textContent])).toEqual([
      ["", "選擇要新增的引擎…"],
      ["indextts", "IndexTTS"], ["indextts-nurse", "IndexTTS（nurse24h）"],
      ["voxcpm", "VoxCPM"], ["cosyvoice", "CosyVoice"],
      ["gemini-tts", "Gemini TTS"], ["gcp-tts", "GCP TTS"], ["aws-polly", "AWS Polly"], ["edge-tts", "Edge TTS"],
    ]);
    expect(Array.from(asr.options).map((option) => [option.value, option.textContent])).toEqual([
      ["", "選擇要新增的引擎…"],
      ["breeze", "Breeze"], ["r2t2", "R2T2"], ["r2t2-dev", "R2T2 dev"], ["sensevoice", "SenseVoice"], ["openai", "OpenAI"],
    ]);
    fireEvent.change(tts, { target: { value: "indextts" } });
    fireEvent.change(asr, { target: { value: "breeze" } });
    fireEvent.click(screen.getByRole("button", { name: "IndexTTS移除" }));
    fireEvent.click(screen.getByRole("button", { name: "Breeze移除" }));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() => expect(api.saveProjectPolicy).toHaveBeenCalledWith("proj-a", expect.objectContaining({
      tts_engine_order: [],
      asr_engine_order: [],
    })));
  });

  it("limits batch ASR additions and prunes the order when the allowlist shrinks", async () => {
    api.fetchProjectPolicy.mockResolvedValue({
      ...UNRESTRICTED,
      allowed_asr_engines: ["breeze", "openai", "gemini-live"],
      asr_engine_order: ["openai", "breeze"],
    });
    renderDialog();
    const select = await screen.findByRole("combobox", { name: "新增批次 ASR 引擎順位" }) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual([""]);
    expect(select.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Whisper"));
    const list = within(screen.getByRole("list", { name: "批次 ASR 引擎順位清單" }));
    expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent)).toEqual(["1. Breeze"]);

    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() => expect(api.saveProjectPolicy).toHaveBeenCalledWith("proj-a", expect.objectContaining({
      allowed_asr_engines: ["breeze", "gemini-live"],
      asr_engine_order: ["breeze"],
    })));
  });

  it("prunes when an unrestricted allowlist becomes restricted and keeps the order when restrictions clear", async () => {
    api.fetchProjectPolicy.mockResolvedValue({
      ...UNRESTRICTED,
      asr_engine_order: ["openai", "breeze"],
    });
    renderDialog();
    fireEvent.click(await screen.findByLabelText("Breeze"));
    const list = within(screen.getByRole("list", { name: "批次 ASR 引擎順位清單" }));
    expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent)).toEqual(["1. Breeze"]);
    fireEvent.click(screen.getByLabelText("Breeze"));
    expect(list.getAllByRole("listitem").map((row) => row.firstChild?.textContent)).toEqual(["1. Breeze"]);
    const select = screen.getByRole("combobox", { name: "新增批次 ASR 引擎順位" });
    expect(within(select).getByRole("option", { name: "OpenAI" })).toBeTruthy();
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

  it("blocks saving until the current policy has loaded, and recovers on retry", async () => {
    // 讀失敗時表單是空清單，而空清單代表「不限制」；一存就把專案限制解掉。
    api.fetchProjectPolicy.mockRejectedValueOnce(new Error("連不上伺服器"));
    renderDialog();

    expect((await screen.findByRole("alert")).textContent).toContain("連不上伺服器");
    expect((screen.getByRole("button", { name: "儲存" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "重新讀取" }));

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "儲存" }) as HTMLButtonElement).disabled).toBe(false);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(api.fetchProjectPolicy).toHaveBeenCalledTimes(2);
  });

  it("renders assignment section as read-only for non-ROOT admin", async () => {
    api.getCurrentAccount.mockResolvedValue({ id: "admin-1", username: "admin", role: "admin" });
    api.fetchProjectResources.mockResolvedValue({
      project_id: "proj-a",
      avatar_character: [
        { resource_id: "c-assigned-1", label: "特派角色 1", source: "assigned", in_project_scope: true },
      ],
      avatar_background: [],
      avatar_mascot: [],
      custom_voice: [],
      asr_engine: [],
    });

    renderDialog();
    expect(await screen.findByText("唯讀（僅 ROOT 可編輯）")).toBeTruthy();
    // 指派區與允許清單（清單列現在顯示 id）都會出現這個 id。
    expect(screen.getAllByText("c-assigned-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("特派角色 1").length).toBeGreaterThan(0);
    expect(screen.getByText("ROOT 指派")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "解除指派" })).toBeNull();
    expect(screen.queryByRole("button", { name: "指派至專案" })).toBeNull();
    expect(screen.queryByLabelText("指派類型")).toBeNull();
  });

  it("allows ROOT to assign and unassign resources with correct resource_type values", async () => {
    api.getCurrentAccount.mockResolvedValue({ id: "root-1", username: "root", role: "root" });
    api.fetchProjectResources.mockResolvedValue({
      project_id: "proj-a",
      avatar_character: [
        { resource_id: "0713", label: "角色 0713", source: "assigned", in_project_scope: true },
      ],
      avatar_background: [],
      avatar_mascot: [],
      custom_voice: [],
      asr_engine: [],
    });

    renderDialog();
    expect(await screen.findByText("ROOT 資源指派（將全域資源指派給此專案）")).toBeTruthy();
    expect(screen.queryByText("唯讀（僅 ROOT 可編輯）")).toBeNull();

    // 驗證類型選項符合後端定義
    const typeSelect = screen.getByLabelText("指派類型") as HTMLSelectElement;
    expect(Array.from(typeSelect.options).map((o) => o.value)).toEqual([
      "avatar_character",
      "avatar_background",
      "avatar_mascot",
      "custom_voice",
      "asr_engine",
    ]);

    // 解除指派
    fireEvent.click(screen.getByRole("button", { name: "解除指派" }));
    await waitFor(() => {
      expect(api.unassignProjectResource).toHaveBeenCalledWith("proj-a", "avatar_character", "0713");
    });

    // 指派聲音 (custom_voice)
    fireEvent.change(typeSelect, { target: { value: "custom_voice" } });
    const voiceResourceSelect = screen.getByLabelText("指派資源");
    fireEvent.change(voiceResourceSelect, { target: { value: "hayley" } });
    fireEvent.click(screen.getByRole("button", { name: "指派至專案" }));
    await waitFor(() => {
      expect(api.assignProjectResource).toHaveBeenCalledWith("proj-a", "custom_voice", "hayley");
    });

    // 指派 ASR 引擎 (asr_engine)
    fireEvent.change(typeSelect, { target: { value: "asr_engine" } });
    const asrResourceSelect = screen.getByLabelText("指派資源");
    fireEvent.change(asrResourceSelect, { target: { value: "breeze" } });
    fireEvent.click(screen.getByRole("button", { name: "指派至專案" }));
    await waitFor(() => {
      expect(api.assignProjectResource).toHaveBeenCalledWith("proj-a", "asr_engine", "breeze");
    });

    // 指派人物 (avatar_character)
    fireEvent.change(typeSelect, { target: { value: "avatar_character" } });
    const charResourceSelect = screen.getByLabelText("指派資源");
    fireEvent.change(charResourceSelect, { target: { value: "0714" } });
    fireEvent.click(screen.getByRole("button", { name: "指派至專案" }));
    await waitFor(() => {
      expect(api.assignProjectResource).toHaveBeenCalledWith("proj-a", "avatar_character", "0714");
    });

    // 指派背景 (avatar_background)
    fireEvent.change(typeSelect, { target: { value: "avatar_background" } });
    const bgResourceSelect = screen.getByLabelText("指派資源");
    fireEvent.change(bgResourceSelect, { target: { value: "bg-office" } });
    fireEvent.click(screen.getByRole("button", { name: "指派至專案" }));
    await waitFor(() => {
      expect(api.assignProjectResource).toHaveBeenCalledWith("proj-a", "avatar_background", "bg-office");
    });

    // 指派小助理 (avatar_mascot)
    fireEvent.change(typeSelect, { target: { value: "avatar_mascot" } });
    const mascotResourceSelect = screen.getByLabelText("指派資源");
    fireEvent.change(mascotResourceSelect, { target: { value: "qqman" } });
    fireEvent.click(screen.getByRole("button", { name: "指派至專案" }));
    await waitFor(() => {
      expect(api.assignProjectResource).toHaveBeenCalledWith("proj-a", "avatar_mascot", "qqman");
    });
  });

  it("includes /projects/{id}/resources in options so non-ROOT admins can set project's own resources as project defaults", async () => {
    api.getCurrentAccount.mockResolvedValue({ id: "admin-1", username: "admin", role: "admin" });
    api.fetchProjectResources.mockResolvedValue({
      project_id: "proj-a",
      avatar_character: [
        { resource_id: "proj-char-local", label: "專案自訂角色", source: "project", in_project_scope: true },
      ],
      avatar_background: [
        { resource_id: "proj-bg-local", label: "專案自訂背景", source: "project", in_project_scope: true },
      ],
      avatar_mascot: [
        { resource_id: "proj-mascot-local", label: "專案自訂小助理", source: "project", in_project_scope: true },
      ],
      custom_voice: [
        { resource_id: "proj-voice-assigned", label: "專案指派聲音", source: "assigned", in_project_scope: true },
      ],
      asr_engine: [],
    });

    renderDialog();
    expect(await screen.findByText("允許的虛擬人物")).toBeTruthy();

    // 檢查預設角色下拉選單包含專案自訂角色
    const charSelect = screen.getByLabelText("預設人物") as HTMLSelectElement;
    expect(Array.from(charSelect.options).map((o) => o.value)).toContain("proj-char-local");
    fireEvent.change(charSelect, { target: { value: "proj-char-local" } });

    // 即使勾選了其他角色形成允許清單，專案資源不會被 keepInside 清除
    fireEvent.click(screen.getByLabelText("角色 0713"));
    expect(charSelect.value).toBe("proj-char-local");

    // 檢查預設背景下拉選單包含專案背景
    const bgSelect = screen.getByLabelText("預設背景") as HTMLSelectElement;
    expect(Array.from(bgSelect.options).map((o) => o.value)).toContain("proj-bg-local");
    fireEvent.change(bgSelect, { target: { value: "proj-bg-local" } });

    // 檢查預設小助理下拉選單包含專案小助理
    const mascotSelect = screen.getByLabelText("預設小助理") as HTMLSelectElement;
    expect(Array.from(mascotSelect.options).map((o) => o.value)).toContain("proj-mascot-local");
    fireEvent.change(mascotSelect, { target: { value: "proj-mascot-local" } });

    // 檢查預設聲音包含指派聲音
    const voiceSelect = screen.getByLabelText("預設聲音") as HTMLSelectElement;
    expect(Array.from(voiceSelect.options).map((o) => o.value)).toContain("proj-voice-assigned");
    fireEvent.change(voiceSelect, { target: { value: "proj-voice-assigned" } });

    // 儲存並驗證送出的 defaults
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() => {
      expect(api.saveProjectPolicy).toHaveBeenCalledWith("proj-a", expect.objectContaining({
        default_character_id: "proj-char-local",
        default_background_id: "proj-bg-local",
        default_mascot_id: "proj-mascot-local",
        default_tts_voice: "proj-voice-assigned",
        allowed_characters: ["0713"],
      }));
    });
  });

  it("displays items with in_project_scope === false with danger style and scope note", async () => {
    api.getCurrentAccount.mockResolvedValue({ id: "root-1", username: "root", role: "root" });
    api.fetchAccountAccessOptions.mockResolvedValue({
      projects: [],
      avatar_characters: [
        { id: "0713", label: "角色 0713", in_project_scope: false },
        { id: "0714", label: "角色 0714", in_project_scope: true },
      ],
      avatar_backgrounds: [],
      avatar_mascots: [],
      custom_voices: [],
      asr_engines: [],
    });

    renderDialog();
    expect(await screen.findByText("允許的虛擬人物")).toBeTruthy();

    // 在勾選清單中應出現提示與 text-danger
    const checkbox = screen.getByLabelText(/角色 0713/);
    const outOfScopeLabel = checkbox.closest("label");
    expect(outOfScopeLabel?.className).toContain("text-danger");
    expect(screen.getAllByText("（不在專案範圍內，一般使用者無法使用）").length).toBeGreaterThan(0);

    // 在預設選單中選擇該項目時，顯示說明與 text-danger
    const charSelect = screen.getByLabelText("預設人物") as HTMLSelectElement;
    fireEvent.change(charSelect, { target: { value: "0713" } });
    expect(charSelect.className).toContain("text-danger");
    expect(screen.getByText("不在專案範圍內，一般使用者無法使用")).toBeTruthy();
  });
});
