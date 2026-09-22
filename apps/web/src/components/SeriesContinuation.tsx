import { usePagedQuery } from "../hooks/usePagedQuery";
import BookLink from "./BookLink";
import InfiniteScroll from "./InfiniteScroll";
import BookCover from "./BookCover";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BookOpen, Check, Headphones } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Medium = "any" | "ebook" | "audio";
type SeriesGap = components["schemas"]["SeriesGap"];
type SeriesGapShelf = components["schemas"]["SeriesGapShelf"];
const mediumLabel = { any: "books", ebook: "ebooks", audio: "audiobooks" };
const singularLabel = { any: "book", ebook: "ebook", audio: "audiobook" };

function emptyCopy(shelf: SeriesGapShelf, medium: Medium) {
  if (!shelf.hardcover_connected)
    return {
      title: `Connect Hardcover to find missing ${mediumLabel[medium]}.`,
      detail:
        "Suggestions use Hardcover links on books you already matched. Nothing is downloaded.",
      to: "/settings#catalog",
      label: "Metadata settings →",
    };
  if (!shelf.suggestions_enabled)
    return {
      title: `No missing ${mediumLabel[medium]} found in these loaded series.`,
      detail:
        "Open a book you own, follow its series link and load the catalog. New or refreshed series can then appear here. This shelf describes your library, not your reading progress.",
      to: "/",
      label: "Browse your catalog →",
    };
  if (!shelf.monitored_series)
    return {
      title: "No Hardcover series are linked to books you own yet.",
      detail:
        "Match a book to Hardcover first. Audiobookshelf series names are not used, and nothing is downloaded.",
      to: "/settings#catalog",
      label: "Metadata settings →",
    };
  return {
    title: `No missing ${mediumLabel[medium]} yet.`,
    detail:
      "Dewarr is checking series linked to books you own. Missing books appear here after each catalog loads.",
    to: "/discover/series",
    label: "See series gaps →",
  };
}

export default function SeriesContinuation({
  hideEmpty = false,
  variant = "shelf",
  canEdit = false,
}: {
  hideEmpty?: boolean;
  variant?: "shelf" | "page";
  canEdit?: boolean;
} = {}) {
  const client = useQueryClient();
  const [medium, setMedium] = useState<Medium>("any");
  const marked = useRef(false);
  const query = usePagedQuery({
    queryKey:
      variant === "page"
        ? ["series-gaps", medium]
        : ["discovery", "series", medium],
    queryFn: async (page, signal) =>
      result(
        await api.GET("/api/discovery/series", {
          signal,
          params: {
            query: {
              medium,
              page,
              limit: variant === "page" ? 8 : 4,
              full: variant === "page",
            },
          },
        }),
      ),
    refetchInterval: variant === "page" ? false : 60_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    next: (last, pages) =>
      last.has_more && pages.length < 100 ? pages.length + 1 : undefined,
  });
  const dismiss = useMutation({
    mutationFn: async (externalId: string) =>
      result(
        await api.POST("/api/discovery/series/{external_id}/dismiss", {
          params: { path: { external_id: externalId } },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["series-gaps"] });
      await client.invalidateQueries({ queryKey: ["discovery", "series"] });
    },
  });
  useEffect(() => {
    if (variant !== "page" || !query.data || marked.current) return;
    marked.current = true;
    void (async () => {
      try {
        result(await api.POST("/api/discovery/series/seen", { body: {} }));
        await client.invalidateQueries({ queryKey: ["discovery", "series"] });
      } catch {
        marked.current = false;
      }
    })();
  }, [variant, query.data, client]);
  const items = query.data?.items || [];
  const unseen = query.data?.unseen || 0;
  if (
    hideEmpty &&
    medium === "any" &&
    query.data &&
    !items.length &&
    !query.data.suggestions_enabled
  )
    return null;
  const Heading = variant === "page" ? "h1" : "h2";
  return (
    <section
      className="discovery-section"
      aria-labelledby="series-continuation-title"
    >
      <div className="page-heading discovery-heading series-gap-heading">
        <div>
          {variant === "page" && (
            <Link className="back-link" to="/discover">
              ← Discover
            </Link>
          )}
          <Heading id="series-continuation-title">
            Missing from your series
          </Heading>
          <p className="muted">
            Published books from Hardcover series linked to books you own.
            {unseen > 0
              ? ` ${unseen} new ${unseen === 1 ? "book" : "books"}.`
              : ""}
          </p>
        </div>
        <div className="shelf-controls">
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
      <Notice error={query.error || dismiss.error} />
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
                  canEdit={canEdit}
                  showActions={variant === "page"}
                  onIgnore={(externalId) => dismiss.mutate(externalId)}
                  ignoring={dismiss.isPending}
                />
              ))}
            </div>
          ) : (
            <Empty shelf={query.data} medium={medium} />
          )}
        </>
      )}
      {variant === "shelf" && items.length > 0 && (
        <Link className="back-link" to="/discover/series">
          See all missing books
          {unseen > 0 ? ` · ${unseen} new` : ""} →
        </Link>
      )}
      <InfiniteScroll query={query} />
    </section>
  );
}

function Empty({ shelf, medium }: { shelf: SeriesGapShelf; medium: Medium }) {
  const copy = emptyCopy(shelf, medium);
  return (
    <div className="panel">
      <p>{copy.title}</p>
      <p className="muted">{copy.detail}</p>
      <Link className="back-link" to={copy.to}>
        {copy.label}
      </Link>
    </div>
  );
}

function SeriesCard({
  series,
  medium,
  canEdit,
  showActions,
  onIgnore,
  ignoring,
}: {
  series: SeriesGap;
  medium: Medium;
  canEdit: boolean;
  showActions: boolean;
  onIgnore: (externalId: string) => void;
  ignoring: boolean;
}) {
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
          {series.unseen > 0 && <span className="series-gap-new">New</span>}
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
        {series.books.map(({ work, position, ambiguous_position, unseen }) => (
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
                  {unseen && " · New"}
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
        {showActions ? (
          <div className="series-gap-actions">
            {canEdit && (
              <Link
                to={`/series/hardcover/${encodeURIComponent(series.external_id)}?tab=requests&gaps=1&medium=${medium}`}
              >
                Request missing books
              </Link>
            )}
            <button
              type="button"
              disabled={ignoring}
              onClick={() => onIgnore(series.external_id)}
            >
              Ignore this series
            </button>
          </div>
        ) : (
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
        )}
      </footer>
    </article>
  );
}

export function SeriesGapPage({ canEdit }: { canEdit: boolean }) {
  return (
    <div className="explore">
      <SeriesContinuation variant="page" canEdit={canEdit} />
    </div>
  );
}
