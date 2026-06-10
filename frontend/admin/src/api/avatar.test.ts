import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchAvatarCharacters,
  uploadAvatarCharacter,
  deleteAvatarCharacter,
  renameAvatarCharacter,
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
    expect(f).toHaveBeenCalledWith("/api/avatar", undefined);
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
});
