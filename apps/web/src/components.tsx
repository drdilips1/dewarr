import BookLink from "./components/BookLink";
import type { ReactNode } from "react";
import { BookOpen } from "lucide-react";
import type { Work } from "./api/client";
import BookCover from "./components/BookCover";

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

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="loading-spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function BookCard({
  work,
  to,
  cover,
  medium,
  rating,
}: {
  work: Work;
  rating?: number | null;
  to?: string;
  cover?: string | null;
  medium?: "any" | "ebook" | "audio";
}) {
  return (
    <BookLink
      aria-label={`View ${work.title}`}
      className="book-card"
      to={to || `/books/${work.id}`}
    >
      <BookCover
        title={work.title}
        work={work}
        cover={cover}
        medium={medium}
        rating={rating}
      />
      <h3 title={work.title}>{work.title}</h3>
      <p title={work.authors.join(", ")}>
        {work.authors.join(", ") || "Author unknown"}
      </p>
    </BookLink>
  );
}
