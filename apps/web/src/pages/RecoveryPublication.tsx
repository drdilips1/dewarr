import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";
import { randomUUID } from "../randomUUID";

export type PublicationReview =
  components["schemas"]["PublicationReconciliationView"];

export function PreparePublicationReview({
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
        await api.POST("/api/recovery/publication-reconciliations", {
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
          ? "Preparing publication review…"
          : `Review publication for ${title}`}
      </button>
      <Notice error={prepare.error} />
    </>
  );
}

export function PublicationRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: PublicationReview;
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
          "/api/recovery/publication-reconciliations/{identifier}/accept",
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
      aria-labelledby="publication-review-title"
    >
      <h3 id="publication-review-title" ref={heading} tabIndex={-1}>
        Review published books
      </h3>
      <p>
        Record files already published into the library. Each book has its own
        result. Availability requires matching Audiobookshelf evidence for the
        files and frozen version.
      </p>
      <p>
        The worker verifies the journal, files and any confirming backend
        evidence again. It leaves folders, media, journals and automation
        unchanged. Books awaiting confirmation remain pending; withdrawn imports
        stay held.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.entry_id}>
            <strong>{item.title}</strong> (
            {item.medium === "audio" ? "Audiobook" : "Ebook"})
            <p>
              {item.outcome === "confirmed"
                ? "Confirm available in Audiobookshelf"
                : item.outcome === "cancel-held"
                  ? "Record publication and hold withdrawn import"
                  : "Record publication; await library confirmation"}
            </p>
            <p>{item.reason}</p>
            <p className="muted">Library folder: {item.folder}</p>
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
              ? "Accepting publication review…"
              : "Record published books"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
