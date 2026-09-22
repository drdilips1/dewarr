import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";

export function usePendingApprovals(enabled: boolean) {
  return useQuery({
    queryKey: ["requests", "pending-count"],
    queryFn: async () =>
      result(
        await api.GET("/api/requests", {
          params: { query: { pending_only: true, limit: 1 } },
        }),
      ),
    enabled,
    refetchInterval: 30_000,
  });
}
