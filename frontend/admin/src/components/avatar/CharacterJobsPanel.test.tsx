import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import CharacterJobsPanel from "./CharacterJobsPanel";
import * as api from "../../api";
import type { AvatarJob } from "../../api";

function job(overrides: Partial<AvatarJob>): AvatarJob {
  return { job_id: "j1", state: "queued", char_id: "hero", label: "主角", ...overrides };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("CharacterJobsPanel", () => {
  it("submits the clip and lists the queued job", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs")
      .mockResolvedValueOnce({ jobs: [] })
      .mockResolvedValue({ jobs: [job({ stage: "landmarks", state: "running", done: 30, total: 150 })] });
    const submit = vi.spyOn(api, "submitAvatarCharacterJob").mockResolvedValue({
      status: "queued",
      job: job({}),
    });
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);

    fireEvent.change(screen.getByLabelText("人物 ID"), { target: { value: "hero" } });
    fireEvent.change(screen.getByLabelText("顯示名稱"), { target: { value: "主角" } });
    const file = new File([new Uint8Array([0, 0, 0, 24])], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText("來源影片或圖片"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "產生人物" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith({
      charId: "hero", label: "主角", video: file, projectId: undefined,
    }));
    expect(await screen.findByText("擷取臉部特徵 30/150")).toBeTruthy();
    expect(screen.getByText("已排入轉換佇列")).toBeTruthy();
  });

  it("refuses to submit without a video", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({ jobs: [] });
    const submit = vi.spyOn(api, "submitAvatarCharacterJob");
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "產生人物" }));
    expect((await screen.findByRole("alert")).textContent).toContain("請填人物 ID、顯示名稱，並選好影片或圖片");
    expect(submit).not.toHaveBeenCalled();
  });

  it("accepts a frontal image as the source and offers both types", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({ jobs: [] });
    const submit = vi.spyOn(api, "submitAvatarCharacterJob").mockResolvedValue({
      status: "queued",
      job: job({}),
    });
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);

    const input = screen.getByLabelText("來源影片或圖片") as HTMLInputElement;
    expect(input.accept).toBe(".mp4,.mov,.m4v,.webm,.png,.jpg,.jpeg,.webp");
    expect(screen.getByText("選擇影片或圖片")).toBeTruthy();
    expect(screen.getByText(/圖片會做成 10 秒的循環片段/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("人物 ID"), { target: { value: "face" } });
    fireEvent.change(screen.getByLabelText("顯示名稱"), { target: { value: "正面照" } });
    const image = new File(["png"], "face.png", { type: "image/png" });
    fireEvent.drop(input.closest("label")!, { dataTransfer: { files: [image] } });
    fireEvent.click(screen.getByRole("button", { name: "產生人物" }));

    // 圖片和影片走同一個 video 欄位，後端依內容判斷。
    await waitFor(() => expect(submit).toHaveBeenCalledWith({
      charId: "face", label: "正面照", video: image, projectId: undefined,
    }));
  });

  it("rejects an oversized source before uploading", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({ jobs: [] });
    const submit = vi.spyOn(api, "submitAvatarCharacterJob");
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);

    const big = new File(["x"], "long.mp4", { type: "video/mp4" });
    Object.defineProperty(big, "size", { value: 250 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText("來源影片或圖片"), { target: { files: [big] } });

    expect(screen.getByRole("alert").textContent).toBe("「long.mp4」有 250.0 MB，影片上限是 200 MB。");
    fireEvent.change(screen.getByLabelText("人物 ID"), { target: { value: "hero" } });
    fireEvent.change(screen.getByLabelText("顯示名稱"), { target: { value: "主角" } });
    fireEvent.click(screen.getByRole("button", { name: "產生人物" }));
    expect(submit).not.toHaveBeenCalled();
  });

  it("shows the server's limit message as-is", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({ jobs: [] });
    vi.spyOn(api, "submitAvatarCharacterJob").mockRejectedValue(new Error("影片超過長度上限（60 秒）"));
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);

    fireEvent.change(screen.getByLabelText("人物 ID"), { target: { value: "hero" } });
    fireEvent.change(screen.getByLabelText("顯示名稱"), { target: { value: "主角" } });
    fireEvent.change(screen.getByLabelText("來源影片或圖片"), {
      target: { files: [new File(["x"], "clip.webm", { type: "video/webm" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "產生人物" }));

    expect((await screen.findByRole("alert")).textContent).toContain("影片超過長度上限（60 秒）");
  });

  it("labels the loop check stage", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({
      jobs: [job({ state: "running", stage: "loop" })],
    });
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    expect(await screen.findByText("檢查首尾銜接")).toBeTruthy();
  });

  it("polls while a job runs and reloads characters once it is done", async () => {
    vi.useFakeTimers();
    const fetchJobs = vi.spyOn(api, "fetchAvatarCharacterJobs")
      .mockResolvedValueOnce({ jobs: [job({ state: "running", stage: "transcode" })] })
      .mockResolvedValue({ jobs: [job({ state: "done", frame_count: 150, width: 1080, height: 1920 })] });
    const onCreated = vi.fn();
    render(<CharacterJobsPanel onCharacterCreated={onCreated} />);

    await vi.waitFor(() => expect(fetchJobs).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(2000);
    await vi.waitFor(() => expect(fetchJobs).toHaveBeenCalledTimes(2));
    expect(onCreated).toHaveBeenCalledTimes(1);

    // Nothing left running: the poll stops.
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchJobs).toHaveBeenCalledTimes(2);
    expect(screen.getByText("150 幀 · 1080×1920")).toBeTruthy();
  });

  it("dismisses finished jobs", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({
      jobs: [job({ state: "failed", error: "第一幀偵測不到人臉" })],
    });
    const remove = vi.spyOn(api, "deleteAvatarCharacterJob").mockResolvedValue({ status: "ok" });
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    expect(await screen.findByText("第一幀偵測不到人臉")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "移除工作 hero" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("j1"));
    await waitFor(() => expect(screen.queryByText("第一幀偵測不到人臉")).toBeNull());
  });

  it("stays quiet when the queue is unavailable", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockRejectedValue(new Error("503"));
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    await waitFor(() => expect(api.fetchAvatarCharacterJobs).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("list", { name: "轉檔工作" })).toBeNull();
  });
});
