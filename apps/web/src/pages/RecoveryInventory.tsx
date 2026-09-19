import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";

export type InventoryReview =
  components["schemas"]["InventoryReconciliationView"];

export function PrepareInventoryReview({
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
        await api.POST("/api/recovery/inventory-reconciliations", {
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
          ? "Preparing inventory review…"
          : `Review inventory for ${title}`}
      </button>
      <Notice error={prepare.error} />
    </>
  );
}

export function InventoryRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: InventoryReview;
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
          "/api/recovery/inventory-reconciliations/{identifier}/accept",
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
      aria-labelledby="inventory-review-title"
    >
      <h3 id="inventory-review-title" ref={heading} tabIndex={-1}>
        Review current library inventory
      </h3>
      <p>
        Refresh the saved library from this complete Audiobookshelf observation.
        The worker checks the inventory and permissions again before applying
        it.
      </p>
      <p>
        Missing media loses its availability badge and awaits review. Lost
        library access is recorded separately. Existing grants, manual matches
        and collection coverage rules are preserved. This does not replace
        missing books, modify media or resume automation.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.integration_id}>
            <strong>{item.title}</strong>: {item.summary.current_items} current
            items in {item.summary.libraries} visible libraries (
            {item.summary.audio_items} with audio, {item.summary.ebook_items}{" "}
            with ebooks).
            <br />
            {item.summary.missing_media} saved media entries absent from their
            library; {item.summary.unavailable_libraries} saved libraries
            inaccessible; {item.summary.new_libraries} newly visible libraries.
            New libraries receive no member grants automatically.
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
              ? "Accepting inventory review…"
              : "Record current inventory"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
