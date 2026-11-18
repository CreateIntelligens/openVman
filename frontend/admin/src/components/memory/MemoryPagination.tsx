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
    <nav
      aria-label="記憶分頁"
      className="flex flex-wrap items-center justify-center gap-2 sm:gap-3"
    >
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="shrink-0 whitespace-nowrap rounded-lg border border-border px-3 py-2 text-sm text-content-muted hover:text-content hover:border-border-strong transition-colors disabled:opacity-30"
      >
        上一頁
      </button>
      <div className="order-last flex w-full flex-wrap justify-center gap-1 sm:order-none sm:w-auto sm:gap-3">
        {pageNumbers.map((pageNumber) => (
          <button
            key={pageNumber}
            aria-label={`第 ${pageNumber} 頁`}
            aria-current={pageNumber === page ? "page" : undefined}
            onClick={() => onPageChange(pageNumber)}
            className={`shrink-0 rounded-lg px-2 py-2 text-sm font-semibold transition-colors sm:px-3 ${
              pageNumber === page
                ? "bg-primary text-white"
                : "border border-border text-content-muted hover:text-content "
            }`}
          >
            {pageNumber}
          </button>
        ))}
      </div>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="shrink-0 whitespace-nowrap rounded-lg border border-border px-3 py-2 text-sm text-content-muted hover:text-content hover:border-border-strong transition-colors disabled:opacity-30"
      >
        下一頁
      </button>
    </nav>
  );
}
