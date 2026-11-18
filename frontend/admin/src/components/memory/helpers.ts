export const PAGE_WINDOW_SIZE = 7;

export function getVisiblePageNumber(index: number, currentPage: number, totalPages: number): number {
  if (totalPages <= PAGE_WINDOW_SIZE) return index + 1;
  const firstPage = Math.max(
    1,
    Math.min(currentPage - 3, totalPages - PAGE_WINDOW_SIZE + 1),
  );
  return firstPage + index;
}

export function parseMetadataJson(raw: string): Record<string, string> {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
