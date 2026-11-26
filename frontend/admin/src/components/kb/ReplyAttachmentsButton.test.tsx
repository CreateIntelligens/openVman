import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReplyAttachmentsButton from "./ReplyAttachmentsButton";
import { NavigationGuardProvider, useNavigationGuard } from "../../context/NavigationGuardContext";
import { fetchReplyLinks, saveReplyLinks } from "../../api";

const QR = "0f1e2d3c-4b5a-4968-8776-655443322110.png";
const OTHER = "11111111-2222-4333-8444-555555555555.png";

vi.mock("../../api", () => ({ fetchReplyLinks: vi.fn(), saveReplyLinks: vi.fn() }));

const uploadImage = vi.fn();
vi.mock("../../hooks/useQaNodes", () => ({
  useQaNodes: () => ({
    nodesTree: [{ node_id: "n", label: "n", qa_entries: [{ question: "q", source_path: "p", hidden: false, image_id: OTHER }], children: [] }],
    fetchTree: vi.fn().mockResolvedValue([]),
    uploadImage,
  }),
}));
vi.mock("./QaImagePreview", () => ({ default: ({ imageId }: { imageId: string }) => <span>{`預覽 ${imageId}`}</span> }));

let guardDirty = false;
function Probe() {
  guardDirty = useNavigationGuard().hasUnsavedChanges;
  return null;
}

async function openPanel() {
  render(<NavigationGuardProvider><Probe /><ReplyAttachmentsButton projectId="proj" /></NavigationGuardProvider>);
  fireEvent.click(screen.getByRole("button", { name: /回覆附件/ }));
  await screen.findByRole("dialog", { name: "回覆附件設定" });
}

describe("ReplyAttachmentsButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchReplyLinks).mockResolvedValue({ contact_image_id: null, catalog_url: null });
  });

  it("picks an uploaded QA image and a catalogue url and saves both for the project", async () => {
    vi.mocked(saveReplyLinks).mockImplementation(async (_p, links) => links);
    await openPanel();
    expect(fetchReplyLinks).toHaveBeenCalledWith("proj");

    fireEvent.click(await screen.findByRole("radio", { name: `選用圖片 ${OTHER}` }));
    fireEvent.change(screen.getByRole("textbox", { name: "型錄網址" }), { target: { value: " https://example.com/catalog " } });
    await waitFor(() => expect(guardDirty).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));

    await waitFor(() => expect(saveReplyLinks).toHaveBeenCalledWith("proj", {
      contact_image_id: OTHER, catalog_url: "https://example.com/catalog",
    }));
    await screen.findByText("已儲存回覆附件");
    await waitFor(() => expect(guardDirty).toBe(false));
  });

  it("uploads a new image and selects it", async () => {
    uploadImage.mockResolvedValue({ image_id: QR });
    await openPanel();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "qr.png", { type: "image/png" })] } });
    await waitFor(() => expect(uploadImage).toHaveBeenCalled());
    expect((await screen.findByRole("radio", { name: `選用圖片 ${QR}` })).getAttribute("aria-checked")).toBe("true");
  });

  it("clears the image or the url on its own, keeping the other one", async () => {
    vi.mocked(fetchReplyLinks).mockResolvedValue({ contact_image_id: QR, catalog_url: "https://example.com/c" });
    vi.mocked(saveReplyLinks).mockImplementation(async (_p, links) => links);
    await openPanel();
    await waitFor(() => expect((screen.getByRole("textbox", { name: "型錄網址" }) as HTMLInputElement).value).toBe("https://example.com/c"));

    fireEvent.click(screen.getByRole("button", { name: "清除聯絡圖片" }));
    await waitFor(() => expect(saveReplyLinks).toHaveBeenLastCalledWith("proj", {
      contact_image_id: null, catalog_url: "https://example.com/c",
    }));
    await waitFor(() => expect((screen.getByRole("button", { name: "清除型錄網址" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "清除型錄網址" }));
    await waitFor(() => expect(saveReplyLinks).toHaveBeenLastCalledWith("proj", {
      contact_image_id: null, catalog_url: null,
    }));
  });

  it("shows the backend message when the url is refused and keeps the draft", async () => {
    vi.mocked(saveReplyLinks).mockRejectedValue(new Error("型錄網址只收 https，長度 1 到 500 個字元。"));
    await openPanel();
    fireEvent.change(screen.getByRole("textbox", { name: "型錄網址" }), { target: { value: "http://bad" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect((await screen.findByRole("alert")).textContent).toContain("型錄網址只收 https");
    expect((screen.getByRole("textbox", { name: "型錄網址" }) as HTMLInputElement).value).toBe("http://bad");
  });
});
