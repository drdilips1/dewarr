import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";

export default function Series({ canEdit }: { canEdit: boolean }) {
  const { externalId = "" } = useParams();
  return (
    <SeriesContent key={externalId} externalId={externalId} canEdit={canEdit} />
  );
}

function SeriesContent({
  externalId,
  canEdit,
}: {
  externalId: string;
  canEdit: boolean;
}) {
  const cache = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [listId, setListId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [added, setAdded] = useState(0);
  const queryKey = ["series", externalId, offset];
  const catalog = useQuery({
    queryKey,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/series/hardcover/{external_id}", {
          params: {
            path: { external_id: externalId },
            query: { offset, limit: 50 },
          },
        }),
      ),
    refetchInterval: (query) =>
      ["queued", "running", "retrying"].includes(query.state.data?.status || "")
        ? 1500
        : false,
  });
  const lists = useQuery({
    queryKey: ["lists"],
    queryFn: async () => result(await api.GET("/api/lists")),
    enabled: canEdit,
  });
  const policy = useQuery({
    queryKey: ["list-policy", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/acquisition", {
          params: { path: { list_id: listId } },
        }),
      ),
    enabled: canEdit && Boolean(listId),
  });
  const refresh = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/catalog/series/hardcover/{external_id}/refresh", {
          params: {
            path: { external_id: externalId },
            header: { "idempotency-key": crypto.randomUUID() },
          },
        }),
      ),
    onSuccess: async () => {
      setSelected([]);
      await cache.invalidateQueries({ queryKey: ["series", externalId] });
    },
  });
  const add = useMutation({
    mutationFn: async () => {
      // Each existing list command is idempotent. Retain failed selections so a
      // partial network failure can be retried without repeating successful work.
      const ids = [...selected];
      const results: PromiseSettledResult<unknown>[] = [];
      for (let offset = 0; offset < ids.length; offset += 5) {
        results.push(
          ...(await Promise.allSettled(
            ids.slice(offset, offset + 5).map(async (work_id) =>
              result(
                await api.POST("/api/lists/{list_id}/entries", {
                  params: { path: { list_id: listId } },
                  body: { work_id },
                }),
              ),
            ),
          )),
        );
      }
      const failed = ids.filter(
        (_, index) => results[index].status === "rejected",
      );
      setSelected(failed);
      setAdded(ids.length - failed.length);
      await cache.invalidateQueries({ queryKey: ["lists"] });
      if (failed.length)
        throw new Error(
          `${failed.length} books could not be added. Successful additions were kept; retry the remaining selection.`,
        );
    },
  });
  if (catalog.isPending) return <Loading />;
  if (!catalog.data) return <Notice error={catalog.error} />;
  const data = catalog.data;
  const loading = ["queued", "running", "retrying"].includes(data.status);
  const changePage = (value: number) => {
    setOffset(value);
    setSelected([]);
    setAdded(0);
  };
  return (
    <>
      <Link to="/">Back to catalog</Link>
      <h1>{data.name}</h1>
      <p className="muted">Hardcover series · {data.external_id}</p>
      {data.description && <p>{data.description}</p>}
      <p role="status">{data.message}</p>
      {data.fetched_at && (
        <p className="muted">
          {data.books} books · {data.owned} in your library · {data.ebook}{" "}
          {data.ebook === 1 ? "ebook" : "ebooks"} · {data.audio}{" "}
          {data.audio === 1 ? "audiobook" : "audiobooks"}
        </p>
      )}
      <Notice
        error={
          catalog.error ||
          refresh.error ||
          add.error ||
          lists.error ||
          policy.error
        }
      />
      {canEdit && (
        <button
          disabled={refresh.isPending || loading || add.isPending}
          onClick={() => refresh.mutate()}
        >
          {data.fetched_at ? "Refresh series" : "Load series from Hardcover"}
        </button>
      )}
      <details className="editor">
        <summary>About this series catalog</summary>
        {data.fetched_at && (
          <p className="muted">
            Last verified {new Date(data.fetched_at).toLocaleString()} ·{" "}
            {data.total} entries.
          </p>
        )}
        <p className="muted">
          Book counts exclude compilations, partial books and merged records.
          Uncertain entries remain visible for review. Available downloads may
          contain a different selection of books.
        </p>
      </details>
      {canEdit && data.items.length > 0 && (
        <section className="panel editor" aria-label="Curate series">
          <label>
            Destination list
            <select
              disabled={add.isPending}
              value={listId}
              onChange={(e) => {
                setListId(e.target.value);
                setAdded(0);
              }}
            >
              <option value="">Choose your list</option>
              {lists.data
                ?.filter((l) => l.editable)
                .map((l) => (
                  <option value={l.id} key={l.id}>
                    {l.name}
                  </option>
                ))}
            </select>
          </label>
          {listId && policy.isSuccess && (
            <p role="status">
              {policy.data?.active &&
              policy.data.configuration.mode === "automatic"
                ? "This list automatically requests missing media for new additions."
                : "This list has no active automatic acquisition policy."}
            </p>
          )}
          <button
            disabled={add.isPending || loading}
            onClick={() =>
              setSelected([
                ...new Set(
                  data.items
                    .filter(
                      (e) =>
                        !e.compilation &&
                        !e.partial &&
                        !e.merged_record &&
                        !e.ambiguous_position &&
                        e.publication === "published",
                    )
                    .map((e) => e.work.id),
                ),
              ])
            }
          >
            Select published books on this page
          </button>
          <button
            disabled={
              !listId ||
              !selected.length ||
              add.isPending ||
              loading ||
              !policy.isSuccess
            }
            onClick={() => add.mutate()}
          >
            Add selected books to list ({selected.length})
          </button>
          {added > 0 && <p role="status">Added {added} books to the list.</p>}
        </section>
      )}
      <div className="edition-grid">
        {data.items.map((entry) => (
          <article className="panel" key={entry.membership_id}>
            {canEdit && (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={selected.includes(entry.work.id)}
                  disabled={add.isPending || loading}
                  onChange={(e) =>
                    setSelected((previous) =>
                      e.target.checked
                        ? [...new Set([...previous, entry.work.id])]
                        : previous.filter((id) => id !== entry.work.id),
                    )
                  }
                />
                Select {entry.work.title}
              </label>
            )}
            <h2>
              <Link to={`/books/${entry.work.id}`}>
                {entry.position != null ? `${entry.position} · ` : ""}
                {entry.work.title}
              </Link>
            </h2>
            <p>{entry.work.authors.join(", ") || "Author unknown"}</p>
            <p>
              {entry.work.availability.owned
                ? "✓ In library"
                : "Not in your library"}
              {entry.work.availability.ebook && " · Ebook"}
              {entry.work.availability.audio && " · Audiobook"}
              {entry.work.availability.stale && " · Inventory needs refresh"}
            </p>
            <p className="muted">
              {[
                entry.compilation && "Compilation",
                entry.partial && "Partial book",
                entry.merged_record && "Merged provider record",
                entry.ambiguous_position && "Multiple works at this position",
                entry.publication === "unreleased" &&
                  `Unreleased · ${entry.release_date}`,
                entry.publication === "unknown" && "Publication date unknown",
                entry.details !== entry.position && entry.details,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </article>
        ))}
      </div>
      {data.fetched_at && !data.total && (
        <p>No accessible books were returned for this series.</p>
      )}
      <nav aria-label="Series pages">
        <button
          disabled={offset === 0 || add.isPending}
          onClick={() => changePage(Math.max(0, offset - 50))}
        >
          Previous
        </button>
        <span>
          {" "}
          {data.total ? offset + 1 : 0}–
          {Math.min(offset + data.items.length, data.total)} of{" "}
          {data.total}{" "}
        </span>
        <button
          disabled={offset + data.items.length >= data.total || add.isPending}
          onClick={() => changePage(offset + 50)}
        >
          Next
        </button>
      </nav>
    </>
  );
}
