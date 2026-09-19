import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { BookCard, Loading, Notice } from "../components";

type Provider = "all" | "hardcover" | "goodreads";
const providers = { hardcover: "Hardcover", goodreads: "Goodreads" };
const syncStates: Record<string, string> = {
  idle: "Scheduled observations enabled",
  queued: "Observation queued",
  running: "Observing list",
  failed: "Last observation failed — review the list",
};

export default function FollowedLists() {
  const [provider, setProvider] = useState<Provider>("all");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["discovery", "followed-lists", provider, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/followed-lists", {
          params: { query: { provider, offset, limit: 4 } },
        }),
      ),
    refetchInterval: 60_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  return (
    <section
      className="discovery-section"
      aria-labelledby="followed-lists-title"
    >
      <div className="page-heading discovery-heading series-gap-heading">
        <div>
          <h2 id="followed-lists-title">Your followed lists</h2>
          <p className="muted">
            Your saved Hardcover and Goodreads lists, most recently followed
            first. Book previews follow your local list order.
          </p>
        </div>
        <label>
          List source
          <select
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value as Provider);
              setOffset(0);
            }}
          >
            <option value="all">All sources</option>
            <option value="hardcover">Hardcover</option>
            <option value="goodreads">Goodreads</option>
          </select>
        </label>
      </div>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry followed lists
        </button>
      )}
      {!query.error && query.data && (
        <>
          {!query.data.items.length && (
            <div className="panel">
              <p>
                {offset
                  ? "No followed lists remain on this page. Try the previous page."
                  : "No followed lists from this source yet."}
              </p>
              <p className="muted">
                Follow a Hardcover community list, or open a local list to
                connect a Goodreads RSS shelf. Paused subscriptions stay here;
                detached subscriptions leave this shelf.
              </p>
            </div>
          )}
          <div className="series-gap-grid">
            {query.data.items.map((list) => (
              <article
                className="panel followed-list-card"
                key={list.id}
                aria-label={`${list.name} followed list`}
              >
                <header>
                  <p className="eyebrow">{providers[list.provider]}</p>
                  <h3>
                    <Link to={`/lists/${list.id}`}>{list.name}</Link>
                  </h3>
                  <p className="muted">
                    {list.count} {list.count === 1 ? "book" : "books"} ·{" "}
                    {list.owned} in your library
                  </p>
                  {list.provisional > 0 && (
                    <p className="muted">
                      {list.provisional}{" "}
                      {list.provisional === 1 ? "title needs" : "titles need"}{" "}
                      catalog matching
                    </p>
                  )}
                  {list.inventory_stale && (
                    <p className="series-gap-note">
                      Some counts use last known library availability.
                    </p>
                  )}
                  <p className="series-gap-note">
                    {list.enabled
                      ? syncStates[list.sync_state] ||
                        "Review observation status in the list"
                      : "List observations paused"}
                  </p>
                  <p className="series-gap-note">
                    {list.last_success_at ? (
                      <>
                        Last successful observation:{" "}
                        <time dateTime={list.last_success_at}>
                          {new Date(list.last_success_at).toLocaleString()}
                        </time>
                      </>
                    ) : (
                      "No successful observation yet"
                    )}
                  </p>
                </header>
                {list.books.length > 0 ? (
                  <ul
                    className="followed-list-books"
                    aria-label={`${list.name} book preview`}
                  >
                    {list.books.map((work) => (
                      <li key={work.id}>
                        <BookCard work={work} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">
                    No accessible saved books in this list yet.
                  </p>
                )}
                {list.provider === "goodreads" && (
                  <p className="series-gap-note">
                    RSS can show only part of a shelf. Saved books remain when
                    they disappear from the feed.
                  </p>
                )}
                <Link className="back-link" to={`/lists/${list.id}`}>
                  Open list · curate and review automation →
                </Link>
              </article>
            ))}
          </div>
          {(offset > 0 || query.data.total > 4) && (
            <div className="pagination" aria-label="Followed list pages">
              <button
                disabled={offset === 0 || query.isFetching}
                onClick={() => setOffset(Math.max(0, offset - 4))}
              >
                Previous followed lists
              </button>
              <span role="status">Page {Math.floor(offset / 4) + 1}</span>
              <button
                disabled={offset + 4 >= query.data.total || query.isFetching}
                onClick={() => setOffset(offset + 4)}
              >
                Next followed lists
              </button>
            </div>
          )}
        </>
      )}
      <p className="muted">
        Library counts include a confirmed ebook or audiobook. List observation
        and download automation are separate settings.
      </p>
      <div className="button-row">
        <Link className="back-link" to="/discover/lists">
          Find more community lists →
        </Link>
        <Link className="back-link" to="/lists">
          Manage your lists →
        </Link>
      </div>
    </section>
  );
}
