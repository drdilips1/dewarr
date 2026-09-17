import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
        "assets",
        "identity-history",
        "version-reviews",
        "lists",
        "list",
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
  const [offset, setOffset] = useState(0);
  const refresh = useRefreshIdentity();
  const history = useQuery({
    queryKey: ["identity-history", entityId, workId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/identity/changes", {
          params: {
            query: { entity_id: entityId, work_id: workId, offset, limit: 10 },
          },
        }),
      ),
    enabled: open,
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
          <div className="pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Previous corrections
              </button>
            )}
            {offset + 10 < history.data.total && (
              <button type="button" onClick={() => setOffset(offset + 10)}>
                Next corrections
              </button>
            )}
          </div>
        </>
      )}
    </details>
  );
}
