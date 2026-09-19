import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";

export type OutboundReview =
  components["schemas"]["OutboundReconciliationView"];

export function PrepareOutboundReview({
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
  const [key] = useState(() => crypto.randomUUID());
  const prepare = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/outbound-reconciliations", {
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
          ? "Preparing outbound review…"
          : `Review outbound change for ${title}`}
      </button>
      <Notice error={prepare.error} />
    </>
  );
}

export function OutboundRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: OutboundReview;
  currentScan?: string;
  otherBusy: boolean;
}) {
  const client = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const heading = useRef<HTMLHeadingElement>(null);
  const prepared = review.status === "prepared";
  useEffect(() => {
    if (prepared) heading.current?.focus();
  }, [review.id, prepared]);
  const accept = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/recovery/outbound-reconciliations/{identifier}/accept",
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
    <section
      className="recovery-decision"
      aria-labelledby="outbound-review-title"
    >
      <h3 id="outbound-review-title" ref={heading} tabIndex={-1}>
        Review outbound list changes
      </h3>
      <p>
        Recheck the original Hardcover account, list and exact membership IDs.
        Record what is visible now without sending another list change. A
        satisfied request does not prove that our earlier write caused it.
      </p>
      <p>
        Old commands stop here. Write-back stays disabled until the list owner
        reviews current differences and confirms their settings again. An
        unconfirmed sent attempt remains held, even when the book is absent.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.operation_id}>
            <strong>{item.title}</strong>
            <p>
              Requested: {item.desired ? "present" : "absent"}. Saved status:{" "}
              {item.saved_status}.{" "}
              {item.pending_attempt
                ? "A sent attempt is unconfirmed."
                : "No sent attempt is recorded in this backup."}
            </p>
            <p>{item.message}</p>
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
              ? "Accepting outbound evidence…"
              : "Record outbound evidence"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
