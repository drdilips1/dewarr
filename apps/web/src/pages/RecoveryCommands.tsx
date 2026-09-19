import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";

export type CommandReview = components["schemas"]["CommandReconciliationView"];

export function PrepareCommandReview({
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
        await api.POST("/api/recovery/command-reconciliations", {
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
          ? "Preparing command review…"
          : `Review historical command for ${title}`}
      </button>
      <Notice error={prepare.error} />
    </>
  );
}

export function CommandRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: CommandReview;
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
          "/api/recovery/command-reconciliations/{identifier}/accept",
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
      aria-labelledby="command-review-title"
    >
      <h3 id="command-review-title" ref={heading} tabIndex={-1}>
        Review historical commands
      </h3>
      <p>
        Stop these saved approvals and acquisition controllers from running
        again. Keep wanted books already recorded, independent request reasons,
        download reservations and files unchanged. Completed batch receipts are
        preserved.
      </p>
      <p>
        This does not confirm external effects or resume automation. To request
        unsaved books or reactivate acquisition after recovery, the owner must
        review a fresh preview.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.entity_id}>
            <strong>{item.title}</strong>
            <p>Saved state: {item.saved_state}.</p>
            <p>
              {item.action === "pause-policy"
                ? "Pause this list policy and stop scheduled book checks. Keep monitored books and their request history."
                : item.action === "pause-controller"
                  ? "Disable this series controller and invalidate its earlier authorization. Keep its accepted batch and acquisition progress."
                  : "Retire this command. Its old preview and worker cannot run again; any existing wanted books stay intact."}
            </p>
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
              ? "Retiring historical commands…"
              : "Retire selected commands"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
