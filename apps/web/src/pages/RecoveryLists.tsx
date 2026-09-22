import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";
import { randomUUID } from "../randomUUID";

export type ListBaselineReview =
  components["schemas"]["ListReconciliationView"];

export function PrepareListBaselineReview({
  scanId,
  findingId,
  title,
  disabled,
}: {
  scanId: string;
  findingId: string;
  title: string;
  disabled: boolean;
}) {
  const client = useQueryClient();
  const [key] = useState(() => randomUUID());
  const prepare = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/list-reconciliations", {
          params: { header: { "idempotency-key": key } },
          body: { scan_id: scanId, finding_ids: [findingId] },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["recovery"] }),
  });
  return (
    <>
      <button
        disabled={disabled || prepare.isPending}
        onClick={() => prepare.mutate()}
      >
        {prepare.isPending
          ? "Preparing list baseline…"
          : `Review list baseline for ${title}`}
      </button>
      <Notice error={prepare.error} />
    </>
  );
}

export function ListBaselineRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: ListBaselineReview;
  currentScan?: string;
  otherBusy: boolean;
}) {
  const client = useQueryClient();
  const [key] = useState(() => randomUUID());
  const heading = useRef<HTMLHeadingElement>(null);
  const prepared = review.status === "prepared";
  useEffect(() => {
    if (prepared) heading.current?.focus();
  }, [review.id, prepared]);
  const accept = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/recovery/list-reconciliations/{identifier}/accept",
          {
            params: {
              path: { identifier: review.id },
              header: { "idempotency-key": key },
            },
            body: { revision: review.revision },
          },
        ),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["recovery"] }),
  });
  return (
    <section className="recovery-decision" aria-labelledby="list-review-title">
      <h3 id="list-review-title" ref={heading} tabIndex={-1}>
        Review current list baseline
      </h3>
      <p>
        Use the current external membership as the restored list baseline.
        Recovered additions appear for browsing and deliberate catch-up
        selection. They do not start downloads automatically.
      </p>
      <p>
        Exclusions and manually added books stay intact. Acquisition and
        outbound writes stay paused until the owner reviews their settings
        again. Uncertain sent writes remain unresolved; this action sends no
        list changes.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.subscription_id}>
            <strong>{item.title}</strong> (
            {item.provider === "hardcover"
              ? "Hardcover"
              : item.provider === "storygraph"
                ? "StoryGraph"
                : "Goodreads"}
            )
            <p>
              {item.summary.visible} visible books; {item.summary.new} newly
              observed; {item.summary.returned} returned;{" "}
              {item.summary.excluded} saved exclusions.
            </p>
            <p>
              {item.provider === "storygraph"
                ? "This StoryGraph check is a partial view. Books omitted from it keep their saved membership."
                : item.complete
                  ? `${item.summary.missing} previously observed books are no longer in the complete list. Remove only their external membership; preserve manual additions and other request reasons.`
                  : "RSS is a partial view. Books omitted from this feed keep their saved membership."}
            </p>
            {item.pause_acquisition && (
              <p>
                Pause the current acquisition policy and require a new
                activation review.
              </p>
            )}
            {item.pause_writeback && (
              <p>
                Disable current list write-back pending a new owner
                confirmation.
              </p>
            )}
          </li>
        ))}
      </ul>
      <p role="status">{review.message}</p>
      {prepared && (
        <>
          <p className="muted">
            Review expires {new Date(review.expires_at).toLocaleString()}.
          </p>
          {review.scan_id !== currentScan && (
            <p>A newer observation exists. Prepare a new review from it.</p>
          )}
          <button
            disabled={
              accept.isPending || otherBusy || review.scan_id !== currentScan
            }
            onClick={() => accept.mutate()}
          >
            {accept.isPending
              ? "Accepting list baseline…"
              : "Record list baseline"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
