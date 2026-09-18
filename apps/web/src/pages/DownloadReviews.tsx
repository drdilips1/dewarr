import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Review = components["schemas"]["ReviewView"];

export default function DownloadReviews() {
  const [offset, setOffset] = useState(0);
  const keys = useRef(new Map<string, string>());
  const cache = useQueryClient();
  const queue = useQuery({
    queryKey: ["download-reviews", offset],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/reviews", {
          params: { query: { offset, limit: 10 } },
        }),
      ),
    refetchInterval: 5000,
  });
  const claim = useMutation({
    mutationFn: async (row: Review) => {
      const revision = `${row.attempt_id}:${row.revision}`;
      if (!keys.current.has(revision))
        keys.current.set(revision, crypto.randomUUID());
      return result(
        await api.POST("/api/acquisition/reviews/{attempt_id}/claim", {
          params: {
            path: { attempt_id: row.attempt_id },
            header: { "idempotency-key": keys.current.get(revision)! },
          },
          body: { revision: row.revision },
        }),
      );
    },
    onSettled: async () => {
      await Promise.all(
        ["download-reviews", "downloads", "activity", "inspections"].map(
          (key) => cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
  return (
    <section
      className="panel library-access"
      aria-label="Download import reviews"
    >
      <h2>Download import reviews</h2>
      <p className="muted">
        Review completed member downloads for import into their selected
        library. Unstarted reviews can be reassigned; imports already underway
        stay with their reviewer.
      </p>
      <Notice error={queue.error || claim.error} />
      {queue.isPending && <Loading />}
      {queue.data && !queue.data.total && (
        <p>No completed downloads need administrator review.</p>
      )}
      {queue.data?.items.map((row) => (
        <article className="activity-row" key={row.attempt_id}>
          <div className="grow">
            <h3>{row.work_title}</h3>
            <p>
              {row.medium === "audio" ? "Audiobook" : "Ebook"} · {row.message}
            </p>
            <div className="button-row">
              {row.can_claim && (
                <button
                  disabled={claim.isPending}
                  onClick={() => claim.mutate(row)}
                >
                  {claim.isPending &&
                  claim.variables.attempt_id === row.attempt_id
                    ? "Assigning…"
                    : row.retry
                      ? "Retry file inspection"
                      : row.reassignment
                        ? "Reassign review to me"
                        : "Review this download"}
                </button>
              )}
              {row.inspection_id && (
                <Link
                  to={`/organization/inspections?inspection=${row.inspection_id}`}
                >
                  Open file review
                </Link>
              )}
            </div>
          </div>
        </article>
      ))}
      <div className="button-row">
        {offset > 0 && (
          <button onClick={() => setOffset((value) => value - 10)}>
            Previous reviews
          </button>
        )}
        {queue.data && offset + 10 < queue.data.total && (
          <button onClick={() => setOffset((value) => value + 10)}>
            More reviews
          </button>
        )}
      </div>
    </section>
  );
}
