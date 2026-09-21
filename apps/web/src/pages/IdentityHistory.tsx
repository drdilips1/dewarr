import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";

export function useRefreshIdentity() {
  const cache = useQueryClient();
  return async () => {
    await Promise.all(
      [
        "works",
        "work",
        "work-metadata",
        "reader-work-metadata",
        "work-grouping",
        "library-books",
        "discovery",
        "assets",
        "identity-history",
        "version-reviews",
        "lists",
        "list",
        "merge-preview",
        "requests",
        "request-preview",
      ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
    );
  };
}

export default function IdentityHistory({
  entityId,
  workId,
  onChanged,
}: {
  entityId?: string;
  workId?: string;
  onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const refresh = useRefreshIdentity();
  const history = usePagedQuery({
    queryKey: ["identity-history", entityId, workId],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/identity/changes", {
          signal,
          params: {
            query: { entity_id: entityId, work_id: workId, offset, limit: 10 },
          },
        }),
      ),
    enabled: open,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const undo = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.POST("/api/identity/changes/{change_id}/undo", {
          params: { path: { change_id: id } },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      onChanged?.();
    },
  });
  return (
    <details
      className="panel provenance"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Match correction history</summary>
      <p className="muted">
        Undo a matching decision when its details have not changed. Library
        files stay in place.
      </p>
      <Notice error={history.error || undo.error} />
      {open && history.isPending && <Loading />}
      {history.data && (
        <>
          {!history.data.items.length && (
            <p className="muted">No matching corrections recorded yet.</p>
          )}
          {history.data.items.map((change) => (
            <article className="source-attribution" key={change.id}>
              <span>
                <strong>{change.summary}</strong>
                <small>
                  {change.actor_name} ·{" "}
                  {new Date(change.created_at).toLocaleString()}
                </small>
                <small>
                  {change.undone_at
                    ? "Undone"
                    : change.can_undo
                      ? "Can be undone"
                      : "Later changes require a new correction"}
                </small>
              </span>
              {change.can_undo && (
                <button
                  type="button"
                  disabled={undo.isPending}
                  onClick={() => undo.mutate(change.id)}
                >
                  Undo correction
                </button>
              )}
            </article>
          ))}
          <InfiniteScroll query={history} />
        </>
      )}
    </details>
  );
}
