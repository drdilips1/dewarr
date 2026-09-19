import type { ReactNode } from "react";
import { BookOpen, Check, Headphones } from "lucide-react";
import { Link } from "react-router-dom";
import type { Work } from "./api/client";

export function Notice({ error }: { error: Error | null }) {
  return error ? (
    <p className="notice error" role="alert">
      {error.message}
    </p>
  ) : null;
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <BookOpen size={36} aria-hidden="true" />
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}

export function Loading() {
  return (
    <p className="loading" role="status">
      Loading your shelves…
    </p>
  );
}

export function BookCard({ work }: { work: Work }) {
  return (
    <Link className="book-card" to={`/books/${work.id}`}>
      <div className="book-cover">
        {work.cover_url ? (
          <img src={work.cover_url} alt="" loading="lazy" />
        ) : (
          <div className="type-cover">
            <BookOpen size={22} aria-hidden="true" />
            <span>{work.title}</span>
            <small>{work.authors.join(" · ")}</small>
          </div>
        )}
        {work.availability.owned ? (
          <span className="owned-badge">
            <Check size={12} /> In library
          </span>
        ) : null}
      </div>
      <h3>{work.title}</h3>
      <p>{work.authors.join(", ") || "Author unknown"}</p>
      <div className="media-badges">
        {work.availability.ebook ? (
          <span>
            <BookOpen size={12} /> Ebook
          </span>
        ) : null}
        {work.availability.audio ? (
          <span>
            <Headphones size={12} /> Audio
          </span>
        ) : null}
        {work.availability.stale ? <span>Last known availability</span> : null}
        {work.availability.in_collection ? <span>In collection</span> : null}
      </div>
    </Link>
  );
}
