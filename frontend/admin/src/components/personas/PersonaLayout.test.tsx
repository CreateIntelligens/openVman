import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PersonaEditor from "./PersonaEditor";
import PersonaList from "./PersonaList";

describe("Persona layout constraints", () => {
  it("constrains persona list and card width so long names truncate without pushing actions out of view", () => {
    const personas = [
      { persona_id: "default", label: "預設角色", is_default: true },
      {
        persona_id: "enterprise-agent-2026",
        label: "VeryLongUnbrokenPersonaLabelWithoutSpaces_EnterpriseSupportAgent2026",
        is_default: false,
      },
    ];
    const { container } = render(
      <PersonaList
        personas={personas}
        selectedPersonaId="enterprise-agent-2026"
        deletingPersonaId=""
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const grid = container.querySelector(".grid");
    expect(grid?.className).toContain("grid-cols-1");

    const longLabel = screen.getByText(personas[1].label);
    const card = longLabel.closest(".rounded-md");
    expect(card?.className).toContain("min-w-0");

    const deleteBtn = screen.getByRole("button", { name: "刪除角色 enterprise-agent-2026" });
    expect(deleteBtn.className).toContain("shrink-0");
  });

  it("keeps document tab buttons non-shrinking inside the horizontally scrollable bar", () => {
    const coreDocs = [
      { path: "SOUL.md", label: "個性與說話方式", icon: "psychology" },
      { path: "AGENTS.md", label: "工作規則", icon: "group_work" },
      { path: "TOOLS.md", label: "工具使用說明", icon: "build" },
      { path: "MEMORY.md", label: "長期記憶", icon: "memory" },
    ];
    render(
      <PersonaEditor
        title="預設角色"
        selectedPath="SOUL.md"
        draftContent=""
        coreDocs={coreDocs}
        editorMode="edit"
        loadingDocument={false}
        saving={false}
        hasUnsavedChanges={false}
        onEditorModeChange={vi.fn()}
        onOpenDocument={vi.fn()}
        onDraftContentChange={vi.fn()}
        onDiscard={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    for (const doc of coreDocs) {
      const btn = screen.getByRole("button", { name: new RegExp(doc.label) });
      expect(btn.className).toContain("shrink-0");
    }
  });
});
