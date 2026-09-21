import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "./InfiniteScroll";
import { useState } from "react";
import { ArrowLeft, ArrowUpRight, UserRound } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { BookCard, Empty, Loading, Notice } from "../components";
import BookCover from "./BookCover";
import { useReaderDetails } from "./BookReaderDetails";

type Kind = "authors" | "series";
type Library = components["schemas"]["LibraryView"];
export default function LibraryGroups({
  kind,
  libraries,
}: {
  kind: Kind;
  libraries: Library[];
}) {
  const [params, setParams] = useSearchParams();
  const group = params.get("group") || "";
  const q = (params.get("q") || "").slice(0, 300);
  const rawLibrary = params.get("library") || "";
  const libraryId =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      rawLibrary,
    )
      ? rawLibrary
      : undefined;
  const medium =
    params.get("medium") === "ebook"
      ? "ebook"
      : params.get("medium") === "audio"
        ? "audio"
        : "any";
  const rawOffset = Number(params.get("offset"));
  const offset =
    Number.isSafeInteger(rawOffset) && rawOffset > 0 ? rawOffset : 0;
  const title = kind === "authors" ? "Authors" : "Series";
  const query = usePagedQuery({
    queryKey: ["library-groups", kind, q, medium, libraryId],
    initial: 0,
    enabled: !group,
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/library/groups/{kind}", {
          signal,
          params: {
            path: { kind },
            query: { q, medium, library_id: libraryId, offset, limit: 24 },
          },
        }),
      ),
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const books = usePagedQuery({
    queryKey: ["library-group-books", kind, group, medium, libraryId],
    initial: 0,
    enabled: !!group,
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/library/groups/{kind}/books", {
          signal,
          params: {
            path: { kind },
            query: {
              name: group,
              medium,
              library_id: libraryId,
              offset,
              limit: 40,
            },
          },
        }),
      ),
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const active = group ? books : query;
  const total = active.data?.total || 0;
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  };
  const back = new URLSearchParams(params);
  back.delete("group");
  back.delete("offset");
  return (
    <section className="library-group-shelf" aria-label={`Library ${kind}`}>
      {group && (
        <Link className="back-link" to={`?${back}`}>
          <ArrowLeft size={16} /> All {kind}
        </Link>
      )}
      <div className="section-heading">
        <div>
          <h2>{group || `${title} in your collection`}</h2>
          <p className="muted">
            {group
              ? `Books ${kind === "authors" ? "by this author" : "in this series"} in your libraries.`
              : kind === "authors"
                ? "Explore the writers on your shelves."
                : "See the stories you’re collecting, one series at a time."}
          </p>
        </div>
        {active.data && !active.error && (
          <span className="count">
            {total}{" "}
            {group
              ? total === 1
                ? "book"
                : "books"
              : kind === "authors" && total === 1
                ? "author"
                : kind}
          </span>
        )}
      </div>
      {!group && (
        <form
          className="library-search"
          onSubmit={(event) => {
            event.preventDefault();
            change(
              "q",
              String(new FormData(event.currentTarget).get("q") || "").trim(),
            );
          }}
        >
          <label>
            Search {kind}
            <input
              key={`${kind}:${q}`}
              name="q"
              type="search"
              defaultValue={q}
              maxLength={300}
              placeholder={kind === "authors" ? "Author name" : "Series name"}
            />
          </label>
          <button>Search {kind}</button>
        </form>
      )}
      <div className="library-filters library-shelf-filters">
        <label>
          Media
          <select
            value={medium}
            onChange={(event) => change("medium", event.target.value)}
          >
            <option value="any">Ebooks and audiobooks</option>
            <option value="ebook">Ebooks</option>
            <option value="audio">Audiobooks</option>
          </select>
        </label>
        <label>
          Library
          <select
            value={libraryId || ""}
            onChange={(event) => change("library", event.target.value)}
          >
            <option value="">All accessible libraries</option>
            {libraries.map((library) => (
              <option key={library.id} value={library.id}>
                {library.name}
              </option>
            ))}
          </select>
        </label>
        {(q || medium !== "any" || libraryId) && (
          <button
            type="button"
            onClick={() =>
              setParams({ view: kind, ...(group ? { group } : {}) })
            }
          >
            Clear filters
          </button>
        )}
      </div>
      <Notice error={active.error} />
      {active.isPending && <Loading />}
      {active.error && (
        <button onClick={() => active.refetch()} disabled={active.isFetching}>
          Retry {kind}
        </button>
      )}
      {!active.error && active.data && (
        <>
          {group ? (
            <div className="book-grid">
              {books.data?.items.map((work) => (
                <BookCard key={work.id} work={work} medium={medium} />
              ))}
            </div>
          ) : (
            <div className="library-group-grid">
              {query.data?.items.map((item) => {
                const next = new URLSearchParams(params);
                next.set("group", item.name);
                next.delete("offset");
                return (
                  <article className="library-group-card" key={item.key}>
                    <Link
                      to={`?${next}`}
                      className="library-group-link"
                      aria-label={`${item.name}, ${item.book_count} ${item.book_count === 1 ? "book" : "books"} in your collection`}
                    >
                      <div className="library-group-art" aria-hidden="true">
                        <GroupPortrait key={item.key} item={item} kind={kind} />
                        <div className="library-group-covers">
                          {item.books.map((work) => (
                            <BookCover
                              actions={false}
                              key={work.id}
                              title={work.title}
                              work={work}
                              medium="ebook"
                            />
                          ))}
                        </div>
                      </div>
                      <div className="library-group-caption">
                        <div>
                          <h3>{item.name}</h3>
                          <p>
                            {item.book_count}{" "}
                            {item.book_count === 1 ? "book" : "books"} in your
                            collection
                          </p>
                        </div>
                        <ArrowUpRight size={18} aria-hidden="true" />
                      </div>
                    </Link>
                    {kind === "series" && item.external_id && (
                      <Link
                        className="library-group-profile"
                        to={`/series/hardcover/${encodeURIComponent(item.external_id)}`}
                      >
                        Explore full series →
                      </Link>
                    )}
                  </article>
                );
              })}
            </div>
          )}
          {!active.data.items.length && (
            <Empty
              title={group ? "No books match this view" : `No ${kind} to show`}
            >
              {q || medium !== "any" || libraryId || offset
                ? "Try clearing the filters."
                : kind === "series"
                  ? "Series appear when books in your libraries have series metadata. You can check a book’s metadata from its detail page."
                  : "Authors appear here when matched books are available in your libraries."}
            </Empty>
          )}
          <InfiniteScroll query={active} />
        </>
      )}
    </section>
  );
}

function GroupPortrait({
  item,
  kind,
}: {
  item: components["schemas"]["LibraryGroup"];
  kind: Kind;
}) {
  const query = useReaderDetails(item.hardcover_book_id || undefined);
  const [failed, setFailed] = useState<string>();
  const normalize = (name: string) =>
    name.trim().replace(/\s+/g, " ").toLowerCase();
  const authors = query.data?.authors || [];
  const author =
    kind === "authors"
      ? authors.find(
          (author) => normalize(author.name) === normalize(item.name),
        )
      : authors.find((author) => author.image_url) || authors[0];
  const src = author?.image_url;
  return (
    <span className="library-group-portrait">
      {src && src !== failed ? (
        <img
          src={src}
          alt={author.name}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(src)}
        />
      ) : (
        <UserRound size={32} />
      )}
    </span>
  );
}
