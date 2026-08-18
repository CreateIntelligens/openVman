import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createAccount,
  createTemporaryBatch,
  fetchAccountAccessOptions,
  login,
  updateAccountAccess,
} from "./auth";
import {
  apiFetch,
  setUnauthorizedHandler,
} from "./common";

describe("cookie auth API", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("includes cookies and never persists the returned JWT", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        id: "user-1",
        username: "alice",
        role: "user",
        disabled: false,
        created_at: "2026-08-17T00:00:00Z",
        token: "secret-jwt",
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const account = await login("alice", "correct horse battery staple");

    expect(account.username).toBe("alice");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(JSON.stringify(window.localStorage)).not.toContain("secret-jwt");
    expect(window.localStorage.length).toBe(0);
  });

  it("centralizes expired-session handling", async () => {
    const onUnauthorized = vi.fn();
    const clear = setUnauthorizedHandler(onUnauthorized);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    await apiFetch("/api/projects");

    expect(onUnauthorized).toHaveBeenCalledOnce();
    clear();
  });

  it("creates a fixed temporary batch through the centralized adapter", async () => {
    const payload = {
      batch_id: "batch-1",
      created_at: "2026-08-17T00:00:00Z",
      credentials: Array.from({ length: 5 }, (_, index) => ({
        user_id: `temporary-${index}`,
        password: `TempCode0${index}Ab`,
        expires_at: null,
      })),
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createTemporaryBatch({
      grants: {
        projects: ["proj-b85afb8bb6"],
        avatar_characters: ["0713"],
        custom_voices: ["hayley"],
      },
      defaults: {
        project_id: "proj-b85afb8bb6",
        character_id: "0713",
        voice_provider: "indextts",
        voice_id: "hayley",
      },
    });

    expect(result.credentials).toHaveLength(5);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/temporary-accounts/batches",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      grants: {
        projects: ["proj-b85afb8bb6"],
        avatar_characters: ["0713"],
        custom_voices: ["hayley"],
      },
      defaults: {
        project_id: "proj-b85afb8bb6",
        character_id: "0713",
        voice_provider: "indextts",
        voice_id: "hayley",
      },
    });
  });

  it("creates a formal account with its selected access in one request", async () => {
    const access = {
      grants: {
        projects: ["project-a"],
        avatar_characters: ["character-a"],
        custom_voices: ["voice-a"],
      },
      defaults: {
        project_id: "project-a",
        character_id: "character-a",
        voice_provider: "indextts",
        voice_id: "voice-a",
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: "user-a",
      username: "alice",
      role: "user",
      kind: "formal",
      disabled: false,
      created_at: "2026-08-18T00:00:00Z",
      grants: access.grants,
      defaults: access.defaults,
    }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await createAccount({
      username: "alice",
      password: "correct horse battery staple",
      role: "user",
      access,
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/users",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(JSON.parse(String(request.body))).toEqual({
      username: "alice",
      password: "correct horse battery staple",
      role: "user",
      access,
    });
  });

  it("loads grantable resources and updates formal account access", async () => {
    const options = {
      projects: [{ id: "project-a", label: "專案 A" }],
      avatar_characters: [{ id: "character-a", label: "人物 A" }],
      custom_voices: [{ id: "voice-a", label: "Voice A", provider: "indextts" }],
    };
    const updated = {
      id: "user-a",
      username: "alice",
      role: "user",
      kind: "formal",
      disabled: false,
      created_at: "2026-08-17T00:00:00Z",
      grants: {
        projects: ["project-a"],
        avatar_characters: ["character-a"],
        custom_voices: ["voice-a"],
      },
      defaults: {
        project_id: "project-a",
        character_id: "character-a",
        voice_provider: "indextts",
        voice_id: "voice-a",
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(options), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(updated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAccountAccessOptions()).resolves.toEqual(options);
    await expect(updateAccountAccess("user-a", {
      grants: updated.grants,
      defaults: updated.defaults,
    })).resolves.toEqual(updated);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/users/access-options",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/users/user-a/access",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });
});
