import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BookOpen, Check, Headphones } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Medium = "any" | "ebook" | "audio";
type SeriesGap = components["schemas"]["SeriesGap"];
const mediumLabel = { any: "books", ebook: "ebooks", audio: "audiobooks" };
const singularLabel = { any: "book", ebook: "ebook", audio: "audiobook" };

export default function SeriesContinuation() {
  const [medium, setMedium] = useState<Medium>("any");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["discovery", "series", medium, page],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/series", {
          params: { query: { medium, page, limit: 4 } },
        }),
      ),
    refetchInterval: 60_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  const items = query.data?.items || [];
  return (
    <section
      className="discovery-section"
      aria-labelledby="series-continuation-title"
    >
      <div className="page-heading discovery-heading series-gap-heading">
        <div>
          <h2 id="series-continuation-title">Continue your series</h2>
          <p className="muted">
            Published books missing from series in your library. Based on the
            Hardcover series catalogs you have loaded; most recently refreshed
            first.
          </p>
        </div>
        <label>
          Find missing
          <select
            value={medium}
            onChange={(event) => {
              setMedium(event.target.value as Medium);
              setPage(1);
            }}
          >
            <option value="any">Books in either format</option>
            <option value="ebook">Ebooks</option>
            <option value="audio">Audiobooks</option>
          </select>
        </label>
      </div>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry series shelf
        </button>
      )}
      {!query.error && query.data && (
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
          {(page > 1 || query.data.has_more) && (
            <div
              className="pagination discovery-pagination"
              aria-label="Series shelf pages"
            >
              <button
                disabled={page === 1 || query.isFetching}
                onClick={() => setPage(page - 1)}
              >
                Previous series page
              </button>
              <span className="muted" role="status">
                Page {page}
              </span>
              <button
                disabled={
                  !query.data.has_more || page >= 100 || query.isFetching
                }
                onClick={() => setPage(page + 1)}
              >
                Next series page
              </button>
            </div>
          )}
        </>
      )}
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
            <Link className="series-gap-book" to={`/books/${work.id}`}>
              <div className="series-gap-cover" aria-hidden="true">
                {work.cover_url ? (
                  <img src={work.cover_url} alt="" loading="lazy" />
                ) : (
                  <BookOpen size={22} />
                )}
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
            </Link>
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
