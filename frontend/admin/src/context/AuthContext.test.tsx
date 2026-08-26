import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/auth", () => ({
  AdminPortalAccessError: class AdminPortalAccessError extends Error {},
  getCurrentAccount: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  temporaryLogin: vi.fn(),
}));

import {
  AdminPortalAccessError,
  getCurrentAccount,
  login,
  logout,
  temporaryLogin,
} from "../api/auth";
import { AuthProvider, useAuth } from "./AuthContext";

const PROFILE = {
  id: "user-1",
  username: "alice",
  role: "user" as const,
  disabled: false,
  created_at: "2026-08-17T00:00:00Z",
};

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span>{auth.loading ? "loading" : auth.account?.username ?? "guest"}</span>
      <button
        type="button"
        onClick={() => void auth.login("alice", "password-123").catch(() => undefined)}
      >
        login
      </button>
      <button type="button" onClick={() => void auth.logout()}>logout</button>
      <button
        type="button"
        onClick={() => void auth.loginTemporary("temporary-password").catch(() => undefined)}
      >
        temporary login
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/admin/chat");
    vi.clearAllMocks();
    vi.mocked(getCurrentAccount).mockResolvedValue(PROFILE);
    vi.mocked(login).mockResolvedValue(PROFILE);
    vi.mocked(logout).mockResolvedValue(undefined);
    vi.mocked(temporaryLogin).mockResolvedValue({
      ...PROFILE,
      kind: "temporary",
      admin_portal_access: true,
    });
  });

  it("restores the cookie session on mount", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);

    expect(screen.getByText("loading")).toBeTruthy();
    expect(await screen.findByText("alice")).toBeTruthy();
    expect(getCurrentAccount).toHaveBeenCalledOnce();
  });

  it("restores a ROOT session without changing its role", async () => {
    vi.mocked(getCurrentAccount).mockResolvedValue({
      ...PROFILE,
      id: "root-1",
      username: "ai360",
      role: "root",
    });

    render(<AuthProvider><Probe /></AuthProvider>);

    expect(await screen.findByText("ai360")).toBeTruthy();
  });

  it("clears the local account and routes to login on logout", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("alice");

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    await waitFor(() => expect(screen.getByText("guest")).toBeTruthy());
    expect(window.location.pathname).toBe("/admin/login");
  });

  it("does not authenticate when login fails", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(new Error("expired"));
    vi.mocked(login).mockRejectedValue(new Error("Invalid credentials"));
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("guest");

    fireEvent.click(screen.getByRole("button", { name: "login" }));

    await waitFor(() => expect(login).toHaveBeenCalledOnce());
    expect(screen.getByText("guest")).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/login");
  });

  it("keeps the normal frontend session when Admin portal bootstrap is denied", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(
      new AdminPortalAccessError("Admin portal access required"),
    );
    render(<AuthProvider><Probe /></AuthProvider>);

    expect(await screen.findByText("guest")).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/chat");
  });

  it("supports an authorized temporary Admin login", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(new Error("expired"));
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("guest");

    fireEvent.click(screen.getByRole("button", { name: "temporary login" }));

    await waitFor(() => expect(temporaryLogin).toHaveBeenCalledWith(
      "temporary-password",
    ));
    expect(await screen.findByText("alice")).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/chat");
  });
});
