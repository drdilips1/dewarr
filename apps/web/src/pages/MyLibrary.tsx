import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";
import IdentityHistory from "./IdentityHistory";
import CollectionContents from "./CollectionContents";

type Asset = components["schemas"]["AssetView"];
type Medium = "any" | "ebook" | "audio";
type AssetState =
  | "any"
  | "present"
  | "stale"
  | "missing-suspected"
  | "missing-confirmed"
  | "scope-unavailable"
  | "moved";
type AssetSort = "title" | "recent";
const states: Record<AssetState, string> = {
  any: "All inventory states",
  present: "Present",
  stale: "Last known availability",
  "missing-suspected": "Checking availability",
  "missing-confirmed": "Missing",
  "scope-unavailable": "Access changed",
  moved: "Moved",
};
export default function MyLibrary({ admin }: { admin: boolean }) {
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") || "").slice(0, 300);
  const rawLibrary = params.get("library") || "";
  const libraryId =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      rawLibrary,
    )
      ? rawLibrary
      : "";
  const review = params.get("review") === "true";
  const medium: Medium =
    params.get("medium") === "ebook"
      ? "ebook"
      : params.get("medium") === "audio"
        ? "audio"
        : "any";
  const rawState = params.get("state") || "any";
  const state: AssetState = Object.hasOwn(states, rawState)
    ? (rawState as AssetState)
    : "any";
  const sort: AssetSort = params.get("sort") === "recent" ? "recent" : "title";
  const rawOffset = Number(params.get("offset") || 0);
  const offset =
    Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  }
  const filtered = !!(
    q ||
    libraryId ||
    review ||
    medium !== "any" ||
    state !== "any"
  );
  const libraries = useQuery({
    queryKey: ["libraries"],
    refetchOnMount: "always",
    queryFn: async () => result(await api.GET("/api/library/libraries")),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">READY TO READ AND LISTEN</p>
          <h1>My Library</h1>
          <p className="muted">
            Books and recordings observed in your connected libraries.
          </p>
        </div>
        {admin && <Link to="/connections">Manage connections</Link>}
      </div>
      <Notice error={libraries.error} />
      <form
        className="library-search"
        aria-label="Search library copies"
        onSubmit={(event) => {
          event.preventDefault();
          change(
            "q",
            String(new FormData(event.currentTarget).get("q") || "").trim(),
          );
        }}
      >
        <label>
          Search your library
          <input
            key={q}
            name="q"
            defaultValue={q}
            maxLength={300}
            type="search"
            placeholder="Title, author or narrator"
          />
        </label>
        <button type="submit">Search library</button>
      </form>
      <div className="library-filters">
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
            value={libraryId}
            onChange={(event) => change("library", event.target.value)}
          >
            <option value="">All accessible libraries</option>
            {libraries.data?.map((library) => (
              <option key={library.id} value={library.id}>
                {library.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Inventory state
          <select
            value={state}
            onChange={(event) => change("state", event.target.value)}
          >
            {Object.entries(states).map(([key, title]) => (
              <option key={key} value={key}>
                {title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sort copies
          <select
            value={sort}
            onChange={(event) => change("sort", event.target.value)}
          >
            <option value="title">Title</option>
            <option value="recent">Recently observed</option>
          </select>
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={review}
            onChange={(event) =>
              change("review", event.target.checked ? "true" : "")
            }
          />
          Needs matching
        </label>
      </div>
      {(filtered || sort !== "title" || offset > 0) && (
        <button type="button" onClick={() => setParams({})}>
          Reset library view
        </button>
      )}
      {sort === "recent" && (
        <p className="muted">
          Newest first observed by this app. Initial sync includes older books;
          repeated syncs do not reset this order.
        </p>
      )}
      <LibraryAssets
        key={JSON.stringify([libraryId, review, q, medium, state, sort])}
        q={q}
        medium={medium}
        state={state}
        sort={sort}
        filtered={filtered}
        pageOffset={offset}
        onPageChange={(value) => change("offset", value ? String(value) : "")}
        admin={admin}
        libraryId={libraryId}
        review={review}
      />
    </>
  );
}

export function LibraryAssets({
  workId,
  libraryId,
  review = false,
  admin = false,
  q = "",
  medium = "any",
  state = "any",
  sort = "title",
  filtered = false,
  pageOffset,
  onPageChange,
}: {
  workId?: string;
  libraryId?: string;
  review?: boolean;
  admin?: boolean;
  q?: string;
  medium?: Medium;
  state?: AssetState;
  sort?: AssetSort;
  filtered?: boolean;
  pageOffset?: number;
  onPageChange?: (value: number) => void;
}) {
  const [localOffset, setLocalOffset] = useState(0);
  const offset = pageOffset ?? localOffset;
  const setOffset = onPageChange ?? setLocalOffset;
  const [matching, setMatching] = useState<Asset | null>(null);
  const [collection, setCollection] = useState<Asset | null>(null);
  const assets = useQuery({
    queryKey: [
      "assets",
      workId,
      libraryId,
      review,
      q,
      medium,
      state,
      sort,
      offset,
    ],
    queryFn: async () =>
      result(
        await api.GET("/api/library/assets", {
          params: {
            query: {
              work_id: workId,
              library_id: libraryId || undefined,
              needs_review: review,
              q,
              medium,
              state,
              sort,
              offset,
              limit: 40,
            },
          },
        }),
      ),
    refetchInterval: 15000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  return (
    <section aria-label="Library copies">
      <Notice error={assets.error} />
      {assets.error && (
        <button disabled={assets.isFetching} onClick={() => assets.refetch()}>
          Retry library copies
        </button>
      )}
      {!assets.error && assets.data && (
        <p className="muted" role="status">
          {assets.data.total}{" "}
          {assets.data.total === 1 ? "library copy" : "library copies"}
          {filtered
            ? assets.data.total === 1
              ? " matches this view"
              : " match this view"
            : ""}
        </p>
      )}
      {!assets.error && matching && (
        <MatchForm asset={matching} close={() => setMatching(null)} />
      )}
      {!assets.error && collection && (
        <CollectionContents
          asset={collection}
          close={() => setCollection(null)}
        />
      )}
      {assets.isPending ? (
        <Loading />
      ) : !assets.error && assets.data?.items.length ? (
        <div className="activity-list">
          {assets.data.items.map((asset) => (
            <article className="activity-row library-copy" key={asset.id}>
              <div className="grow">
                <h2>
                  {asset.collection_work_id || asset.work_ids.length === 1 ? (
                    <Link
                      to={`/books/${asset.collection_work_id || asset.work_ids[0]}`}
                    >
                      {asset.title}
                    </Link>
                  ) : (
                    asset.title
                  )}
                </h2>
                {!!asset.authors?.length && (
                  <p className="muted">{asset.authors.join(", ")}</p>
                )}
                <p>
                  {asset.medium === "audio" ? "Audiobook" : "Ebook"}
                  {asset.narrators.length
                    ? ` · ${asset.collection ? "Collection narrators: " : ""}${asset.narrators.join(", ")}`
                    : ""}{" "}
                  ·{" "}
                  {asset.formats
                    .map((format) => format.toUpperCase())
                    .join(" / ")}
                </p>
                <p className="muted">
                  {asset.library_name} ·{" "}
                  {asset.full_content
                    ? asset.collection
                      ? "In collection · Verified complete books"
                      : "Full book"
                    : "Supplementary or needs verification"}
                </p>
                {asset.collection && (
                  <ul aria-label="Collection contents">
                    {asset.contents?.map((book) => (
                      <li key={book.work_id}>
                        <Link to={`/books/${book.work_id}`}>{book.title}</Link>
                        {!book.verified && " · Needs verification"}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="activity-meta">
                <span className="status">
                  {(
                    {
                      present: "Available",
                      stale: "Last known availability",
                      "missing-suspected": "Checking availability",
                      "missing-confirmed": "Missing",
                      "scope-unavailable": "Access changed",
                      moved: "Moved",
                    } as Record<string, string>
                  )[asset.state] || asset.state.replaceAll("-", " ")}
                </span>
                {asset.match_status === "needs-review" && (
                  <span className="status">Needs matching</span>
                )}
                <div className="button-row">
                  <a href={asset.open_url} target="_blank" rel="noreferrer">
                    Open in Audiobookshelf
                  </a>
                  {admin && (
                    <button
                      onClick={() => {
                        setMatching(null);
                        setCollection(asset);
                      }}
                    >
                      Review collection contents
                    </button>
                  )}
                  {admin && (
                    <button
                      onClick={() => {
                        setCollection(null);
                        setMatching(asset);
                      }}
                    >
                      Correct match
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        !assets.isError && (
          <Empty title="No library copies to show">
            {offset > 0
              ? "This page is empty. Return to an earlier page or reset the library view."
              : filtered
                ? "No copies match these filters. Try another title, author, narrator or media type."
                : review
                  ? "No items need matching in this view."
                  : "A completed library sync brings accessible books and recordings here."}
          </Empty>
        )
      )}
      {!assets.error &&
        assets.data &&
        (assets.data.total > 40 || offset > 0) && (
          <div className="pagination">
            <button
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 40))}
            >
              Previous
            </button>
            <span>
              {assets.data.items.length
                ? `${offset + 1}–${offset + assets.data.items.length} of ${assets.data.total}`
                : `0 copies on this page · ${assets.data.total} total`}
            </span>
            <button
              disabled={offset + 40 >= assets.data.total}
              onClick={() => setOffset(offset + 40)}
            >
              Next
            </button>
          </div>
        )}
    </section>
  );
}

function MatchForm({ asset, close }: { asset: Asset; close: () => void }) {
  const cache = useQueryClient();
  const [search, setSearch] = useState(asset.title);
  const [workId, setWorkId] = useState(asset.work_ids[0] || "");
  const works = useQuery({
    queryKey: ["match-search", search],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q: search, limit: 100 } },
        }),
      ),
    enabled: search.trim().length > 1,
  });
  const match = useMutation({
    mutationFn: async (id: string | null) =>
      result(
        await api.POST("/api/library/assets/{asset_id}/match", {
          params: { path: { asset_id: asset.id } },
          body: { work_id: id, expected_revision: asset.match_revision },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries();
      close();
    },
  });
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        match.mutate(workId);
      }}
    >
      <h2>Match {asset.title}</h2>
      <p className="muted">
        Your correction is preserved during future syncs. Confirming a match
        also accepts the current edition or recording details.
      </p>
      <Notice error={works.error || match.error} />
      {asset.work_ids.length > 1 && (
        <p className="notice">
          This replaces all current book associations for this library item. The
          correction history can restore them.
        </p>
      )}
      <label>
        Search catalog
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setWorkId("");
          }}
        />
      </label>
      <label>
        Book
        <select
          value={workId}
          onChange={(event) => setWorkId(event.target.value)}
          required
        >
          <option value="">Choose the correct book</option>
          {works.data?.items.map((work) => (
            <option key={work.id} value={work.id}>
              {work.title} — {work.authors.join(", ") || "Unknown author"}
            </option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button className="primary" disabled={!workId || match.isPending}>
          Confirm match
        </button>
        <button
          type="button"
          disabled={match.isPending}
          onClick={() => match.mutate(null)}
        >
          Leave unmatched
        </button>
        <button type="button" onClick={close}>
          Cancel
        </button>
      </div>
      <IdentityHistory entityId={asset.id} onChanged={close} />
    </form>
  );
}
