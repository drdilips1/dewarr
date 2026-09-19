import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import { Preview } from "../pages/ProviderSearch";
import DiscoveryShelf from "./DiscoveryShelf";

export default function RelatedBooks({
  workId,
  canEdit,
}: {
  workId: string;
  canEdit: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const query = useQuery({
    queryKey: ["discovery", "related", workId],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/related/{work_id}", {
          params: { path: { work_id: workId } },
        }),
      ),
    refetchInterval: (query) =>
      Math.max(60_000, (query.state.data?.retry_after || 0) * 1_000),
    retry: false,
  });
  return (
    <section className="discovery-section" aria-label="Related books">
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.data && (
        <DiscoveryShelf
          shelf={query.data}
          onPreview={(item, button) => {
            if (item.book.provider === "hardcover" && item.book.external_id) {
              trigger.current = button;
              setSelected(item.book.external_id);
            }
          }}
        />
      )}
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
    </section>
  );
}
