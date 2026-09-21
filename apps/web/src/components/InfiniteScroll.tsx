import { useEffect, useRef } from "react";

export default function InfiniteScroll({
  query,
}: {
  query: {
    hasNextPage: boolean;
    isFetching: boolean;
    isFetchNextPageError: boolean;
    fetchNextPage: () => Promise<unknown>;
  };
}) {
  const target = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } =
    query;
  useEffect(() => {
    if (!hasNextPage || isFetching || isFetchNextPageError) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          observer.disconnect();
          void fetchNextPage();
        }
      },
      { rootMargin: "0px 0px 160px 0px" },
    );
    if (target.current) observer.observe(target.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
  if (!hasNextPage) return null;
  return (
    <div ref={target} className="infinite-scroll" aria-live="polite">
      {isFetching ? (
        <span role="status">Loading more…</span>
      ) : (
        <button type="button" onClick={() => void fetchNextPage()}>
          {isFetchNextPageError ? "Retry loading more" : "Load more"}
        </button>
      )}
    </div>
  );
}
