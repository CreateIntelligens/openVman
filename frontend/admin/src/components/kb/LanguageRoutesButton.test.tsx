import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LanguageRoutesButton from "./LanguageRoutesButton";

const api = vi.hoisted(() => ({
  fetchKnowledgeSettings: vi.fn(),
  saveKnowledgeSettings: vi.fn(),
}));

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, ...api };
});

describe("LanguageRoutesButton", () => {
  beforeEach(() => {
    api.fetchKnowledgeSettings.mockResolvedValue({ language_routes: ["zh"] });
    api.saveKnowledgeSettings.mockImplementation(async (settings) => settings);
  });

  it("turns on the Taiwanese route and keeps Chinese locked", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    fireEvent.click(await screen.findByText("分流：中文"));

    expect((screen.getByLabelText(/中文/) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/台語/));

    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenCalledWith({ language_routes: ["zh", "nan"] }),
    );
    expect(await screen.findByText("分流：中文、台語")).toBeTruthy();
  });
});
