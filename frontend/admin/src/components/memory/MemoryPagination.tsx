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
        className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:text-white hover:border-slate-600 transition-colors disabled:opacity-30"
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
              : "border border-slate-700 text-slate-400 hover:text-white"
          }`}
        >
          {pageNumber}
        </button>
      ))}
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:text-white hover:border-slate-600 transition-colors disabled:opacity-30"
      >
        下一頁
      </button>
    </div>
  );
}
