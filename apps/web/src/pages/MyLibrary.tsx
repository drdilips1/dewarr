import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";

type Asset = components["schemas"]["AssetView"];
export default function MyLibrary({ admin }: { admin: boolean }) {
  const [libraryId, setLibraryId] = useState("");
  const [review, setReview] = useState(false);
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
      <div className="library-filters">
        <label>
          Library
          <select
            value={libraryId}
            onChange={(event) => setLibraryId(event.target.value)}
          >
            <option value="">All accessible libraries</option>
            {libraries.data?.map((library) => (
              <option key={library.id} value={library.id}>
                {library.name}
              </option>
            ))}
          </select>
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={review}
            onChange={(event) => setReview(event.target.checked)}
          />
          Needs matching
        </label>
      </div>
      <LibraryAssets
        key={libraryId + review}
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
}: {
  workId?: string;
  libraryId?: string;
  review?: boolean;
  admin?: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const [matching, setMatching] = useState<Asset | null>(null);
  const assets = useQuery({
    queryKey: ["assets", workId, libraryId, review, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/library/assets", {
          params: {
            query: {
              work_id: workId,
              library_id: libraryId || undefined,
              needs_review: review,
              offset,
              limit: 40,
            },
          },
        }),
      ),
    refetchInterval: 15000,
  });
  return (
    <section aria-label="Library copies">
      <Notice error={assets.error} />
      {matching && (
        <MatchForm asset={matching} close={() => setMatching(null)} />
      )}
      {assets.isPending ? (
        <Loading />
      ) : assets.data?.items.length ? (
        <div className="activity-list">
          {assets.data.items.map((asset) => (
            <article className="activity-row library-copy" key={asset.id}>
              <div className="grow">
                <h2>
                  {asset.work_ids.length === 1 ? (
                    <Link to={`/books/${asset.work_ids[0]}`}>
                      {asset.title}
                    </Link>
                  ) : (
                    asset.title
                  )}
                </h2>
                <p>
                  {asset.medium === "audio" ? "Audiobook" : "Ebook"}
                  {asset.narrators.length
                    ? ` · ${asset.narrators.join(", ")}`
                    : ""}{" "}
                  ·{" "}
                  {asset.formats
                    .map((format) => format.toUpperCase())
                    .join(" / ")}
                </p>
                <p className="muted">
                  {asset.library_name} ·{" "}
                  {asset.full_content
                    ? "Full book"
                    : "Supplementary or needs verification"}
                </p>
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
                    <button onClick={() => setMatching(asset)}>
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
            {review
              ? "No items need matching in this view."
              : "A completed library sync brings accessible books and recordings here."}
          </Empty>
        )
      )}
      {assets.data && assets.data.total > 40 && (
        <div className="pagination">
          <button
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 40))}
          >
            Previous
          </button>
          <span>
            {offset + 1}–{Math.min(offset + 40, assets.data.total)} of{" "}
            {assets.data.total}
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
          body: { work_id: id },
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
    </form>
  );
}
