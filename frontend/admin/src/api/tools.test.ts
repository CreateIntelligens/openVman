import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setActiveProjectId } from "./common";
import {
  createSkill,
  deleteSkill,
  fetchSkillFiles,
  reloadAllSkills,
  toggleSkill,
  updateSkillFiles,
} from "./tools";

function jsonResponse(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response;
}

describe("skills api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "ok", files: {} }));
    vi.stubGlobal("fetch", fetchMock);
    setActiveProjectId("proj-active");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setActiveProjectId("default");
  });

  const url = (call = 0) => fetchMock.mock.calls[call][0] as string;
  const init = (call = 0) => fetchMock.mock.calls[call][1] as RequestInit;

  // 2026-11-18：共用技能的請求沒帶 project_id，後端一律回 422，編輯共用技能打不開。
  it("sends the active project with every shared-skill request", async () => {
    await fetchSkillFiles("joke", { scope: "shared" });
    await updateSkillFiles("joke", { "skill.yaml": "x" }, { scope: "shared" });
    await toggleSkill("joke", { scope: "shared" });
    await deleteSkill("joke", { scope: "shared" });

    const query = "scope=shared&project_id=proj-active";
    expect(url(0)).toBe(`/api/v1/skills/joke/files?${query}`);
    expect(url(1)).toBe(`/api/v1/skills/joke/files?${query}`);
    expect(init(1).method).toBe("PUT");
    expect(url(2)).toBe(`/api/v1/skills/joke/toggle?${query}`);
    expect(init(2).method).toBe("PATCH");
    expect(url(3)).toBe(`/api/v1/skills/joke?${query}`);
    expect(init(3).method).toBe("DELETE");
  });

  it("names the shared scope explicitly when the skill has none", async () => {
    // Brain 沒收到 scope 會先找專案技能，找不到才落到共用的；不能讓它猜。
    await fetchSkillFiles("joke");

    expect(url()).toBe("/api/v1/skills/joke/files?scope=shared&project_id=proj-active");
  });

  it("keeps the skill's own project for project-scope requests", async () => {
    await toggleSkill("joke", { scope: "project", project_id: "proj-owner" });

    expect(url()).toBe("/api/v1/skills/joke/toggle?scope=project&project_id=proj-owner");
  });

  it("creates project skills only, in the active project by default", async () => {
    await createSkill("new", "New");
    await createSkill("other", "Other", "", "proj-owner");

    expect(url(0)).toBe("/api/v1/skills");
    expect(JSON.parse(init(0).body as string)).toEqual({
      skill_id: "new", name: "New", description: "", scope: "project", project_id: "proj-active",
    });
    expect(JSON.parse(init(1).body as string)).toMatchObject({
      scope: "project", project_id: "proj-owner",
    });
  });

  it("reloads skills for the active project", async () => {
    await reloadAllSkills();

    expect(url()).toBe("/api/v1/skills/reload?project_id=proj-active");
    expect(init().method).toBe("POST");
  });
});
