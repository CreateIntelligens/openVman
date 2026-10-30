/**
 * 各上傳欄位接受的檔案類型與大小上限。
 *
 * 這裡只在送出前擋掉明顯不對的檔案，省得等上傳完才被退；伺服器仍是最後
 * 把關（影片長度、圖片尺寸只在伺服器檢查），它回的 413／415 說明原樣顯示。
 */

const MB = 1024 * 1024;

export type FileKind = {
  /** 錯誤訊息裡怎麼稱呼這個欄位要的東西，例如「影片或圖片」。 */
  noun: string;
  /** 小寫、含點的副檔名。 */
  extensions: readonly string[];
  /** 給使用者看的格式名稱。 */
  formats: readonly string[];
  maxBytes: number;
};

type MediaKind = FileKind & { media: "video" | "image" };

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"] as const;
const IMAGE_FORMATS = ["PNG", "JPG", "WebP"] as const;

export const SOURCE_VIDEO: MediaKind = {
  media: "video",
  noun: "影片",
  extensions: [".mp4", ".mov", ".m4v", ".webm"],
  formats: ["MP4", "MOV", "WebM"],
  maxBytes: 200 * MB,
};
export const SOURCE_VIDEO_MAX_SECONDS = 60;

export const SOURCE_IMAGE: MediaKind = {
  media: "image",
  noun: "圖片",
  extensions: IMAGE_EXTENSIONS,
  formats: IMAGE_FORMATS,
  maxBytes: 25 * MB,
};
export const SOURCE_IMAGE_MAX_SIDE = 8192;
/** 靜態圖片會被做成這麼長的循環片段。 */
export const STILL_CLIP_SECONDS = 10;

export const BUNDLE_VIDEO: FileKind = {
  noun: "影片",
  extensions: [".webm"],
  formats: ["WebM"],
  maxBytes: 100 * MB,
};
export const BUNDLE_DATA: FileKind = {
  noun: "資料檔",
  extensions: [".gz"],
  formats: ["GZ"],
  maxBytes: 100 * MB,
};
/** 素材包的影片與資料檔合計上限。 */
export const BUNDLE_TOTAL_MAX_BYTES = 100 * MB;

export const BACKGROUND_IMAGE: FileKind = {
  noun: "圖片",
  extensions: IMAGE_EXTENSIONS,
  formats: IMAGE_FORMATS,
  maxBytes: 25 * MB,
};

/** 從影片產生人物：影片或圖片都收，各自有上限。 */
export const SOURCE_KINDS: readonly MediaKind[] = [SOURCE_VIDEO, SOURCE_IMAGE];

export function acceptList(kinds: readonly FileKind[]): string {
  return [...new Set(kinds.flatMap((kind) => kind.extensions))].join(",");
}

export function formatLimit(bytes: number): string {
  return `${Math.round(bytes / MB)} MB`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < MB) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / MB).toFixed(1)} MB`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

/** 依副檔名找出檔案屬於哪一種；瀏覽器給的 MIME 對 .mov 常是空的，不可靠。 */
export function matchKind<K extends FileKind>(file: File, kinds: readonly K[]): K | null {
  const extension = extensionOf(file.name);
  return kinds.find((kind) => kind.extensions.includes(extension)) ?? null;
}

function joinFormats(kinds: readonly FileKind[]): string {
  const formats = [...new Set(kinds.flatMap((kind) => kind.formats))];
  if (formats.length <= 1) return formats.join("");
  return `${formats.slice(0, -1).join("、")} 或 ${formats[formats.length - 1]}`;
}

/** 回傳要給使用者看的錯誤；檔案可以送就回 null。 */
export function checkFile(file: File, kinds: readonly FileKind[]): string | null {
  const kind = matchKind(file, kinds);
  if (!kind) {
    return `「${file.name}」不是支援的格式，請改選 ${joinFormats(kinds)} 檔。`;
  }
  if (file.size > kind.maxBytes) {
    return `「${file.name}」有 ${formatFileSize(file.size)}，${kind.noun}上限是 ${formatLimit(kind.maxBytes)}。`;
  }
  return null;
}

export function checkBundleTotal(video: File, data: File): string | null {
  const total = video.size + data.size;
  if (total <= BUNDLE_TOTAL_MAX_BYTES) return null;
  return `影片和資料檔合計 ${formatFileSize(total)}，上限是 ${formatLimit(BUNDLE_TOTAL_MAX_BYTES)}。`;
}

export function isImageFile(file: File): boolean {
  return matchKind(file, [SOURCE_IMAGE]) !== null;
}

export function isVideoFile(file: File): boolean {
  return matchKind(file, [SOURCE_VIDEO]) !== null;
}
