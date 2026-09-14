type UploadFileLike = Pick<File, "name" | "size">;

export function validateUploadFiles(
  files: Iterable<UploadFileLike>,
  maxBytes: number,
): string | null {
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
    return "無法取得檔案大小上限，請稍後再試";
  }
  for (const file of files) {
    if (file.size > maxBytes) {
      const limit = maxBytes >= 1024 * 1024
        ? `${maxBytes / (1024 * 1024)} MiB`
        : `${maxBytes} bytes`;
      return `檔案大小不可超過 ${limit}`;
    }
  }
  return null;
}
