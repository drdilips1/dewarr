import { Info } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";

export default function BookDetailsStatus({
  error,
  unmatched,
  reason,
  retry,
  busy,
  workId,
}: {
  error?: Error | null;
  unmatched: boolean;
  reason?: string | null;
  retry: () => void;
  busy: boolean;
  workId: string;
}) {
  if (!error && !unmatched) return null;
  const status = error instanceof ApiError ? error.status : undefined;
  const missingEndpoint =
    status === 404 && error?.message.toLowerCase() === "not found";
  const connection =
    status === 409 && /connect|account|token/i.test(error?.message || "");
  const title = unmatched
    ? "Choose a Hardcover match"
    : connection
      ? "Check your Hardcover connection"
      : "Book details couldn’t load";
  const description = unmatched
    ? reason ||
      "We couldn’t verify a unique match using this book’s identifiers, title, and author. Choose the correct book to show its synopsis, ratings and reviews."
    : missingEndpoint
      ? "The server doesn’t have the book-details lookup available. Restart or update the app server, then retry."
      : connection
        ? "Your Hardcover connection needs attention before we can load its synopsis, ratings and reviews."
        : status === 429
          ? "Hardcover is limiting requests. Wait a moment, then retry to load ratings and reviews."
          : status === 404
            ? "The linked book record could not be found. Review its metadata match or retry if the record has moved."
            : "Additional metadata is temporarily unavailable. Retry to load the missing synopsis, ratings or reviews.";
  return (
    <section
      className="book-details-status"
      role="status"
      aria-label="Book details status"
    >
      <Info size={20} aria-hidden="true" />
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
        <p className="muted">
          Your library copies and files are still available.
        </p>
      </div>
      <div className="book-details-status-actions">
        {!unmatched && (
          <button disabled={busy} onClick={retry}>
            {busy ? "Retrying…" : "Retry details"}
          </button>
        )}
        <Link
          to={connection ? "/settings#catalog" : `/books/${workId}?tab=manage`}
        >
          {connection ? "Connection settings" : "Review book match"}
        </Link>
      </div>
    </section>
  );
}
