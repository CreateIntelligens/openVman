import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Sessions from "./Sessions";

const browserState = vi.hoisted(() => ({
  exportSessionHistory: vi.fn(),
  toggleSessionSelection: vi.fn(),
  toggleAllSessions: vi.fn(),
  setDeleteTarget: vi.fn(),
  resetFilters: vi.fn(),
  selectedSessionIds: new Set<string>(),
  sessions: [
    {
      session_id: "aaaaaaaa-1111-2222-3333-444444444444",
      persona_id: "default",
      created_at: "2026-08-30T02:00:00+00:00",
      updated_at: "2026-09-01T02:00:00+00:00",
      message_count: 12,
      last_message_preview: "第一則對話預覽",
    },
    {
      session_id: "bbbbbbbb-1111-2222-3333-444444444444",
      persona_id: "support",
      created_at: "2026-08-28T02:00:00+00:00",
      updated_at: "2026-08-29T02:00:00+00:00",
      message_count: 4,
      last_message_preview: "第二則對話預覽",
    },
  ],
  hasActiveFilters: false,
}));

vi.mock("../hooks/useSessionBrowser", async () => {
  const actual = await vi.importActual<
    typeof import("../hooks/useSessionBrowser")
  >("../hooks/useSessionBrowser");
  return {
    ...actual,
    useSessionBrowser: () => ({
      personas: [{ persona_id: "default", label: "預設" }],
      selectedPersonaId: actual.ALL_PERSONAS,
      setSelectedPersonaId: vi.fn(),
      loadingPersonas: false,
      sessions: browserState.sessions,
      loadingSessions: false,
      exportingSessions: false,
      selectedSessionIds: browserState.selectedSessionIds,
      deleteTarget: null,
      setDeleteTarget: browserState.setDeleteTarget,
      error: "",
      searchQuery: "",
      setSearchQuery: vi.fn(),
      dateFrom: "",
      setDateFrom: vi.fn(),
      dateTo: "",
      setDateTo: vi.fn(),
      sortKey: "updated_at" as const,
      setSortKey: vi.fn(),
      hasActiveFilters: browserState.hasActiveFilters,
      loadSessions: vi.fn(),
      resetFilters: browserState.resetFilters,
      toggleSessionSelection: browserState.toggleSessionSelection,
      toggleAllSessions: browserState.toggleAllSessions,
      exportSessionHistory: browserState.exportSessionHistory,
      confirmDelete: vi.fn(),
    }),
  };
});

describe("Sessions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    browserState.selectedSessionIds = new Set();
    browserState.hasActiveFilters = false;
  });

  it("lists every session with its persona and message count", () => {
    render(<Sessions />);

    expect(screen.getByText("第一則對話預覽")).toBeTruthy();
    expect(screen.getByText("第二則對話預覽")).toBeTruthy();
    expect(screen.getByText("共 2 筆對話 · 16 則訊息")).toBeTruthy();
    expect(screen.getByText("support")).toBeTruthy();
  });

  it("exports the filtered set when nothing is selected", () => {
    render(<Sessions />);

    fireEvent.click(screen.getByRole("button", { name: /匯出篩選結果/ }));

    expect(browserState.exportSessionHistory).toHaveBeenCalledWith(undefined);
  });

  it("exports only the chosen sessions once some are selected", () => {
    browserState.selectedSessionIds = new Set([
      "aaaaaaaa-1111-2222-3333-444444444444",
    ]);
    render(<Sessions />);

    fireEvent.click(screen.getByRole("button", { name: /匯出已選 \(1\)/ }));

    expect(browserState.exportSessionHistory).toHaveBeenCalledWith([
      "aaaaaaaa-1111-2222-3333-444444444444",
    ]);
  });

  it("exports a single session from its row action", () => {
    render(<Sessions />);

    const rows = screen.getAllByRole("listitem");
    fireEvent.click(
      within(rows[0]).getByRole("button", { name: "匯出這筆對話" }),
    );

    expect(browserState.exportSessionHistory).toHaveBeenCalledWith([
      "aaaaaaaa-1111-2222-3333-444444444444",
    ]);
  });

  it("asks for confirmation before deleting", () => {
    render(<Sessions />);

    const rows = screen.getAllByRole("listitem");
    fireEvent.click(within(rows[1]).getByRole("button", { name: "刪除對話" }));

    expect(browserState.setDeleteTarget).toHaveBeenCalledWith(
      browserState.sessions[1],
    );
  });

  it("offers a filter reset only while filters are active", () => {
    const { unmount } = render(<Sessions />);
    expect(screen.queryByRole("button", { name: /清除篩選/ })).toBeNull();
    unmount();

    browserState.hasActiveFilters = true;
    render(<Sessions />);
    expect(screen.getByRole("button", { name: /清除篩選/ })).toBeTruthy();
  });
});
