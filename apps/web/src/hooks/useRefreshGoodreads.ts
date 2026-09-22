import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { randomUUID } from "../randomUUID";

const active = (state: string) => ["queued", "running"].includes(state);

export function useRefreshGoodreads() {
  const cache = useQueryClient();
  const [batch, setBatch] = useState<{
    ids: string[];
    failures: string[];
    key: string;
  } | null>(null);
  const [message, setMessage] = useState("");
  const progress = useQuery({
    queryKey: ["goodreads-refresh", batch?.key],
    enabled: !!batch,
    queryFn: async () =>
      result(await api.GET("/api/reading-accounts/subscriptions")),
    refetchInterval: (query) => (query.state.status === "error" ? false : 1500),
    retry: 2,
  });
  useEffect(() => {
    if (!batch) return;
    if (progress.error) {
      setMessage(
        "Refresh started, but progress could not be checked. Check your lists in Settings.",
      );
      setBatch(null);
      return;
    }
    if (!progress.data) return;
    const lists = progress.data.filter((item) =>
      batch.ids.includes(item.list_id),
    );
    if (lists.some((item) => active(item.subscription.state))) return;
    const failures = [...batch.failures];
    for (const item of lists) {
      if (item.subscription.state === "failed" || !item.subscription.enabled)
        failures.push(`${item.name}: ${item.subscription.message}`);
    }
    const missing = batch.ids.length - lists.length;
    if (missing) failures.push(`${missing} list(s) are no longer available.`);
    setMessage(
      failures.length
        ? `Some Goodreads lists could not be refreshed. ${failures.join(" ")}`
        : `Refreshed ${lists.length} Goodreads ${lists.length === 1 ? "list" : "lists"}.`,
    );
    setBatch(null);
    for (const key of [
      "reading-subscriptions",
      "list-subscription",
      "lists",
      "discovery-personal",
      "list-settings-details",
    ])
      void cache.invalidateQueries({ queryKey: [key] });
  }, [batch, progress.data, progress.error, cache]);

  const refresh = useMutation({
    mutationFn: async () => {
      setMessage("");
      // Read settings at click time, including lists outside the current page.
      const subscriptions = result(
        await api.GET("/api/reading-accounts/subscriptions"),
      );
      const lists = subscriptions.filter(
        ({ subscription }) =>
          subscription.provider === "goodreads" && subscription.enabled,
      );
      const ids: string[] = [];
      const failures: string[] = [];
      // Keep large collections from flooding the API with simultaneous requests.
      for (const item of lists) {
        try {
          result(
            await api.POST("/api/lists/{list_id}/subscription/sync", {
              params: {
                path: { list_id: item.list_id },
                header: { "idempotency-key": randomUUID() },
              },
            }),
          );
          ids.push(item.list_id);
        } catch (error) {
          failures.push(
            `${item.name}: ${error instanceof Error ? error.message : "Refresh failed."}`,
          );
        }
      }
      if (ids.length) setBatch({ ids, failures, key: randomUUID() });
      else
        setMessage(
          failures.length
            ? `Goodreads refresh failed. ${failures.join(" ")}`
            : "No enabled Goodreads lists. Enable lists in Settings → Reading accounts.",
        );
      void cache.invalidateQueries({ queryKey: ["list-subscription"] });
    },
  });
  return {
    refresh: () => refresh.mutate(),
    busy: refresh.isPending || !!batch,
    message,
    error: refresh.error,
  };
}
