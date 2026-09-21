import BookLink from "./BookLink";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { api, result } from "../api/client";
import { BookCard, Loading, Notice } from "../components";
import BookCover from "./BookCover";
import type { Entry } from "./DiscoveryCollections";

// Resolve only visible cards, with bounded concurrency. Provider responses are
// also cached server-side under the reader's Hardcover connection generation.
let active = 0;
const waiting: (() => void)[] = [];
async function resolve(id: string, signal: AbortSignal) {
  if (active >= 2) await new Promise<void>((done) => waiting.push(done));
  else active++;
  try {
    signal.throwIfAborted();
    return result(
      await api.GET("/api/discovery/goodreads/{external_id}", {
        params: { path: { external_id: id } },
        signal,
      }),
    );
  } finally {
    const next = waiting.shift();
    if (next) next();
    else active--;
  }
}
export function useGoodreadsBook(id: string, enabled = true) {
  return useQuery({
    queryKey: ["goodreads-discovery-book", id],
    queryFn: ({ signal }) => resolve(id, signal),
    enabled,
    staleTime: (query) =>
      query.state.data?.match.status === "disabled" ? 0 : 30 * 60_000,
    retry: false,
  });
}
export function GoodreadsCard({ book }: { book: Entry }) {
  const node = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const account = useQuery({
    queryKey: ["metadata-account"],
    queryFn: async () => result(await api.GET("/api/metadata/account")),
  });
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    });
    if (node.current) observer.observe(node.current);
    return () => observer.disconnect();
  }, []);
  const resolved = useGoodreadsBook(
    book.external_id,
    visible && !!account.data?.enabled,
  );
  const match = resolved.data?.match.book;
  const work = resolved.data?.entry.work || book.work;
  const cover = match?.cover_url || book.cover_url;
  return (
    <div ref={node}>
      {work ? (
        <BookCard
          work={
            match?.cover_url ? { ...work, cover_url: match.cover_url } : work
          }
          rating={match?.rating ?? book.rating}
          cover={cover}
        />
      ) : (
        <BookLink
          className="book-card discovery-book"
          state={{ goodreads: book }}
          aria-label={`View ${book.title}`}
          to={
            match
              ? `/discover/books/hardcover/${match.external_id}`
              : `/discover/books/goodreads/${book.external_id}`
          }
        >
          <BookCover
            title={match?.title || book.title}
            rating={match?.rating ?? book.rating}
            cover={cover}
            providerBook={{
              provider: match ? "hardcover" : "goodreads",
              external_id: match?.external_id || book.external_id,
            }}
          />
          <h3 title={book.title}>{match?.title || book.title}</h3>
          <p title={(book.authors || []).join(", ")}>
            {(match?.authors || book.authors || []).join(", ")}
          </p>
        </BookLink>
      )}
    </div>
  );
}

export default function GoodreadsBook() {
  const { externalId = "" } = useParams();
  const query = useGoodreadsBook(externalId);
  const location = useLocation();
  const fallback = location.state?.goodreads as Entry | undefined;
  const value =
    query.data ||
    (query.error && fallback?.external_id === externalId
      ? {
          entry: fallback,
          match: {
            book: null,
            candidates: [],
            status: "unavailable",
            reason: "Hardcover details are temporarily unavailable.",
          },
        }
      : undefined);
  if (value?.entry.work)
    return <Navigate replace to={`/books/${value.entry.work.id}`} />;
  if (value?.match.book)
    return (
      <Navigate
        replace
        to={`/discover/books/hardcover/${value.match.book.external_id}`}
      />
    );
  return (
    <article className="reader-page">
      <Link className="back-link" to="/discover">
        <ArrowLeft size={16} /> Back to Discover
      </Link>
      <Notice error={query.error} />
      {query.isPending && (
        <>
          <Loading />
          <p role="status">Finding book details on Hardcover…</p>
        </>
      )}
      {query.error && (
        <button onClick={() => query.refetch()}>Retry book details</button>
      )}
      {value && (
        <>
          <div className="explore-book-preview">
            <BookCover
              actions={false}
              title={value.entry.title}
              providerBook={{ provider: "goodreads", external_id: externalId }}
              cover={value.entry.cover_url}
            />
            <div>
              <h1>{value.entry.title}</h1>
              <p>{(value.entry.authors || []).join(", ")}</p>
              <p>{value.match.reason}</p>
              <div className="button-row">
                {value.match.status === "disabled" && (
                  <Link className="primary" to="/settings#reading">
                    Connect Hardcover
                  </Link>
                )}
                <Link
                  className="primary"
                  to={`/search?q=${encodeURIComponent(`${value.entry.title} ${value.entry.authors?.[0] || ""}`)}`}
                >
                  Find editions
                </Link>
                <a
                  className="back-link"
                  href={`https://www.goodreads.com/book/show/${externalId}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Goodreads <ExternalLink size={14} />
                </a>
              </div>
            </div>
          </div>
          {!!value.match.candidates?.length && (
            <section>
              <h2>Choose the right book</h2>
              <ul className="explore-books">
                {value.match.candidates?.map((book) => (
                  <li key={book.external_id}>
                    <BookLink
                      aria-label={`View ${book.title}`}
                      className="book-card"
                      to={`/discover/books/hardcover/${book.external_id}`}
                    >
                      <BookCover
                        title={book.title}
                        cover={book.cover_url}
                        providerBook={{
                          provider: "hardcover",
                          external_id: book.external_id,
                        }}
                      />
                      <h3>{book.title}</h3>
                      <p>{(book.authors || []).join(", ")}</p>
                    </BookLink>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </article>
  );
}
