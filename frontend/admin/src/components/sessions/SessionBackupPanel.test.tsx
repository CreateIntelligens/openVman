import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SessionBackupPanel from "./SessionBackupPanel";

const api = vi.hoisted(() => ({
  fetchSessionBackups: vi.fn(),
  runSessionBackup: vi.fn(),
}));

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, ...api };
});

const manifest = {
  backup_id: "20260923-030000",
  created_at: "2026-09-23T03:00:00+08:00",
  trigger: "schedule" as const,
  dry_run: false,
  projects: [
    { project_id: "a", sessions: { zh: 3, en: 1, es: 0 }, messages: 20 },
    { project_id: "b", sessions: { zh: 1, en: 0, es: 2 }, messages: 9 },
  ],
  total_sessions: 7,
  total_messages: 29,
};

describe("SessionBackupPanel", () => {
  beforeEach(() => {
    api.fetchSessionBackups.mockResolvedValue({ backups: [manifest], running: false });
    api.runSessionBackup.mockReset();
  });

  it("lists recent backups with per-language totals", async () => {
    render(<SessionBackupPanel />);
    expect(await screen.findByText("7 筆 · 中文 4 · English 1 · Español 2")).toBeTruthy();
    expect(screen.getByText("排程")).toBeTruthy();
  });

  it("previews without writing and then backs up", async () => {
    api.runSessionBackup
      .mockResolvedValueOnce({ ...manifest, dry_run: true })
      .mockResolvedValueOnce(manifest);
    render(<SessionBackupPanel />);

    fireEvent.click(screen.getByText("預覽"));
    expect(await screen.findByText(/預覽：2 個專案、7 筆對話/)).toBeTruthy();
    expect(api.runSessionBackup).toHaveBeenLastCalledWith({ dryRun: true });

    fireEvent.click(screen.getByText("立即備份"));
    await waitFor(() => expect(api.runSessionBackup).toHaveBeenLastCalledWith({ dryRun: false }));
    expect(await screen.findByText(/已備份 7 筆對話/)).toBeTruthy();
  });
});
