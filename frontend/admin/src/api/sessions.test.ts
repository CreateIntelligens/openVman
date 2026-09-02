import { afterEach, describe, expect, it, vi } from "vitest";

import { setActiveProjectId } from "./common";
import { fetchSessionExport } from "./sessions";

afterEach(() => {
  vi.restoreAllMocks();
  setActiveProjectId("default");
});

describe("sessions api", () => {
  it("exports the current filtered and selected sessions", async () => {
    setActiveProjectId("project-a");
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ sessions: [], total_sessions: 0 }),
      headers: new Headers({ "content-type": "application/json" }),
    } as Response);

    await fetchSessionExport(
      "doctor",
      {
        dateFrom: "2026-08-01",
        dateTo: "2026-08-31",
        search: "hello world",
      },
      ["session-a", "session-b"],
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      "/api/sessions/export?project_id=project-a&persona_id=doctor&date_from=2026-08-01&date_to=2026-08-31&search=hello+world&session_ids=session-a%2Csession-b",
    );
    expect((init as RequestInit).credentials).toBe("include");
  });
});
