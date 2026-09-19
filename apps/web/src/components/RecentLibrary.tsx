import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import DiscoveryShelf from "./DiscoveryShelf";

type Medium = "any" | "ebook" | "audio";

export default function RecentLibrary() {
  const [medium, setMedium] = useState<Medium>("any");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["discovery", "library", medium, page],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/library", {
          params: { query: { medium, page, limit: 12 } },
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
      aria-label="Recent library additions"
    >
      <label>
        Show library additions
        <select
          value={medium}
          onChange={(event) => {
            setMedium(event.target.value as Medium);
            setPage(1);
          }}
        >
          <option value="any">Ebooks and audiobooks</option>
          <option value="ebook">Ebooks</option>
          <option value="audio">Audiobooks</option>
        </select>
      </label>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry library shelf
        </button>
      )}
      {!query.error && query.data && (
        <>
          <DiscoveryShelf
            shelf={{
              ...query.data,
              items: (query.data.items || []).map((item) => ({
                ...item,
                reason: `Library copy first observed ${new Date(item.observed_at).toLocaleDateString()}`,
              })),
            }}
            onPreview={() => {}}
          />
          <p className="muted">
            Complete books confirmed in your connected libraries. Initial sync
            can bring older books here; these dates are not publication or
            download dates. A newly observed version can bring a title back to
            this shelf.
          </p>
          {!query.data.items?.length && (
            <p className="muted">
              Sync a library and resolve unmatched items to bring books into
              this view. Try the other format if your library is already synced.
            </p>
          )}
          {(page > 1 || query.data.has_more) && (
            <div className="pagination" aria-label="Library shelf pages">
              <button
                disabled={page === 1 || query.isFetching}
                onClick={() => setPage(page - 1)}
              >
                Previous library page
              </button>
              <span role="status">Page {page}</span>
              <button
                disabled={
                  !query.data.has_more || page >= 100 || query.isFetching
                }
                onClick={() => setPage(page + 1)}
              >
                Next library page
              </button>
            </div>
          )}
        </>
      )}
      <Link className="back-link" to="/library">
        View your library →
      </Link>
    </section>
  );
}
