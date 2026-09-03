import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EmbedKeys from "./EmbedKeys";
import type { EmbedKey } from "../api/embedKeys";

const api = vi.hoisted(() => ({
  listEmbedKeys: vi.fn(),
  createEmbedKey: vi.fn(),
  updateEmbedKey: vi.fn(),
  setEmbedKeyDisabled: vi.fn(),
  deleteEmbedKey: vi.fn(),
  fetchProjects: vi.fn(),
}));

vi.mock("../api/embedKeys", async () => {
  const actual = await vi.importActual<typeof import("../api/embedKeys")>(
    "../api/embedKeys",
  );
  return {
    ...actual,
    listEmbedKeys: api.listEmbedKeys,
    createEmbedKey: api.createEmbedKey,
    updateEmbedKey: api.updateEmbedKey,
    setEmbedKeyDisabled: api.setEmbedKeyDisabled,
    deleteEmbedKey: api.deleteEmbedKey,
  };
});

vi.mock("../api/projects", () => ({
  fetchProjects: api.fetchProjects,
}));

function makeKey(overrides: Partial<EmbedKey> = {}): EmbedKey {
  return {
    key_id: "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    label: "夥伴官網",
    project_id: "default",
    allowed_origins: ["https://partner.example"],
    default_character_id: "aria",
    allowed_character_ids: [],
    default_persona_id: "",
    default_tts_provider: "indextts",
    default_tts_voice: "hayley",
    rate_limit_per_minute: 60,
    daily_request_quota: 1000,
    disabled: false,
    created_by: "admin-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_used_at: null,
    requests_today: 12,
    ...overrides,
  };
}

describe("EmbedKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listEmbedKeys.mockResolvedValue([makeKey()]);
    api.fetchProjects.mockResolvedValue({
      projects: [
        { project_id: "default", label: "預設專案", document_count: 0, persona_count: 0 },
      ],
      project_count: 1,
    });
    api.createEmbedKey.mockResolvedValue(makeKey());
    api.updateEmbedKey.mockResolvedValue(makeKey());
    api.setEmbedKeyDisabled.mockResolvedValue(makeKey({ disabled: true }));
    api.deleteEmbedKey.mockResolvedValue(undefined);
  });

  it("lists each key with its id, project, origins, limits and today's usage", async () => {
    render(<EmbedKeys />);

    expect(await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa")).toBeTruthy();
    expect(screen.getByText("夥伴官網")).toBeTruthy();
    expect(await screen.findByText("預設專案")).toBeTruthy();
    expect(screen.getByText("https://partner.example")).toBeTruthy();
    expect(screen.getByText("60/分、1000/日")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("啟用中")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /複製 ovk_aaaaaaaaaaaaaaaaaaaaaaaa/ }),
    ).toBeTruthy();
  });

  it("shows a disabled key as such", async () => {
    api.listEmbedKeys.mockResolvedValue([makeKey({ disabled: true })]);

    render(<EmbedKeys />);

    expect(await screen.findByText("已停用")).toBeTruthy();
    expect(screen.getByRole("button", { name: "啟用" })).toBeTruthy();
  });

  it("creates a key from the modal with the parsed origin list", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "建立金鑰" }));
    fireEvent.change(screen.getByLabelText("名稱"), {
      target: { value: "新網站" },
    });
    fireEvent.change(
      screen.getByLabelText(/允許的來源網域/),
      { target: { value: "https://a.example\nhttps://b.example" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "建立" }));

    await waitFor(() => expect(api.createEmbedKey).toHaveBeenCalledTimes(1));
    expect(api.createEmbedKey.mock.calls[0][0]).toMatchObject({
      label: "新網站",
      project_id: "default",
      allowed_origins: ["https://a.example", "https://b.example"],
    });
    await waitFor(() => expect(api.listEmbedKeys).toHaveBeenCalledTimes(2));
  });

  it("refuses to submit an empty origin list", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "建立金鑰" }));
    fireEvent.click(screen.getByRole("button", { name: "建立" }));

    expect(await screen.findByText("至少需要一個允許的來源網域。")).toBeTruthy();
    expect(api.createEmbedKey).not.toHaveBeenCalled();
  });

  it("edits an existing key through PATCH rather than creating a new one", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "編輯" }));
    fireEvent.change(screen.getByLabelText("名稱"), {
      target: { value: "改名後" },
    });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    await waitFor(() => expect(api.updateEmbedKey).toHaveBeenCalledTimes(1));
    expect(api.updateEmbedKey.mock.calls[0][0]).toBe(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    );
    expect(api.updateEmbedKey.mock.calls[0][1]).toMatchObject({
      label: "改名後",
      allowed_origins: ["https://partner.example"],
    });
    expect(api.createEmbedKey).not.toHaveBeenCalled();
  });

  it("disables a key from the row action", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(screen.getByRole("button", { name: "停用" }));

    await waitFor(() => expect(api.setEmbedKeyDisabled).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
      true,
    ));
  });

  it("re-enables a disabled key", async () => {
    api.listEmbedKeys.mockResolvedValue([makeKey({ disabled: true })]);

    render(<EmbedKeys />);
    await screen.findByText("已停用");

    fireEvent.click(screen.getByRole("button", { name: "啟用" }));

    await waitFor(() => expect(api.setEmbedKeyDisabled).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
      false,
    ));
  });

  it("deletes a key only after the confirmation is accepted", async () => {
    render(<EmbedKeys />);
    await screen.findByText("ovk_aaaaaaaaaaaaaaaaaaaaaaaa");

    fireEvent.click(
      screen.getByRole("button", { name: /刪除 ovk_aaaaaaaaaaaaaaaaaaaaaaaa/ }),
    );
    expect(api.deleteEmbedKey).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^刪除$/ }));

    await waitFor(() => expect(api.deleteEmbedKey).toHaveBeenCalledWith(
      "ovk_aaaaaaaaaaaaaaaaaaaaaaaa",
    ));
  });

  it("surfaces a failure from the API", async () => {
    api.listEmbedKeys.mockRejectedValueOnce(new Error("後端掛了"));

    render(<EmbedKeys />);

    expect(await screen.findByText("後端掛了")).toBeTruthy();
  });
});
