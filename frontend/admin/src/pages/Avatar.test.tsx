import { useEffect, useState, type ReactElement } from "react";
import { NavigationProvider } from "../context/NavigationContext";
import { buildAdminPath, parseAdminRoute } from "../components/app/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render as renderComponent, screen, waitFor } from "@testing-library/react";
import Avatar from "./Avatar";
import { MascotProvider } from "../context/MascotContext";
import * as api from "../api";

const authState = vi.hoisted(() => ({ role: "admin" as "root" | "admin" | "user" }));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { id: "a", username: "a", role: authState.role } }),
}));

function render(element: ReactElement) {
  function RouteHarness() {
    const [view, setView] = useState(() => parseAdminRoute(window.location.pathname, window.location.search)?.subView);
    useEffect(() => {
      const update = () => setView(parseAdminRoute(window.location.pathname, window.location.search)?.subView);
      window.addEventListener("popstate", update);
      return () => window.removeEventListener("popstate", update);
    }, []);
    return <NavigationProvider currentTab="Avatar" currentSubView={view} onSelectTab={(tab, next) => {
      window.history.pushState(null, "", buildAdminPath(tab, "default", next));
      setView(next);
    }}>{element}</NavigationProvider>;
  }
  return renderComponent(<RouteHarness />);
}

beforeEach(() => {
  authState.role = "admin";
  window.history.replaceState(null, "", "/admin/avatar");
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("Avatar page", () => {
  it("uses the default URL view instead of a stored background view", async () => {
    window.localStorage.setItem("admin.avatar.assets_tab", "backgrounds");
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    render(<Avatar />);
    expect(await screen.findByText(/還沒有人物/)).toBeTruthy();
  });

  it("updates the visible asset panel when history restores a route", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({ backgrounds: [] });
    render(<Avatar />);
    await screen.findByText(/還沒有人物/);
    fireEvent.click(screen.getByRole("tab", { name: "背景" }));
    expect(window.location.pathname).toBe("/admin/avatar/backgrounds");
    window.history.replaceState(null, "", "/admin/avatar");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(await screen.findByText(/還沒有人物/)).toBeTruthy();
    window.history.replaceState(null, "", "/admin/avatar/backgrounds");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.queryByText(/還沒有人物/)).toBeNull();
  });

  it("renders character list", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "008", label: "角色八", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    render(<Avatar />);
    expect(await screen.findByText("008")).toBeTruthy();
    expect(screen.getByText("角色八")).toBeTruthy();
  });

  it("gives regular accounts a read-only list without admin-only controls", async () => {
    // 上傳、轉檔、改名、刪除的 API 都限管理員；畫面若照樣顯示，一按就回 403，
    // 整個後台會翻成「權限不足」。
    authState.role = "user";
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "008", label: "角色八", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    render(<Avatar />);

    expect(await screen.findByRole("button", { name: "試用 008" })).toBeTruthy();
    expect(screen.queryByText("從影片產生角色")).toBeNull();
    expect(screen.queryByText("上傳新人物")).toBeNull();
    expect(screen.queryByRole("button", { name: "改名" })).toBeNull();
    expect(screen.queryByRole("button", { name: "刪除" })).toBeNull();
  });

  it("shows admins the upload, conversion and rename controls", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "008", label: "角色八", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    render(<Avatar />);

    expect(await screen.findByRole("button", { name: "試用 008" })).toBeTruthy();
    expect(screen.getByText("從影片產生角色")).toBeTruthy();
    expect(screen.getByText("上傳新人物")).toBeTruthy();
    expect(screen.getByRole("button", { name: "改名" })).toBeTruthy();
  });

  it("shows empty state when no characters", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    render(<Avatar />);
    expect(await screen.findByText(/還沒有人物/)).toBeTruthy();
  });

  it("shows error when load fails", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockRejectedValue(new Error("boom"));
    render(<Avatar />);
    await waitFor(() => expect(screen.getByText(/boom/)).toBeTruthy());
  });

  it("keeps the page itself scrollable inside the app shell", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: Array.from({ length: 11 }, (_, index) => ({
        char_id: String(index).padStart(3, "0"),
        label: `角色 ${index}`,
        has_video: true,
        has_data: true,
        size_bytes: 1024,
        updated_at: "2026-06-08T00:00:00Z",
      })),
    });

    render(<Avatar />);

    const page = await screen.findByTestId("avatar-page");
    expect(page.className).toContain("h-full");
    expect(page.className).toContain("min-h-0");
    // 頁首固定在上方，和其他頁對齊；捲動的是頁首下面的內容區。
    const panel = screen.getByRole("tabpanel");
    expect(panel.className).toContain("min-h-0");
    expect(panel.className).toContain("overflow-y-auto");
  });

  it("hands the tried character and its owner project to the avatar app", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "010", label: "角色十", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z", owner_project_id: "proj-owner" },
        { char_id: "011", label: "角色十一", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z", owner_project_id: null },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "試用 010" }));

    // 前台登入後會用伺服器偏好蓋掉直接寫的鍵，所以改留一次性的交接指令。
    expect(window.localStorage.getItem("avatar.character_id")).toBeNull();
    const payload = JSON.parse(window.localStorage.getItem("avatar.admin_handoff") ?? "null");
    expect(payload).toMatchObject({ v: 1, accountId: "a", characterId: "010", projectId: "proj-owner" });
    expect(typeof payload.createdAt).toBe("number");
    expect(openSpy).toHaveBeenCalledWith("/", "_blank", "noopener,noreferrer");

    fireEvent.click(screen.getByRole("button", { name: "試用 011" }));
    const global = JSON.parse(window.localStorage.getItem("avatar.admin_handoff") ?? "null");
    expect(global).toMatchObject({ v: 1, accountId: "a", characterId: "011" });
    expect("projectId" in global).toBe(false);
  });

  it("opens the avatar app under the public prefix when the admin is served there", async () => {
    window.history.replaceState(null, "", "/openvman/admin/avatar");
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "010", label: "角色十", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "試用 010" }));

    expect(openSpy).toHaveBeenCalledWith("/openvman/", "_blank", "noopener,noreferrer");
  });

  it("uses a bounded zip icon for the GZ data picker", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });

    render(<Avatar />);

    await screen.findByText(/還沒有人物/);

    expect(screen.queryByText("settings_zip")).toBeNull();
    const icon = screen.getByText("folder_zip");
    expect(icon.className).toContain("w-4");
    expect(icon.className).toContain("overflow-hidden");
    expect(icon.getAttribute("aria-hidden")).toBe("true");
  });

  it("renames the display label without changing character id", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "010", label: "角色十", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    vi.spyOn(api, "updateAvatarCharacterLabel").mockResolvedValue({
      status: "ok",
      character: { char_id: "010", label: "新的名字", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
    });
    render(<Avatar />);
    fireEvent.click(await screen.findByRole("button", { name: "改名" }));

    const input = await screen.findByLabelText(/顯示名稱/);
    fireEvent.change(input, { target: { value: "新的名字" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    expect(api.updateAvatarCharacterLabel).toHaveBeenCalledWith("010", "新的名字");
    await waitFor(() => expect(screen.getByText("新的名字")).toBeTruthy());
    expect(screen.getByText("010")).toBeTruthy();
  });

  it("loads backgrounds from a dedicated Avatar tab", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({
      backgrounds: [
        {
          background_id: "clinic",
          label: "診間背景",
          url: "/static/backgrounds/clinic/image.png",
          mime_type: "image/png",
          size_bytes: 2048,
          updated_at: "2026-06-08T00:00:00Z",
        },
      ],
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "背景" }));

    expect(await screen.findByText("診間背景")).toBeTruthy();
    expect(api.fetchAvatarBackgrounds).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/admin/avatar/backgrounds");
  });

  it("opens the background route despite a stale stored character tab", async () => {
    window.history.replaceState(null, "", "/admin/avatar/backgrounds");
    window.localStorage.setItem("admin.avatar.assets_tab", "characters");
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({
      backgrounds: [
        {
          background_id: "clinic",
          label: "診間背景",
          url: "/static/backgrounds/clinic/image.png",
          mime_type: "image/png",
          size_bytes: 2048,
          updated_at: "2026-06-08T00:00:00Z",
        },
      ],
    });

    render(<Avatar />);

    expect(await screen.findByText("診間背景")).toBeTruthy();
    expect(api.fetchAvatarBackgrounds).toHaveBeenCalledOnce();
  });

  it("uploads a background image from the background tab", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({ backgrounds: [] });
    vi.spyOn(api, "uploadAvatarBackground").mockResolvedValue({
      status: "ok",
      background: {
        background_id: "clinic",
        label: "診間背景",
        url: "/static/backgrounds/clinic/image.png",
        mime_type: "image/png",
        size_bytes: 2048,
        updated_at: "2026-06-08T00:00:00Z",
      },
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "背景" }));
    fireEvent.change(await screen.findByPlaceholderText("背景 ID（background_id）"), {
      target: { value: "clinic" },
    });
    fireEvent.change(screen.getByPlaceholderText("顯示名稱"), {
      target: { value: "診間背景" },
    });
    fireEvent.change(screen.getByLabelText(/圖片/), {
      target: { files: [new File(["image"], "clinic.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上傳背景" }));

    await waitFor(() => {
      expect(api.uploadAvatarBackground).toHaveBeenCalledWith({
        backgroundId: "clinic",
        label: "診間背景",
        image: expect.any(File),
      });
    });
  });

  it("hands the chosen background to the avatar app", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({
      backgrounds: [
        {
          background_id: "clinic",
          label: "診間背景",
          url: "/static/backgrounds/clinic/image.png",
          mime_type: "image/png",
          size_bytes: 2048,
          updated_at: "2026-06-08T00:00:00Z",
          owner_project_id: "proj-owner",
        },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "背景" }));
    fireEvent.click(await screen.findByRole("button", { name: "使用 clinic" }));

    expect(window.localStorage.getItem("avatar.background_id")).toBeNull();
    expect(window.localStorage.getItem("avatar.background_url")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("avatar.admin_handoff") ?? "null")).toMatchObject({
      v: 1,
      accountId: "a",
      projectId: "proj-owner",
      backgroundId: "uploaded:clinic",
      backgroundUrl: "/static/backgrounds/clinic/image.png",
    });
    expect(openSpy).toHaveBeenCalledWith("/", "_blank", "noopener,noreferrer");
  });

  it("replaces the admin's own corner mascot without opening the avatar app", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarMascots").mockResolvedValue({
      mascots: [
        {
          mascot_id: "custom-vrm",
          label: "自訂 VRM",
          engine: "3d",
          model_url: "",
          vrm_url: "/static/mascots/custom-vrm/model.vrm",
          fit: "",
          builtin: false,
          size_bytes: 1024,
          updated_at: "",
        },
      ],
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    // 選項要從清單來：包上 MascotProvider，Avatar 頁載入的小助理才會成為可選項目。
    render(<MascotProvider><Avatar /></MascotProvider>);
    fireEvent.click(await screen.findByRole("tab", { name: "小助理" }));
    fireEvent.click(await screen.findByRole("button", { name: "使用 自訂 VRM" }));

    expect(window.localStorage.getItem("avatar.mascot_id")).toBe("custom-vrm");
    // 前台不讀這個設定，開前台只是多一個看不出差別的分頁。
    expect(openSpy).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("avatar.admin_handoff")).toBeNull();
  });

  it("captures uploaded mascot snapshots with that mascot's widget source", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarMascots").mockResolvedValue({
      mascots: [
        {
          mascot_id: "custom",
          label: "自訂小助理",
          engine: "3d",
          model_url: "",
          vrm_url: "/static/mascots/custom/model.vrm",
          fit: "",
          builtin: false,
          size_bytes: 4096,
          updated_at: "2026-07-08T00:00:00Z",
        },
      ],
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "小助理" }));

    const frame = await screen.findByTitle("小助理縮圖擷取");
    const src = decodeURIComponent(frame.getAttribute("src") ?? "");

    expect(src).toContain("/static/mascots/custom/model.vrm");
    expect(src).toContain("engine=3d");
  });

  it("uploads a mascot VRM from the mascot tab", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarMascots").mockResolvedValue({ mascots: [] });
    vi.spyOn(api, "uploadAvatarMascot").mockResolvedValue({
      status: "ok",
      mascot: {
        mascot_id: "custom",
        label: "自訂小助理",
        engine: "3d",
        model_url: "",
        vrm_url: "/static/mascots/custom/model.vrm",
        fit: "",
        builtin: false,
        size_bytes: 4096,
        updated_at: "2026-07-08T00:00:00Z",
      },
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "小助理" }));
    fireEvent.change(await screen.findByPlaceholderText("小助理 ID（mascot_id）"), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByPlaceholderText("小助理顯示名稱"), {
      target: { value: "自訂小助理" },
    });
    fireEvent.change(screen.getByLabelText(/VRM/), {
      target: { files: [new File(["glTF"], "custom.vrm", { type: "model/gltf-binary" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上傳小助理" }));

    await waitFor(() => {
      expect(api.uploadAvatarMascot).toHaveBeenCalledWith({
        mascotId: "custom",
        label: "自訂小助理",
        model: expect.any(File),
      });
    });
  });

  it("renames an uploaded mascot without changing mascot id", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarMascots").mockResolvedValue({
      mascots: [
        {
          mascot_id: "custom",
          label: "自訂小助理",
          engine: "3d",
          model_url: "",
          vrm_url: "/static/mascots/custom/model.vrm",
          fit: "",
          builtin: false,
          size_bytes: 4096,
          updated_at: "2026-07-08T00:00:00Z",
        },
      ],
    });
    vi.spyOn(api, "updateAvatarMascotLabel").mockResolvedValue({
      status: "ok",
      mascot: {
        mascot_id: "custom",
        label: "新小助理",
        engine: "3d",
        model_url: "",
        vrm_url: "/static/mascots/custom/model.vrm",
        fit: "",
        builtin: false,
        size_bytes: 4096,
        updated_at: "2026-07-08T00:00:00Z",
      },
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "小助理" }));
    fireEvent.click(await screen.findByRole("button", { name: "改名 custom" }));

    const input = await screen.findByLabelText(/顯示名稱/);
    fireEvent.change(input, { target: { value: "新小助理" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    expect(api.updateAvatarMascotLabel).toHaveBeenCalledWith("custom", "新小助理");
    await waitFor(() => expect(screen.getByText("新小助理")).toBeTruthy());
    expect(screen.getByText("custom")).toBeTruthy();
  });

  it("deletes uploaded mascots but not builtin mascots", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarMascots").mockResolvedValue({
      mascots: [
        {
          mascot_id: "qqman",
          label: "Frieren",
          engine: "3d",
          model_url: "",
          vrm_url: "/static/mascots/qqman/model.vrm",
          fit: "",
          builtin: true,
          size_bytes: 0,
          updated_at: "",
        },
        {
          mascot_id: "custom",
          label: "自訂小助理",
          engine: "3d",
          model_url: "",
          vrm_url: "/static/mascots/custom/model.vrm",
          fit: "",
          builtin: false,
          size_bytes: 4096,
          updated_at: "2026-07-08T00:00:00Z",
        },
      ],
    });
    vi.spyOn(api, "deleteAvatarMascot").mockResolvedValue({
      status: "ok",
      mascot_id: "custom",
    });

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "小助理" }));

    expect(screen.queryByRole("button", { name: "刪除 Frieren" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "刪除 custom" }));

    expect(api.deleteAvatarMascot).toHaveBeenCalledWith("custom");
    await waitFor(() => expect(screen.queryByText("custom")).toBeNull());
    expect(screen.getByText("Frieren")).toBeTruthy();
  });
});
