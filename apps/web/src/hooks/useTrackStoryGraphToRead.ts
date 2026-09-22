import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";

/** To-read is the shelf selected on connect. Track it so an empty shelf still appears. */
export function useTrackStoryGraphToRead(enabled = true) {
  const cache = useQueryClient();
  const started = useRef(false);
  const account = useQuery({
    queryKey: ["storygraph-account"],
    enabled,
    queryFn: async () =>
      result(await api.GET("/api/reading-accounts/storygraph")),
  });
  const subscriptions = useQuery({
    queryKey: ["reading-subscriptions"],
    enabled,
    queryFn: async () =>
      result(await api.GET("/api/reading-accounts/subscriptions")),
  });
  const follow = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/reading-accounts/follow", {
          body: {
            provider: "storygraph",
            external_id: "to-read",
            interval_minutes: 60,
          },
        }),
      ),
    onSuccess: async () => {
      await Promise.all(
        ["reading-subscriptions", "lists", "list-subscription"].map((key) =>
          cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
  useEffect(() => {
    if (!enabled || started.current || follow.isPending || follow.isSuccess)
      return;
    const shelves = account.data?.shelves;
    const rows = subscriptions.data;
    if (!shelves || !rows) return;
    const shelf = shelves.find(
      (item) => item.kind === "shelf" && item.external_id === "to-read",
    );
    const tracked = rows.some(
      (entry) =>
        entry.subscription.provider === "storygraph" &&
        entry.external_id === "to-read",
    );
    if (!shelf || tracked || (shelf.count != null && shelf.count > 0)) return;
    started.current = true;
    follow.mutate();
  }, [enabled, account.data, subscriptions.data, follow]);
  return follow;
}
