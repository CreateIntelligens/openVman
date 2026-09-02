import { describe, expect, it } from "vitest";

import type { SessionsExportResponse } from "../../api";
import { buildSessionExportFilename } from "./sessionExport";

const payload: SessionsExportResponse = {
  exported_at: "2026-09-01T00:00:00+00:00",
  project_id: "esg-7dea843a0d",
  persona_id: "default",
  sessions: [
    {
      session_id: "abcdefgh-1234",
      persona_id: "default",
      created_at: "2026-09-01T00:00:00+00:00",
      updated_at: "2026-09-01T00:00:00+00:00",
      message_count: 1,
      last_message_preview: "hello",
      messages: [{ role: "user", content: "hello" }],
    },
  ],
  total_messages: 1,
  total_sessions: 1,
};

describe("session export filenames", () => {
  const date = new Date(2026, 8, 1);

  it("builds a filename for all filtered sessions", () => {
    expect(buildSessionExportFilename(payload, "all", date)).toBe(
      "esg-7dea843a0d_history_export_20260901.json",
    );
  });

  it("builds a filename for one session", () => {
    expect(buildSessionExportFilename(payload, "single", date)).toBe(
      "esg-7dea843a0d_session_abcdefgh_20260901.json",
    );
  });

  it("builds a filename for selected sessions", () => {
    expect(buildSessionExportFilename(payload, "selected", date)).toBe(
      "esg-7dea843a0d_selected_sessions_1_20260901.json",
    );
  });
});
