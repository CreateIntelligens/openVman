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
});
