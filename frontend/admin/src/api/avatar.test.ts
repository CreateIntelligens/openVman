import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchAvatarCharacters,
  uploadAvatarCharacter,
  deleteAvatarCharacter,
  renameAvatarCharacter,
  updateAvatarCharacterLabel,
  fetchAvatarBackgrounds,
  uploadAvatarBackground,
  deleteAvatarBackground,
  updateAvatarBackgroundLabel,
  fetchAvatarMascots,
  uploadAvatarMascot,
  uploadAvatarMascotThumbnail,
  deleteAvatarMascot,
  updateAvatarMascotLabel,
} from "./avatar";

afterEach(() => vi.restoreAllMocks());

function mockFetch(payload: unknown, ok = true, status = 200) {
  return vi.spyOn(global, "fetch").mockResolvedValue({
    ok,
    status,
    json: async () => payload,
    headers: new Headers({ "content-type": "application/json" }),
  } as Response);
}

describe("avatar api", () => {
  it("fetchAvatarCharacters GETs /api/avatar", async () => {
    const f = mockFetch({ characters: [{ char_id: "008" }] });
    const res = await fetchAvatarCharacters();
    expect(f).toHaveBeenCalledWith(
      "/api/avatar",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(res.characters[0].char_id).toBe("008");
  });

  it("uploadAvatarCharacter POSTs multipart", async () => {
    const f = mockFetch({ status: "ok", character: { char_id: "008" } });
    const video = new File([new Uint8Array([0x1a])], "01.webm");
    const data = new File([new Uint8Array([0x1f])], "combined_data.json.gz");
    await uploadAvatarCharacter({ charId: "008", label: "x", video, data });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("deleteAvatarCharacter DELETEs by id", async () => {
    const f = mockFetch({ status: "ok", char_id: "008" });
    await deleteAvatarCharacter("008");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/008");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("renameAvatarCharacter POSTs new id", async () => {
    const f = mockFetch({ status: "ok", character: { char_id: "009" } });
    await renameAvatarCharacter("008", "009");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/008/rename");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ new_char_id: "009" });
  });

  it("updateAvatarCharacterLabel PATCHes display name", async () => {
    const f = mockFetch({ status: "ok", character: { char_id: "008", label: "新的名字" } });
    await updateAvatarCharacterLabel("008", "新的名字");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/008");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ label: "新的名字" });
  });

  it("fetchAvatarBackgrounds GETs /api/backgrounds", async () => {
    const f = mockFetch({ backgrounds: [{ background_id: "clinic" }] });
    const res = await fetchAvatarBackgrounds();
    expect(f).toHaveBeenCalledWith(
      "/api/backgrounds",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(res.backgrounds[0].background_id).toBe("clinic");
  });

  it("uploadAvatarBackground POSTs multipart", async () => {
    const f = mockFetch({ status: "ok", background: { background_id: "clinic" } });
    const image = new File([new Uint8Array([0x89])], "clinic.png");
    await uploadAvatarBackground({ backgroundId: "clinic", label: "診間", image });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/backgrounds");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("deleteAvatarBackground DELETEs by id", async () => {
    const f = mockFetch({ status: "ok", background_id: "clinic" });
    await deleteAvatarBackground("clinic");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/backgrounds/clinic");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("updateAvatarBackgroundLabel PATCHes display name", async () => {
    const f = mockFetch({ status: "ok", background: { background_id: "clinic", label: "新的診間" } });
    await updateAvatarBackgroundLabel("clinic", "新的診間");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/backgrounds/clinic");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ label: "新的診間" });
  });

  it("fetchAvatarMascots GETs /api/avatar/mascots", async () => {
    const f = mockFetch({ mascots: [{ mascot_id: "qqman" }] });
    const res = await fetchAvatarMascots();
    expect(f).toHaveBeenCalledWith(
      "/api/avatar/mascots",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(res.mascots[0].mascot_id).toBe("qqman");
  });

  it("uploadAvatarMascot POSTs multipart", async () => {
    const f = mockFetch({ status: "ok", mascot: { mascot_id: "custom" } });
    const model = new File([new Uint8Array([0x67])], "custom.vrm");
    await uploadAvatarMascot({ mascotId: "custom", label: "自訂", model });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/mascots");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("deleteAvatarMascot DELETEs by id", async () => {
    const f = mockFetch({ status: "ok", mascot_id: "custom" });
    await deleteAvatarMascot("custom");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/mascots/custom");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("updateAvatarMascotLabel PATCHes display name", async () => {
    const f = mockFetch({ status: "ok", mascot: { mascot_id: "custom", label: "新名稱" } });
    await updateAvatarMascotLabel("custom", "新名稱");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/mascots/custom");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ label: "新名稱" });
  });

  it("uploadAvatarMascotThumbnail POSTs multipart thumbnail", async () => {
    const f = mockFetch({ status: "ok", mascot: { mascot_id: "custom" } });
    const thumbnail = new File([new Uint8Array([0x89])], "custom.png");
    await uploadAvatarMascotThumbnail("custom", thumbnail);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/avatar/mascots/custom/thumbnail");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });
});
