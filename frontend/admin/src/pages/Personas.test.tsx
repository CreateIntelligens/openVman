import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Personas from "./Personas";
import { setPersonaAvatar } from "../api";

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "default" }),
}));

vi.mock("../components/personas/PersonaCreateForm", () => ({
  default: () => <div data-testid="persona-create-form" />,
}));

vi.mock("../components/personas/PersonaEditor", () => ({
  default: () => <div data-testid="persona-editor" />,
}));

vi.mock("../components/personas/PersonaEmptyState", () => ({
  default: () => <div data-testid="persona-empty-state" />,
}));

vi.mock("../components/personas/PersonaList", () => ({
  default: () => <div data-testid="persona-list" />,
}));

vi.mock("../api", () => ({
  clonePersona: vi.fn(),
  createPersona: vi.fn(),
  deletePersona: vi.fn(),
  fetchKnowledgeDocument: vi.fn().mockResolvedValue({
    path: "SOUL.md",
    content: "persona",
  }),
  fetchPersonas: vi.fn().mockResolvedValue({
    personas: [
      {
        persona_id: "default",
        label: "Default",
        path: "SOUL.md",
        is_default: true,
        avatar_char_id: null,
      },
    ],
  }),
  fetchAvatarCharacters: vi.fn().mockResolvedValue({
    characters: [
      {
        char_id: "0616",
        label: "ESG-AIKKA半身",
        has_video: true,
        has_data: true,
        size_bytes: 1024,
        updated_at: "2026-07-07T00:00:00Z",
      },
    ],
  }),
  fetchAvatarMascots: vi.fn().mockResolvedValue({
    mascots: [
      {
        mascot_id: "qqman",
        label: "QQman",
        engine: "3d",
        builtin: false,
        size_bytes: 2048,
        updated_at: "2026-07-07T00:00:00Z",
      },
    ],
  }),
  saveKnowledgeDocument: vi.fn(),
  setPersonaAvatar: vi.fn().mockResolvedValue({ status: "ok" }),
}));

describe("Personas page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("uses the styled Select component for avatar binding", async () => {
    render(<Personas />);

    const trigger = await screen.findByRole("button", { name: /未綁定/ });
    expect(screen.queryByRole("combobox")).toBeNull();

    fireEvent.click(trigger);
    fireEvent.mouseDown(await screen.findByRole("option", { name: "ESG-AIKKA半身 (2D)" }));

    await waitFor(() => {
      expect(setPersonaAvatar).toHaveBeenCalledWith("default", "0616");
    });
  });
});
