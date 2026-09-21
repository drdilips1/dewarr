import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { Collection } from "../components/DiscoveryCollections";
import type { components } from "../api/schema";

export function useDiscoverShelfSources() {
  const collections = useQuery({
    queryKey: ["discover-shelf-collections"],
    staleTime: 300_000,
    queryFn: async ({ signal }) => {
      const items: Collection[] = [];
      for (let page = 1; ; page++) {
        const value = result(
          await api.GET("/api/discovery/collections", {
            params: { query: { page, limit: 100 } },
            signal,
          }),
        );
        items.push(...value.items);
        if (!value.items.length || items.length >= value.total) return items;
      }
    },
  });
  const lists = useQuery({
    queryKey: ["lists", "discover-shelves"],
    queryFn: async ({ signal }) => {
      const items: components["schemas"]["ListView"][] = [];
      for (let offset = 0; ; offset += 100) {
        const value = result(
          await api.GET("/api/lists/page", {
            params: { query: { offset, limit: 100 } },
            signal,
          }),
        );
        items.push(...value.items);
        if (!value.items.length || items.length >= value.total) return items;
      }
    },
  });
  return { collections, lists };
}
