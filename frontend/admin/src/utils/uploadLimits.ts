export const MAX_UPLOAD_FILE_SIZE_BYTES = 5 * 1024 * 1024;
export const UPLOAD_FILE_SIZE_ERROR = "檔案大小不可超過 5 MB";

type UploadFileLike = Pick<File, "name" | "size">;

export function validateUploadFiles(files: Iterable<UploadFileLike>): string | null {
  for (const file of files) {
    if (file.size > MAX_UPLOAD_FILE_SIZE_BYTES) {
      return UPLOAD_FILE_SIZE_ERROR;
    }
  }
  return null;
}
