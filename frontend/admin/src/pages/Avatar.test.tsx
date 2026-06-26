import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Avatar from "./Avatar";
import * as api from "../api";

afterEach(() => vi.restoreAllMocks());

describe("Avatar page", () => {
  it("renders character list", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "008", label: "角色八", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    render(<Avatar />);
    expect(await screen.findByText("008")).toBeTruthy();
    expect(screen.getByText("角色八")).toBeTruthy();
  });

  it("shows empty state when no characters", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    render(<Avatar />);
    expect(await screen.findByText(/no characters yet/i)).toBeTruthy();
  });

  it("shows error when load fails", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockRejectedValue(new Error("boom"));
    render(<Avatar />);
    await waitFor(() => expect(screen.getByText(/boom/)).toBeTruthy());
  });

  it("keeps the page itself scrollable inside the app shell", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: Array.from({ length: 11 }, (_, index) => ({
        char_id: String(index).padStart(3, "0"),
        label: `角色 ${index}`,
        has_video: true,
        has_data: true,
        size_bytes: 1024,
        updated_at: "2026-06-08T00:00:00Z",
      })),
    });

    render(<Avatar />);

    const page = await screen.findByTestId("avatar-page");
    expect(page.className).toContain("h-full");
    expect(page.className).toContain("min-h-0");
    expect(page.className).toContain("overflow-y-auto");
  });

  it("can open the avatar app with the selected character", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "010", label: "角色十", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "Try 010" }));

    expect(window.localStorage.getItem("avatar.character_id")).toBe("010");
    expect(openSpy).toHaveBeenCalledWith("/", "_blank", "noopener,noreferrer");
  });

  it("renames the display label without changing character id", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "010", label: "角色十", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    vi.spyOn(api, "updateAvatarCharacterLabel").mockResolvedValue({
      status: "ok",
      character: { char_id: "010", label: "新的名字", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
    });
    vi.spyOn(window, "prompt").mockReturnValue("新的名字");

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: /rename/i }));

    expect(api.updateAvatarCharacterLabel).toHaveBeenCalledWith("010", "新的名字");
    await waitFor(() => expect(screen.getByText("新的名字")).toBeTruthy());
    expect(screen.getByText("010")).toBeTruthy();
  });

  it("loads backgrounds from a dedicated Avatar tab", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({
      backgrounds: [
        {
          background_id: "clinic",
          label: "診間背景",
          url: "/backgrounds/clinic/image.png",
          mime_type: "image/png",
          size_bytes: 2048,
          updated_at: "2026-06-08T00:00:00Z",
        },
      ],
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "Backgrounds" }));

    expect(await screen.findByText("診間背景")).toBeTruthy();
    expect(api.fetchAvatarBackgrounds).toHaveBeenCalledOnce();
  });

  it("uploads a background image from the background tab", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({ backgrounds: [] });
    vi.spyOn(api, "uploadAvatarBackground").mockResolvedValue({
      status: "ok",
      background: {
        background_id: "clinic",
        label: "診間背景",
        url: "/backgrounds/clinic/image.png",
        mime_type: "image/png",
        size_bytes: 2048,
        updated_at: "2026-06-08T00:00:00Z",
      },
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "Backgrounds" }));
    fireEvent.change(await screen.findByPlaceholderText("Background ID"), {
      target: { value: "clinic" },
    });
    fireEvent.change(screen.getByPlaceholderText("Display name"), {
      target: { value: "診間背景" },
    });
    fireEvent.change(screen.getByLabelText(/Image/), {
      target: { files: [new File(["image"], "clinic.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload background" }));

    await waitFor(() => {
      expect(api.uploadAvatarBackground).toHaveBeenCalledWith({
        backgroundId: "clinic",
        label: "診間背景",
        image: expect.any(File),
      });
    });
  });

  it("can open the avatar app with the selected background", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({
      backgrounds: [
        {
          background_id: "clinic",
          label: "診間背景",
          url: "/backgrounds/clinic/image.png",
          mime_type: "image/png",
          size_bytes: 2048,
          updated_at: "2026-06-08T00:00:00Z",
        },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "Backgrounds" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use clinic" }));

    expect(window.localStorage.getItem("avatar.background_id")).toBe("uploaded:clinic");
    expect(window.localStorage.getItem("avatar.background_url")).toBe("/backgrounds/clinic/image.png");
    expect(openSpy).toHaveBeenCalledWith("/", "_blank", "noopener,noreferrer");
  });
});
