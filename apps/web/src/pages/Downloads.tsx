import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";

export default function Downloads({ canManage }: { canManage: boolean }) {
  const [offset, setOffset] = useState(0);
  const cache = useQueryClient();
  const downloads = useQuery({
    queryKey: ["downloads", offset],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/downloads", {
          params: { query: { offset, limit: 10 } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (item) => !["complete", "cancelled"].includes(item.state),
      )
        ? 3000
        : false,
  });
  const action = useMutation({
    mutationFn: async ({ id, cancel }: { id: string; cancel: boolean }) => {
      const params = { path: { attempt_id: id } };
      return result(
        cancel
          ? await api.DELETE("/api/acquisition/downloads/{attempt_id}", {
              params,
            })
          : await api.POST("/api/acquisition/downloads/{attempt_id}/recheck", {
              params,
            }),
      );
    },
    onSuccess: async () => {
      await Promise.all(
        ["downloads", "activity", "requests", "release-selections"].map((key) =>
          cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
  if (!downloads.data?.items.length && !downloads.error) return null;
  return (
    <section className="panel library-access" aria-label="Downloads">
      <h2>Downloads</h2>
      <p className="muted">
        Completed downloads still need inspection and library confirmation
        before they appear as available.
      </p>
      <Notice error={downloads.error || action.error} />
      {downloads.data?.items.map((item) => (
        <article className="activity-row" key={item.id}>
          <div className="grow">
            <h3>{item.work_title}</h3>
            <p>{item.release_title}</p>
            <p>{item.message}</p>
            {item.progress !== null && item.progress !== undefined && (
              <p className="muted">
                {Math.round(item.progress * 100)}% downloaded
              </p>
            )}
            <div className="button-row">
              {canManage && item.can_cancel && (
                <button
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: item.id, cancel: true })}
                >
                  Cancel before submission
                </button>
              )}
              {canManage && item.can_recheck && (
                <button
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: item.id, cancel: false })}
                >
                  Check existing transfer
                </button>
              )}
              {item.inspection_id && (
                <Link
                  to={`/organization/inspections?inspection=${item.inspection_id}`}
                >
                  Review downloaded files
                </Link>
              )}
            </div>
          </div>
          <span className="status">{item.state}</span>
        </article>
      ))}
      <div className="button-row">
        {offset > 0 && (
          <button onClick={() => setOffset((value) => value - 10)}>
            Previous downloads
          </button>
        )}
        {downloads.data && offset + 10 < downloads.data.total && (
          <button onClick={() => setOffset((value) => value + 10)}>
            More downloads
          </button>
        )}
      </div>
    </section>
  );
}
