import { BookOpen } from "lucide-react";
import { Link } from "react-router-dom";
import type { components } from "../api/schema";
import { BookCard } from "../components";

export type Shelf = components["schemas"]["DiscoveryShelf"];
export type DiscoveryItem = components["schemas"]["DiscoveryItem"];

export default function DiscoveryShelf({
  shelf,
  onPreview,
}: {
  shelf: Shelf;
  onPreview: (item: DiscoveryItem, button: HTMLButtonElement) => void;
}) {
  const items = shelf.items || [];
  return (
    <>
      <div className="section-heading discovery-heading">
        <div>
          <h2>{shelf.title}</h2>
          <p className="muted">{shelf.attribution}</p>
        </div>
        {shelf.stale && <span className="count">Cached shelf</span>}
      </div>
      {shelf.warning && (
        <p className="notice" role="status">
          {shelf.warning}
        </p>
      )}
      {shelf.status === "not-connected" && (
        <Link className="back-link" to="/metadata">
          Connect Hardcover
        </Link>
      )}
      {shelf.status === "ready" && items.length === 0 && (
        <p className="muted">No titles available for this shelf yet.</p>
      )}
      {items.length > 0 && (
        <ul className="discovery-shelf" aria-label={shelf.title}>
          {items.map((item) => (
            <li
              key={
                item.work?.id ||
                `${item.book.provider}:${item.book.external_id}`
              }
            >
              {item.work ? (
                <BookCard work={item.work} />
              ) : (
                <button
                  className="book-card discovery-book"
                  onClick={(event) => onPreview(item, event.currentTarget)}
                  aria-label={`Preview ${item.book.title}`}
                >
                  <div className="book-cover">
                    {item.book.cover_url ? (
                      <img
                        src={item.book.cover_url}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <div className="type-cover">
                        <BookOpen size={22} aria-hidden="true" />
                        <span>{item.book.title}</span>
                        <small>{item.book.authors.join(" · ")}</small>
                      </div>
                    )}
                  </div>
                  <h3>{item.book.title}</h3>
                  <p>{item.book.authors.join(", ") || "Author unknown"}</p>
                  <small className="muted">Library match not established</small>
                </button>
              )}
              {item.book.release_date && (
                <p className="discovery-date">
                  Published {item.book.release_date}
                </p>
              )}
              {item.reason !== shelf.attribution &&
                item.reason !== shelf.title && (
                  <p className="discovery-reason">{item.reason}</p>
                )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
