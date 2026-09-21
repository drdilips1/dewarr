import { ChevronLeft, ChevronRight } from "lucide-react";

export default function BookPagination({
  page,
  total,
  onPage,
  busy = false,
  label = "Editions",
  size = 20,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
  busy?: boolean;
  label?: string;
  size?: number;
}) {
  if (!total) return null;
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <nav className="book-pagination" aria-label={`${label} pagination`}>
      <span className="muted" role="status">
        {(page - 1) * size + 1}–{Math.min(page * size, total)} of {total}{" "}
        {label.toLowerCase()}
      </span>
      <div>
        <button
          aria-label={`Previous ${label.toLowerCase()} page`}
          disabled={busy || page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft size={16} /> Previous
        </button>
        <span className="muted">
          {page} / {pages}
        </span>
        <button
          aria-label={`Next ${label.toLowerCase()} page`}
          disabled={busy || page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next <ChevronRight size={16} />
        </button>
      </div>
    </nav>
  );
}
