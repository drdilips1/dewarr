import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import DiscoveryShelf, {
  type DiscoveryItem,
} from "../components/DiscoveryShelf";
import { Preview } from "./ProviderSearch";
import SeriesContinuation from "../components/SeriesContinuation";

export default function Discover({ canEdit }: { canEdit: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const account = useQuery({
    queryKey: ["metadata-account"],
    queryFn: async () => result(await api.GET("/api/metadata/account")),
  });
  const local = useQuery({
    queryKey: ["discovery", "local"],
    queryFn: async () => result(await api.GET("/api/discovery/local")),
    refetchInterval: 60_000,
  });
  function preview(item: DiscoveryItem, button: HTMLButtonElement) {
    if (item.book.provider !== "hardcover" || !item.book.external_id) return;
    trigger.current = button;
    setSelected(item.book.external_id);
  }
  return (
    <>
      <div className="page-heading discovery-intro">
        <div>
          <p className="eyebrow">EXPLORE YOUR NEXT CHAPTER</p>
          <h1>Discover</h1>
          <p className="muted">
            Browse new books, revisit your shelves, and see what is already in
            your library.
          </p>
        </div>
        <div className="button-row">
          <Link className="back-link" to="/discover/lists">
            Explore community lists →
          </Link>
          <Link className="back-link" to="/search">
            Find a specific book →
          </Link>
        </div>
      </div>
      {selected && (
        <Preview
          key={selected}
          provider="hardcover"
          externalId={selected}
          canEdit={canEdit}
          onClose={() => {
            setSelected(null);
            trigger.current?.focus();
          }}
        />
      )}
      <Notice error={account.error} />
      {account.isPending && <Loading />}
      {account.data && !account.data.enabled && (
        <section className="panel" aria-label="Discover more books">
          <h2>Discover more with Hardcover</h2>
          <p className="muted">
            Connect your account for trending books, new releases and related
            titles. Your local shelves are ready below.
          </p>
          <Link className="back-link" to="/metadata">
            Connect Hardcover
          </Link>
        </section>
      )}
      {account.data?.enabled && (
        <>
          <section className="discovery-section" aria-label="Trending books">
            <ProviderShelf shelf="trending" onPreview={preview} />
          </section>
          <section
            className="discovery-section"
            aria-label="Recently published books"
          >
            <ProviderShelf shelf="new-releases" onPreview={preview} />
          </section>
        </>
      )}
      <SeriesContinuation />
      <section className="discovery-section" aria-label="Your catalog picks">
        <Notice error={local.error} />
        {local.isPending && <Loading />}
        {local.data && (
          <DiscoveryShelf shelf={local.data} onPreview={preview} />
        )}
        <Link className="back-link" to="/">
          View your catalog →
        </Link>
      </section>
    </>
  );
}

function ProviderShelf({
  shelf,
  onPreview,
}: {
  shelf: "trending" | "new-releases";
  onPreview: (item: DiscoveryItem, button: HTMLButtonElement) => void;
}) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["discovery", shelf, page],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/hardcover/{shelf}", {
          params: { path: { shelf }, query: { page } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "not-connected"
        ? false
        : Math.max(60_000, (query.state.data?.retry_after || 0) * 1_000),
    retry: false,
  });
  return (
    <>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.data && (
        <DiscoveryShelf shelf={query.data} onPreview={onPreview} />
      )}
      {(query.error || query.data?.status === "unavailable") && (
        <button disabled={query.isFetching} onClick={() => query.refetch()}>
          Retry shelf
        </button>
      )}
      {(page > 1 || query.data?.has_more) && (
        <div
          className="pagination discovery-pagination"
          aria-label={`${shelf} pages`}
        >
          <button
            disabled={page === 1 || query.isFetching}
            onClick={() => setPage(page - 1)}
          >
            Previous shelf page
          </button>
          <span className="muted" role="status">
            Page {page}
          </span>
          <button
            disabled={!query.data?.has_more || page >= 25 || query.isFetching}
            onClick={() => setPage(page + 1)}
          >
            Next shelf page
          </button>
        </div>
      )}
    </>
  );
}
