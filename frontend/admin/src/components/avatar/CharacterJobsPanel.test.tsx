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

    fireEvent.change(screen.getByPlaceholderText("人物 ID（char_id）"), { target: { value: "hero" } });
    fireEvent.change(screen.getByPlaceholderText("顯示名稱"), { target: { value: "主角" } });
    const file = new File([new Uint8Array([0, 0, 0, 24])], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText("Source video"), { target: { files: [file] } });
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
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
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
    expect(screen.getByText("150 frames · 1080×1920")).toBeTruthy();
  });

  it("dismisses finished jobs", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockResolvedValue({
      jobs: [job({ state: "failed", error: "第一幀偵測不到人臉" })],
    });
    const remove = vi.spyOn(api, "deleteAvatarCharacterJob").mockResolvedValue({ status: "ok" });
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    expect(await screen.findByText("第一幀偵測不到人臉")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss job hero" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("j1"));
    await waitFor(() => expect(screen.queryByText("第一幀偵測不到人臉")).toBeNull());
  });

  it("stays quiet when the queue is unavailable", async () => {
    vi.spyOn(api, "fetchAvatarCharacterJobs").mockRejectedValue(new Error("503"));
    render(<CharacterJobsPanel onCharacterCreated={() => {}} />);
    await waitFor(() => expect(api.fetchAvatarCharacterJobs).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("list", { name: "Conversion jobs" })).toBeNull();
  });
});
