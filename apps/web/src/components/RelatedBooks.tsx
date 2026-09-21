import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import DiscoveryShelf from "./DiscoveryShelf";

export default function RelatedBooks({ workId }: { workId: string }) {
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
      {query.data && <DiscoveryShelf shelf={query.data} />}
    </section>
  );
}
