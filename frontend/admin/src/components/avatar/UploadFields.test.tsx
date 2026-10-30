import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { FileDropField } from "./UploadFields";
import { SOURCE_KINDS } from "./uploadRules";

function Harness({ onChange }: { onChange?: (file: File | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <FileDropField
      variant="media"
      label="來源影片或圖片"
      kinds={SOURCE_KINDS}
      file={file}
      onChange={(next) => {
        setFile(next);
        onChange?.(next);
      }}
      chooseText="選擇影片或圖片"
      icon="movie"
      hint="限制說明"
    />
  );
}

function fileOf(name: string, type: string, bytes = 4): File {
  const file = new File(["data"], name, { type });
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

beforeEach(() => {
  // jsdom 沒有 object URL；預覽靠它，補一個可觀察的假實作。
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("FileDropField", () => {
  it("keeps the native input focusable and limits it to the accepted types", () => {
    render(<Harness />);
    const input = screen.getByLabelText("來源影片或圖片") as HTMLInputElement;
    expect(input.type).toBe("file");
    expect(input.accept).toBe(".mp4,.mov,.m4v,.webm,.png,.jpg,.jpeg,.webp");
    // display:none 的輸入框鍵盤到不了；要用 sr-only。
    expect(input.className).toContain("sr-only");
    expect(input.className).not.toContain("hidden");
    input.focus();
    expect(document.activeElement).toBe(input);
    expect(screen.getByText("選擇影片或圖片")).toBeTruthy();
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("accepts a dropped file and previews an image on a checkerboard", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByLabelText("來源影片或圖片");
    const zone = input.closest("label")!;
    const image = fileOf("face.png", "image/png");

    fireEvent.dragOver(zone, { dataTransfer: { files: [image], dropEffect: "none" } });
    expect(zone.getAttribute("data-dragging")).toBe("true");
    fireEvent.drop(zone, { dataTransfer: { files: [image] } });

    expect(onChange).toHaveBeenCalledWith(image);
    expect(zone.getAttribute("data-dragging")).toBeNull();
    const preview = screen.getByTestId("file-preview");
    expect(preview.style.backgroundImage).toContain("linear-gradient");
    const img = screen.getByRole("img", { name: "預覽 face.png" }) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("blob:preview");
    expect(screen.getByText("face.png")).toBeTruthy();
    // 欄位預設是影片圖示，選了圖片要換成圖片圖示。
    expect(zone.textContent).toContain("image");
    expect(zone.textContent).not.toContain("movie");
  });

  it("previews a chosen video as a muted loop", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("來源影片或圖片"), {
      target: { files: [fileOf("clip.mov", "")] },
    });
    const video = screen.getByLabelText("預覽 clip.mov") as HTMLVideoElement;
    expect(video.tagName).toBe("VIDEO");
    expect(video.muted).toBe(true);
    expect(video.loop).toBe(true);
    expect(video.closest("label")!.textContent).toContain("movie");
  });

  it("rejects a wrong type or an oversized file before it reaches the form", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByLabelText("來源影片或圖片");

    fireEvent.drop(input.closest("label")!, {
      dataTransfer: { files: [fileOf("notes.pdf", "application/pdf")] },
    });
    expect(screen.getByRole("alert").textContent).toContain("「notes.pdf」不是支援的格式");
    expect(input.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(input, {
      target: { files: [fileOf("huge.png", "image/png", 30 * 1024 * 1024)] },
    });
    expect(screen.getByRole("alert").textContent).toBe("「huge.png」有 30.0 MB，圖片上限是 25 MB。");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("file-preview")).toBeNull();
  });

  it("clears the chosen file", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("來源影片或圖片"), {
      target: { files: [fileOf("face.jpg", "image/jpeg")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "移除 face.jpg" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText("face.jpg")).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });
});
