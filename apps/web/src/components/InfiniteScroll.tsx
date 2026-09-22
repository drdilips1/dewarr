import { useEffect, useRef } from "react";

export default function InfiniteScroll({
  query,
  manual = false,
}: {
  query: {
    hasNextPage: boolean;
    isFetching: boolean;
    isFetchNextPageError: boolean;
    fetchNextPage: () => Promise<unknown>;
  };
  manual?: boolean;
}) {
  const target = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } =
    query;
  useEffect(() => {
    if (manual || !hasNextPage || isFetching || isFetchNextPageError) return;
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
  }, [manual, hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
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
