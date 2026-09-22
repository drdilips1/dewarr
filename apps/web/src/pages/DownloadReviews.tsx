import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import { randomUUID } from "../randomUUID";

type Review = components["schemas"]["ReviewView"];

export default function DownloadReviews() {
  const keys = useRef(new Map<string, string>());
  const cache = useQueryClient();
  const queue = usePagedQuery({
    queryKey: ["download-reviews"],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/acquisition/reviews", {
          signal,
          params: { query: { offset, limit: 10 } },
        }),
      ),
    refetchInterval: 5000,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const claim = useMutation({
    mutationFn: async (row: Review) => {
      const revision = `${row.attempt_id}:${row.revision}`;
      if (!keys.current.has(revision)) keys.current.set(revision, randomUUID());
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
      className="panel library-access requests-panel"
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
      {!!queue.data?.items.length && (
        <div className="requests-table-scroll">
          <table
            className="requests-table review-table"
            aria-label="Download import reviews"
          >
            <thead>
              <tr>
                <th scope="col">Book</th>
                <th scope="col">Media / details</th>
                <th scope="col">Review</th>
              </tr>
            </thead>
            <tbody>
              {queue.data.items.map((row) => (
                <tr key={row.attempt_id}>
                  <td>
                    <h3>{row.work_title}</h3>
                  </td>
                  <td>
                    <p>
                      {row.medium === "audio" ? "Audiobook" : "Ebook"} ·{" "}
                      {row.message}
                    </p>
                  </td>
                  <td>
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <InfiniteScroll query={queue} />
    </section>
  );
}
