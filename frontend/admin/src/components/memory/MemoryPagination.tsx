import { PAGE_WINDOW_SIZE, getVisiblePageNumber } from "./helpers";

interface MemoryPaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function MemoryPagination({
  page,
  totalPages,
  onPageChange,
}: MemoryPaginationProps) {
  const visibleCount = Math.min(totalPages, PAGE_WINDOW_SIZE);
  const pageNumbers = Array.from({ length: visibleCount }, (_, i) =>
    getVisiblePageNumber(i, page, totalPages),
  );
  if (totalPages <= 1) {
    return null;
  }

  return (
    <div className="flex items-center justify-center gap-3">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="rounded-lg border border-border px-3 py-2 text-sm text-content-muted hover:text-content hover:border-border-strong transition-colors disabled:opacity-30"
      >
        上一頁
      </button>
      {pageNumbers.map((pageNumber) => (
        <button
          key={pageNumber}
          onClick={() => onPageChange(pageNumber)}
          className={`rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
            pageNumber === page
              ? "bg-primary text-white"
              : "border border-border text-content-muted hover:text-content "
          }`}
        >
          {pageNumber}
        </button>
      ))}
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg border border-border px-3 py-2 text-sm text-content-muted hover:text-content hover:border-border-strong transition-colors disabled:opacity-30"
      >
        下一頁
      </button>
    </div>
  );
}
