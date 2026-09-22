import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { randomUUID } from "../randomUUID";

const active = (state: string) => ["queued", "running"].includes(state);

export type ReadingProvider = "goodreads" | "storygraph" | "hardcover";

const providers: ReadingProvider[] = ["goodreads", "storygraph", "hardcover"];
const names: Record<ReadingProvider, string> = {
  goodreads: "Goodreads",
  storygraph: "StoryGraph",
  hardcover: "Hardcover",
};

type Scope = ReadingProvider | "reading";

function named(scope: Scope, count?: number) {
  if (scope === "reading") return count === 1 ? "list" : "lists";
  const provider = names[scope];
  return count === 1 ? `${provider} list` : `${provider} lists`;
}

export function useRefreshReadingLists() {
  const cache = useQueryClient();
  const [batch, setBatch] = useState<{
    ids: string[];
    failures: string[];
    key: string;
    scope: Scope;
  } | null>(null);
  const [scope, setScope] = useState<Scope>("reading");
  const [message, setMessage] = useState("");
  const progress = useQuery({
    queryKey: ["reading-list-refresh", batch?.key],
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
    const title = named(batch.scope, lists.length);
    setMessage(
      failures.length
        ? `Some ${named(batch.scope)} could not be refreshed. ${failures.join(" ")}`
        : `Refreshed ${lists.length} ${title}.`,
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
    mutationFn: async (provider?: ReadingProvider) => {
      const next: Scope = provider ?? "reading";
      setScope(next);
      setMessage("");
      const subscriptions = result(
        await api.GET("/api/reading-accounts/subscriptions"),
      );
      const lists = subscriptions.filter(
        ({ subscription }) =>
          subscription.enabled &&
          (provider
            ? subscription.provider === provider
            : providers.includes(subscription.provider)),
      );
      const ids: string[] = [];
      const failures: string[] = [];
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
      if (ids.length)
        setBatch({ ids, failures, key: randomUUID(), scope: next });
      else
        setMessage(
          failures.length
            ? `${named(next)} refresh failed. ${failures.join(" ")}`
            : `No enabled ${next === "reading" ? "reading lists" : named(next)}. Track lists in Settings → Reading accounts.`,
        );
      void cache.invalidateQueries({ queryKey: ["list-subscription"] });
    },
  });
  return {
    refresh: (provider?: ReadingProvider) => refresh.mutate(provider),
    busy: refresh.isPending || !!batch,
    scope,
    message,
    error: refresh.error,
  };
}
