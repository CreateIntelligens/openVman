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

  it("keeps at least one route but Chinese is not required", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    fireEvent.click(await screen.findByText("分流：中文"));

    // 只剩一條時不能取消。
    expect((screen.getByLabelText(/^中文/) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/^English/));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenCalledWith({ language_routes: ["zh", "en"] }),
    );

    // 有兩條之後中文可以取消，只留英文。
    await waitFor(() => expect((screen.getByLabelText(/^中文/) as HTMLInputElement).disabled).toBe(false));
    fireEvent.click(screen.getByLabelText(/^中文/));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["en"] }),
    );
    expect(await screen.findByText("分流：English")).toBeTruthy();
  });

  it("reorders routes so the first one is the primary language", async () => {
    api.fetchKnowledgeSettings.mockResolvedValue({ language_routes: ["zh", "en"] });
    render(<LanguageRoutesButton projectId="proj-hekee" />);
    fireEvent.click(await screen.findByText("分流：中文、English"));

    expect(screen.getByText("主要")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("English 往前移"));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["en", "zh"] }),
    );
    expect(await screen.findByText("分流：English、中文")).toBeTruthy();
  });
});
