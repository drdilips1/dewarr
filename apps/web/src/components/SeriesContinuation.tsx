import { usePagedQuery } from "../hooks/usePagedQuery";
import BookLink from "./BookLink";
import InfiniteScroll from "./InfiniteScroll";
import BookCover from "./BookCover";
import { useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Check, Headphones } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Medium = "any" | "ebook" | "audio";
type SeriesGap = components["schemas"]["SeriesGap"];
const mediumLabel = { any: "books", ebook: "ebooks", audio: "audiobooks" };
const singularLabel = { any: "book", ebook: "ebook", audio: "audiobook" };

export default function SeriesContinuation({
  hideEmpty = false,
}: { hideEmpty?: boolean } = {}) {
  const [medium, setMedium] = useState<Medium>("any");
  const query = usePagedQuery({
    queryKey: ["discovery", "series", medium],
    queryFn: async (page, signal) =>
      result(
        await api.GET("/api/discovery/series", {
          signal,
          params: { query: { medium, page, limit: 4 } },
        }),
      ),
    refetchInterval: 60_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    next: (last, pages) =>
      last.has_more && pages.length < 100 ? pages.length + 1 : undefined,
  });
  const items = query.data?.items || [];
  if (hideEmpty && medium === "any" && query.data && !items.length) return null;
  return (
    <section
      className="discovery-section"
      aria-labelledby="series-continuation-title"
    >
      <div className="page-heading discovery-heading series-gap-heading">
        <div>
          <h2 id="series-continuation-title">Continue your series</h2>
          <p className="muted">Find the missing books in your series.</p>
        </div>
        <div className="shelf-controls">
          {" "}
          <label>
            Find missing
            <select
              value={medium}
              onChange={(event) => {
                setMedium(event.target.value as Medium);
              }}
            >
              <option value="any">Books in either format</option>
              <option value="ebook">Ebooks</option>
              <option value="audio">Audiobooks</option>
            </select>
          </label>
        </div>
      </div>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry series shelf
        </button>
      )}
      {query.data && (
        <>
          {items.length ? (
            <div className="series-gap-grid">
              {items.map((series) => (
                <SeriesCard
                  key={series.external_id}
                  series={series}
                  medium={medium}
                />
              ))}
            </div>
          ) : (
            <div className="panel">
              <p>
                No missing {mediumLabel[medium]} found in these loaded series.
              </p>
              <p className="muted">
                Open a book you own, follow its series link and load the
                catalog. New or refreshed series can then appear here. This
                shelf describes your library, not your reading progress.
              </p>
              <Link className="back-link" to="/">
                Browse your catalog →
              </Link>
            </div>
          )}
        </>
      )}
      <InfiniteScroll query={query} />
    </section>
  );
}

function SeriesCard({ series, medium }: { series: SeriesGap; medium: Medium }) {
  return (
    <article
      className="panel series-gap-card"
      aria-label={`${series.name} library gaps`}
    >
      <header>
        <h3>
          <Link
            to={`/series/hardcover/${encodeURIComponent(series.external_id)}`}
          >
            {series.name}
          </Link>
        </h3>
        <p className="muted">
          {series.owned} in library · {series.missing} missing{" "}
          {series.missing === 1 ? singularLabel[medium] : mediumLabel[medium]}
        </p>
        {(series.catalog_stale || series.inventory_stale) && (
          <p className="series-gap-note">
            {series.catalog_stale && "Catalog needs a refresh. "}
            {series.inventory_stale && "Using last known library availability."}
          </p>
        )}
      </header>
      <ol className="series-gap-books">
        {series.books.map(({ work, position, ambiguous_position }) => (
          <li key={work.id}>
            <BookLink
              aria-label={`View ${work.title}`}
              className="series-gap-book"
              to={`/books/${work.id}`}
            >
              <div className="series-gap-cover">
                <BookCover title={work.title} work={work} medium={medium} />
              </div>
              <div className="series-gap-book-detail">
                <span className="series-gap-note">
                  {position ? `Position ${position}` : "Order unknown"}
                  {ambiguous_position && " · Order needs review"}
                </span>
                <h4>{work.title}</h4>
                <p className="muted">
                  {work.authors.join(", ") || "Author unknown"}
                </p>
                <div className="media-badges">
                  {work.availability.owned && (
                    <span>
                      <Check size={12} aria-hidden="true" /> In library
                    </span>
                  )}
                  {work.availability.ebook && (
                    <span>
                      <BookOpen size={12} aria-hidden="true" /> Ebook
                    </span>
                  )}
                  {work.availability.audio && (
                    <span>
                      <Headphones size={12} aria-hidden="true" /> Audio
                    </span>
                  )}
                  {work.availability.stale && (
                    <span>Last known availability</span>
                  )}
                  {work.availability.in_collection && (
                    <span>In collection</span>
                  )}
                </div>
              </div>
            </BookLink>
          </li>
        ))}
      </ol>
      <footer>
        {series.unknown_publication + series.future_publication > 0 && (
          <p className="series-gap-note">
            {series.unknown_publication > 0 &&
              `${series.unknown_publication} with unknown publication date. `}
            {series.future_publication > 0 &&
              `${series.future_publication} not yet published. `}
            These are excluded from the missing count.
          </p>
        )}
        <Link
          className="back-link"
          to={`/series/hardcover/${encodeURIComponent(series.external_id)}`}
        >
          View series
          {series.missing > series.books.length
            ? ` · ${series.missing - series.books.length} more missing`
            : ""}{" "}
          →
        </Link>
      </footer>
    </article>
  );
}
