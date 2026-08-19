import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Accounts from "./Accounts";
import {
  createAccount,
  fetchAccountAccessOptions,
  listAccounts,
} from "../api/auth";

vi.mock("../api/auth", () => ({
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  fetchAccountAccessOptions: vi.fn(),
  listAccounts: vi.fn(),
  revokeAccountSessions: vi.fn(),
  setAccountDisabled: vi.fn(),
  updateAccountAccess: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    account: {
      id: "admin-a",
      username: "admin",
      role: "admin",
    },
  }),
}));

vi.mock("../components/accounts/FormalAccountAccessPanel", () => ({
  default: () => null,
}));

vi.mock("../components/accounts/TemporaryBatchPanel", () => ({
  default: () => <section>臨時帳號批次</section>,
}));

describe("Accounts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAccounts).mockResolvedValue([]);
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue({
      projects: [{ id: "project-a", label: "專案 A" }],
      avatar_characters: [{ id: "character-a", label: "人物 A" }],
      custom_voices: [
        { id: "voice-a", label: "聲音 A", provider: "indextts" },
      ],
    });
    vi.mocked(createAccount).mockResolvedValue({
      id: "user-a",
      username: "alice",
      role: "user",
      kind: "formal",
      disabled: false,
      created_at: "2026-08-18T00:00:00Z",
    });
  });

  it("selects access before creating a formal user", async () => {
    render(<Accounts />);

    fireEvent.change(screen.getByLabelText("帳號"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密碼"), {
      target: { value: "correct horse battery staple" },
    });
    const submit = await screen.findByRole("button", {
      name: "建立正式帳號",
    });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(createAccount).toHaveBeenCalledWith({
      username: "alice",
      password: "correct horse battery staple",
      role: "user",
      access: {
        grants: {
          projects: ["project-a"],
          avatar_characters: ["character-a"],
          custom_voices: ["voice-a"],
          avatar_mascots: [],
          avatar_backgrounds: [],
        },
        defaults: {
          project_id: "project-a",
          character_id: "character-a",
          voice_provider: "indextts",
          voice_id: "voice-a",
          mascot_id: "",
          background_id: "",
        },
      },
    }));
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledTimes(2);
      expect(fetchAccountAccessOptions).toHaveBeenCalledTimes(2);
    });
  });

  it("shows one account creation flow at a time", async () => {
    render(<Accounts />);

    expect(screen.getByText("新增正式帳號")).toBeTruthy();
    expect(screen.queryByText("臨時帳號批次")).toBeNull();
    await waitFor(() => {
      expect(listAccounts).toHaveBeenCalledOnce();
      expect(fetchAccountAccessOptions).toHaveBeenCalledOnce();
    });

    fireEvent.click(screen.getByRole("button", { name: /臨時帳號/ }));

    expect(screen.queryByText("新增正式帳號")).toBeNull();
    expect(screen.getByText("臨時帳號批次")).toBeTruthy();
  });
});
