import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

export type MainBookReview = components["schemas"]["ScopeReviewView"];

export default function SeriesScopeReview({
  externalId,
  generation,
  selected,
  review,
  onSelect,
}: {
  externalId: string;
  generation: number;
  selected: string[];
  review: MainBookReview;
  onSelect: (ids: string[]) => void;
}) {
  const cache = useQueryClient();
  const [confirmedDraft, setConfirmedDraft] = useState<string | null>(null);
  const draft = JSON.stringify([generation, review.id, [...selected].sort()]);
  const confirmed = confirmedDraft === draft;
  const command = useRef({ draft: "", key: crypto.randomUUID() });
  const path = { external_id: externalId };
  const changed = async () => {
    setConfirmedDraft(null);
    await cache.invalidateQueries({
      queryKey: ["series-main-books", externalId],
    });
  };
  const save = useMutation({
    mutationFn: async () => {
      if (command.current.draft !== draft)
        command.current = { draft, key: crypto.randomUUID() };
      return result(
        await api.POST(
          "/api/catalog/series/hardcover/{external_id}/main-books",
          {
            params: {
              path,
              header: { "idempotency-key": command.current.key },
            },
            body: {
              work_ids: selected,
              expected_generation: generation,
              expected_review_id: review.id ?? null,
              confirm_main_membership: true,
            },
          },
        ),
      );
    },
    onSuccess: changed,
  });
  const withdraw = useMutation({
    mutationFn: async () =>
      result(
        await api.DELETE(
          "/api/catalog/series/hardcover/{external_id}/main-books/{review_id}",
          { params: { path: { ...path, review_id: review.id! } } },
        ),
      ),
    onSuccess: changed,
  });
  const busy = save.isPending || withdraw.isPending;
  return (
    <section className="panel editor" aria-label="Main-book review">
      <details>
        <summary>Reusable main-book selection</summary>
        <p>
          Save which selected books belong to the main series. Positions alone
          cannot establish this. The review stays limited to these books and
          does not request downloads or include future additions.
        </p>
        <p role="status">{review.message}</p>
        {review.id && (
          <>
            <p className="muted">
              Revision {review.revision} · {review.books.length} reviewed books
            </p>
            <ul>
              {review.books.map((book) => (
                <li key={book.work_id}>{book.title}</li>
              ))}
            </ul>
            <button
              disabled={busy || review.state !== "current"}
              onClick={() => onSelect(review.books.map((book) => book.work_id))}
            >
              Select reviewed main books
            </button>
            <button
              disabled={busy || review.state === "withdrawn"}
              onClick={() => withdraw.mutate()}
            >
              Withdraw main-book review
            </button>
            <p className="muted">
              Withdrawal prevents reuse in new requests. Existing accepted
              requests keep their finite scope; cancel them separately if
              needed.
            </p>
          </>
        )}
        <Notice error={save.error || withdraw.error} />
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={busy || !selected.length}
            onChange={(event) =>
              setConfirmedDraft(event.target.checked ? draft : null)
            }
          />
          I reviewed the selected books as a reusable main-series selection.
        </label>
        <button
          disabled={busy || !confirmed || !selected.length}
          onClick={() => save.mutate()}
        >
          Save main-book review ({selected.length})
        </button>
      </details>
    </section>
  );
}
