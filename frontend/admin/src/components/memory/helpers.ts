export const PAGE_WINDOW_SIZE = 7;

export function getVisiblePageNumber(index: number, currentPage: number, totalPages: number): number {
  if (totalPages <= PAGE_WINDOW_SIZE) return index + 1;
  if (currentPage <= 4) return index + 1;
  return Math.min(currentPage - 3 + index, totalPages);
}

export function parseMetadataJson(raw: string): Record<string, string> {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
