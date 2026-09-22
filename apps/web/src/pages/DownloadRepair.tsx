import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Notice } from "../components";
import { randomUUID } from "../randomUUID";

export default function DownloadRepair({ attemptId }: { attemptId: string }) {
  const cache = useQueryClient();
  const keys = useRef(new Map<string, string>());
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.GET(
          "/api/acquisition/downloads/{attempt_id}/repair-preview",
          {
            params: { path: { attempt_id: attemptId } },
          },
        ),
      ),
  });
  const repair = useMutation({
    mutationFn: async (revision: string) => {
      if (!keys.current.has(revision)) keys.current.set(revision, randomUUID());
      return result(
        await api.POST("/api/acquisition/downloads/{attempt_id}/repairs", {
          params: {
            path: { attempt_id: attemptId },
            header: { "idempotency-key": keys.current.get(revision)! },
          },
          body: { revision },
        }),
      );
    },
    onSuccess: async () => {
      preview.reset();
      await Promise.all(
        ["downloads", "activity"].map((key) =>
          cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
  return (
    <div>
      <Notice error={preview.error || repair.error} />
      {preview.data ? (
        <section aria-label="Review updated download connections">
          <p>Verify the existing transfer using these updated connections:</p>
          <ul>
            {preview.data.changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
          <p className="muted">
            The selected release and file locations are preserved.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={repair.isPending}
              onClick={() => repair.mutate(preview.data!.revision)}
            >
              Confirm and check existing transfer
            </button>
            <button disabled={repair.isPending} onClick={() => preview.reset()}>
              Close review
            </button>
          </div>
        </section>
      ) : (
        <button
          disabled={preview.isPending || repair.isPending}
          onClick={() => preview.mutate()}
        >
          Review updated connections
        </button>
      )}
    </div>
  );
}
