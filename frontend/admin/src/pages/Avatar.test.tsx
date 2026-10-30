import { useEffect, useState, type ReactElement } from "react";
import { NavigationProvider } from "../context/NavigationContext";
import { buildAdminPath, parseAdminRoute } from "../components/app/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render as renderComponent, screen, waitFor, within } from "@testing-library/react";
import Avatar from "./Avatar";
import * as api from "../api";

const authState = vi.hoisted(() => ({ role: "admin" as "root" | "admin" | "user" }));
const projectState = vi.hoisted(() => ({ projectId: "proj-a" }));
vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: projectState.projectId }),
}));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { id: "a", username: "a", role: authState.role } }),
}));

function render(element: ReactElement) {
  function RouteHarness({ element }: { element: ReactElement }) {
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
  const result = renderComponent(<RouteHarness element={element} />);
  return { ...result, rerender: (next: ReactElement) => result.rerender(<RouteHarness element={next} />) };
}

beforeEach(() => {
  authState.role = "admin";
  projectState.projectId = "proj-a";
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
    expect(screen.queryByText("從影片或圖片產生人物")).toBeNull();
    expect(screen.queryByText("上傳現成素材包")).toBeNull();
    expect(screen.queryByRole("button", { name: "改名" })).toBeNull();
    expect(screen.queryByRole("button", { name: "刪除" })).toBeNull();
  });

  it("lists regular accounts' assets for the current project", async () => {
    // 不帶專案時後端只回帳號自己被授權的素材，專案專屬的人物一個都看不到。
    authState.role = "user";
    const spy = vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    render(<Avatar />);

    await waitFor(() => expect(spy).toHaveBeenCalledWith("proj-a"));
  });

  it("keeps the new project's backgrounds when the old project's list answers late", async () => {
    // 背景還在載入就切專案：新專案要照樣載入，舊專案晚回來的清單不能蓋掉它。
    authState.role = "user";
    window.history.replaceState(null, "", "/admin/avatar/backgrounds");
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    const background = (id: string) => ({
      background_id: id, label: `背景 ${id}`, url: `/bg/${id}.png`, mime_type: "image/png",
      size_bytes: 1, updated_at: "2026-10-22T00:00:00Z",
    });
    let answerOld: (value: { backgrounds: ReturnType<typeof background>[] }) => void = () => {};
    const spy = vi.spyOn(api, "fetchAvatarBackgrounds").mockImplementation((project) =>
      project === "proj-a"
        ? new Promise((resolve) => { answerOld = resolve; })
        : Promise.resolve({ backgrounds: [background("bg-new")] }),
    );
    const view = render(<Avatar />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("proj-a"));

    projectState.projectId = "proj-b";
    view.rerender(<Avatar />);
    expect(await screen.findByText("背景 bg-new")).toBeTruthy();
    expect(spy).toHaveBeenCalledWith("proj-b");

    answerOld({ backgrounds: [background("bg-old")] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("背景 bg-old")).toBeNull();
    expect(screen.getByText("背景 bg-new")).toBeTruthy();
  });

  it("shows admins the upload, conversion and rename controls", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({
      characters: [
        { char_id: "008", label: "角色八", has_video: true, has_data: true, size_bytes: 1024, updated_at: "2026-06-08T00:00:00Z" },
      ],
    });
    render(<Avatar />);

    expect(await screen.findByRole("button", { name: "試用 008" })).toBeTruthy();
    expect(screen.getByText("從影片或圖片產生人物")).toBeTruthy();
    expect(screen.getByText("上傳現成素材包")).toBeTruthy();
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
    expect(icon.className).toContain("w-5");
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

    const input = await screen.findByDisplayValue("角色十");
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
    fireEvent.change(await screen.findByLabelText("背景 ID"), {
      target: { value: "clinic" },
    });
    fireEvent.change(screen.getByLabelText("顯示名稱"), {
      target: { value: "診間背景" },
    });
    fireEvent.change(screen.getByLabelText("背景圖片"), {
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

  it("has no mascot tab; the corner mascot is the built-in Haru only", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });

    render(<Avatar />);

    await screen.findByRole("tab", { name: "人物" });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["人物", "背景"]);
  });

  it("checks background images before uploading and shows server limits verbatim", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    vi.spyOn(api, "fetchAvatarBackgrounds").mockResolvedValue({ backgrounds: [] });
    const upload = vi.spyOn(api, "uploadAvatarBackground")
      .mockRejectedValue(new Error("圖片超過大小上限（25 MB）"));

    render(<Avatar />);
    fireEvent.click(await screen.findByRole("tab", { name: "背景" }));
    expect(await screen.findByText("PNG／JPG／WebP，25 MB 內。")).toBeTruthy();
    const picker = screen.getByLabelText("背景圖片");
    fireEvent.change(picker, {
      target: { files: [new File(["gif"], "bg.gif", { type: "image/gif" })] },
    });
    expect(screen.getByRole("alert").textContent).toContain("「bg.gif」不是支援的格式");

    fireEvent.change(screen.getByLabelText("背景 ID"), { target: { value: "clinic" } });
    fireEvent.change(screen.getByLabelText("顯示名稱"), { target: { value: "診間背景" } });
    fireEvent.change(picker, {
      target: { files: [new File(["png"], "bg.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上傳背景" }));

    await waitFor(() => expect(upload).toHaveBeenCalled());
    expect(await screen.findByText("圖片超過大小上限（25 MB）")).toBeTruthy();
  });

  it("refuses a bundle over the combined size before uploading", async () => {
    vi.spyOn(api, "fetchAvatarCharacters").mockResolvedValue({ characters: [] });
    const upload = vi.spyOn(api, "uploadAvatarCharacter");
    render(<Avatar />);
    await screen.findByText(/還沒有人物/);

    const bundle = screen.getByText("上傳現成素材包").closest("details")!;
    const video = new File(["v"], "01.webm", { type: "video/webm" });
    Object.defineProperty(video, "size", { value: 80 * 1024 * 1024 });
    const data = new File(["d"], "combined_data.json.gz", { type: "application/gzip" });
    Object.defineProperty(data, "size", { value: 30 * 1024 * 1024 });
    fireEvent.change(within(bundle).getByLabelText("人物 ID"), { target: { value: "big" } });
    fireEvent.change(within(bundle).getByLabelText("顯示名稱"), { target: { value: "大檔" } });
    fireEvent.change(within(bundle).getByLabelText("影片"), { target: { files: [video] } });
    fireEvent.change(within(bundle).getByLabelText("資料檔"), { target: { files: [data] } });
    fireEvent.click(within(bundle).getByRole("button", { name: "上傳素材包" }));

    expect(await screen.findByText("影片和資料檔合計 110.0 MB，上限是 100 MB。")).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
  });
});
