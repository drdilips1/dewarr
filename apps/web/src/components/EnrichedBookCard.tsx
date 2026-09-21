import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result, type Work } from "../api/client";
import { BookCard } from "../components";

// Shelf pages can contain hundreds of books. Only resolve visible cards, and
// share the result with the book detail page without importing a catalog match.
let active = 0;
const waiting: (() => void)[] = [];
async function resolve(workId: string, signal: AbortSignal) {
  if (active >= 2) await new Promise<void>((done) => waiting.push(done));
  else active++;
  try {
    signal.throwIfAborted();
    return result(
      await api.GET("/api/metadata/works/{work_id}/reader-match", {
        params: { path: { work_id: workId } },
        signal,
      }),
    );
  } finally {
    const next = waiting.shift();
    if (next) next();
    else active--;
  }
}

export default function EnrichedBookCard({ work }: { work: Work }) {
  const node = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const needsMetadata = work.provisional || !work.cover_url;
  const account = useQuery({
    queryKey: ["metadata-account"],
    queryFn: async () => result(await api.GET("/api/metadata/account")),
    enabled: needsMetadata,
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
  const match = useQuery({
    queryKey: ["work-reader-match", work.id],
    queryFn: ({ signal }) => resolve(work.id, signal),
    enabled: visible && needsMetadata && !!account.data?.enabled,
    staleTime: 300_000,
    retry: false,
  });
  const book = account.data?.enabled ? match.data?.book : undefined;
  return (
    <div ref={node}>
      <BookCard
        work={
          book
            ? {
                ...work,
                title: book.title,
                authors: book.authors?.length ? book.authors : work.authors,
                description: book.description || work.description,
                cover_url: work.cover_url || book.cover_url || null,
              }
            : work
        }
      />
    </div>
  );
}
