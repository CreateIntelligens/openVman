type UploadFileLike = Pick<File, "name" | "size">;

const MIB = 1024 * 1024;

export function formatUploadSize(bytes: number): string {
  if (bytes >= MIB) {
    const mb = bytes / MIB;
    return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
  }
  return `${bytes} bytes`;
}

export function formatUploadDuration(seconds: number): string {
  return seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} 分鐘` : `${seconds} 秒`;
}

export function validateUploadFiles(
  files: Iterable<UploadFileLike>,
  maxBytes: number,
): string | null {
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
    return "無法取得檔案大小上限，請稍後再試";
  }
  for (const file of files) {
    if (file.size > maxBytes) {
      return `檔案大小不可超過 ${formatUploadSize(maxBytes)}`;
    }
  }
  return null;
}
