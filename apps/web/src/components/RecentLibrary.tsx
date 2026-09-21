import { usePagedQuery } from "../hooks/usePagedQuery";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import ShelfPagination from "./ShelfPagination";
import DiscoveryShelf from "./DiscoveryShelf";

type Medium = "any" | "ebook" | "audio";

export default function RecentLibrary({
  hideEmpty = false,
}: { hideEmpty?: boolean } = {}) {
  const [medium, setMedium] = useState<Medium>("any");
  const query = usePagedQuery({
    queryKey: ["discovery", "library", medium],
    queryFn: async (page, signal) =>
      result(
        await api.GET("/api/discovery/library", {
          signal,
          params: { query: { medium, page, limit: 12 } },
        }),
      ),
    refetchInterval: 60_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    next: (last, pages) =>
      last.has_more && pages.length < 100 ? pages.length + 1 : undefined,
  });
  if (hideEmpty && medium === "any" && query.data && !query.data.items?.length)
    return null;
  return (
    <section
      className="discovery-section"
      aria-label="Recent library additions"
    >
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry library shelf
        </button>
      )}
      <DiscoveryShelf
        shelf={
          query.data || {
            title: "Recent library additions",
            attribution: "Your library",
            status: "unavailable",
            page: 1,
            has_more: false,
            stale: false,
            items: [],
          }
        }
        medium={medium}
        controls={
          <div className="shelf-controls">
            <label className="shelf-filter">
              <span className="sr-only">Show library additions</span>
              <select
                value={medium}
                onChange={(event) => {
                  setMedium(event.target.value as Medium);
                }}
              >
                <option value="any">Ebooks and audiobooks</option>
                <option value="ebook">Ebooks</option>
                <option value="audio">Audiobooks</option>
              </select>
            </label>
            <ShelfPagination
              page={1}
              hasMore={query.hasNextPage}
              busy={query.isFetching}
              onPage={() => {}}
              infinite={{
                fetchNextPage: query.fetchNextPage,
                isFetchNextPageError: query.isFetchNextPageError,
                count: query.data?.items?.length || 0,
              }}
              label="library"
            />
          </div>
        }
      />
      {!query.error && query.data && (
        <>
          {!query.data.items?.length && (
            <p className="muted">
              Sync a library and resolve unmatched items to bring books into
              this view. Try the other format if your library is already synced.
            </p>
          )}
        </>
      )}
      <Link className="back-link" to="/library">
        View your library →
      </Link>
    </section>
  );
}
