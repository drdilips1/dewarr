import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import { randomUUID } from "../randomUUID";

type Prepared = components["schemas"]["ManualPackPrepared"];

export default function ManualPack({
  selectionId,
  onPrepared,
  onClose,
}: {
  selectionId: string;
  onPrepared: (value: Prepared) => Promise<void>;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<string[] | null>(null);
  const key = useRef(randomUUID());
  const query = useQuery({
    queryKey: ["manual-pack-preview", selectionId],
    queryFn: async () =>
      result(
        await api.GET(
          "/api/acquisition/selections/{selection_id}/pack-preview",
          {
            params: { path: { selection_id: selectionId } },
          },
        ),
      ),
    refetchOnWindowFocus: false,
  });
  const ids =
    selected ??
    query.data?.records
      .filter((book) => ["wanted", "pending"].includes(book.state))
      .map((book) => book.work_id) ??
    [];
  const prepare = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/acquisition/selections/{selection_id}/pack-selections",
          {
            params: {
              path: { selection_id: selectionId },
              header: { "idempotency-key": key.current },
            },
            body: { revision: query.data!.revision!, work_ids: ids },
          },
        ),
      ),
    onSuccess: onPrepared,
  });
  return (
    <section className="panel editor" aria-label="Additional pack books">
      <h4>Additional books in this pack</h4>
      <p>
        Review the covered books and choose which to prepare in the same medium
        and library. Each book is checked against your library and pending
        requests. This step does not start a download.
      </p>
      <Notice error={query.error || prepare.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        query.data && (
          <>
            <p role="status">{query.data.message}</p>
            {query.data.records.map((book) => (
              <label key={book.work_id} className="check-label">
                <input
                  type="checkbox"
                  checked={ids.includes(book.work_id)}
                  disabled={
                    prepare.isPending ||
                    !["wanted", "pending"].includes(book.state)
                  }
                  onChange={(event) => {
                    setSelected(
                      event.target.checked
                        ? [...ids, book.work_id]
                        : ids.filter((id) => id !== book.work_id),
                    );
                    key.current = randomUUID();
                    prepare.reset();
                  }}
                />
                <span>
                  {book.title}
                  <small className="block">{book.message}</small>
                </span>
              </label>
            ))}
            {query.data.state === "ready" && (
              <button
                className="primary"
                disabled={!ids.length || prepare.isPending || query.isFetching}
                onClick={() => prepare.mutate()}
              >
                {prepare.isPending
                  ? "Preparing pack books…"
                  : `Prepare selected pack books (${ids.length})`}
              </button>
            )}
            {query.data.external_id && (
              <Link
                to={`/series/hardcover/${encodeURIComponent(query.data.external_id)}`}
              >
                Review main-series books
              </Link>
            )}
          </>
        )
      )}
      <div className="button-row">
        <button
          disabled={prepare.isPending || query.isFetching}
          onClick={() => {
            setSelected(null);
            key.current = randomUUID();
            prepare.reset();
            void query.refetch();
          }}
        >
          Refresh pack review
        </button>
        <button disabled={prepare.isPending} onClick={onClose}>
          Close pack review
        </button>
      </div>
    </section>
  );
}
