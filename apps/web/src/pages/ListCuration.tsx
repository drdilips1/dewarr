import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";
import EnrichedBookCard from "../components/EnrichedBookCard";

type Detail = components["schemas"]["ListDetail"];
type Input = components["schemas"]["CurationInput"];

export default function ListCuration({
  list,
  editable,
  onChange,
  loading,
  filtered,
  onPage,
}: {
  list: Detail;
  editable: boolean;
  loading: boolean;
  filtered: boolean;
  onPage: (offset: number) => void;
  onChange: () => Promise<unknown>;
}) {
  const [selection, setSelection] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState("");
  const [selectionRevision, setSelectionRevision] = useState<string>();
  const selected = selection;
  const pageOffset = list.offset;
  const shown = list.items;
  const stale =
    selected.length > 0 && selectionRevision !== list.content_revision;
  function select(ids: string[]) {
    if (!selected.length) setSelectionRevision(list.content_revision);
    setSelection(ids);
  }
  const change = useMutation({
    mutationFn: async ({ body, key }: { body: Input; key: string }) =>
      result(
        await api.POST("/api/lists/{list_id}/curation", {
          params: {
            path: { list_id: list.id },
            header: { "idempotency-key": key },
          },
          body,
        }),
      ),
    onSuccess: async (receipt) => {
      setSelection([]);
      setMessage(
        `${receipt.changed} ${receipt.changed === 1 ? "book" : "books"} removed from this list. Library files were kept.`,
      );
      await onChange();
    },
  });
  const reorder = useMutation({
    mutationFn: async ({
      id,
      direction,
    }: {
      id: string;
      direction: number;
    }) => {
      return result(
        await api.POST("/api/lists/{list_id}/move", {
          params: { path: { list_id: list.id } },
          body: {
            work_id: id,
            direction,
            expected_revision: list.content_revision,
          },
        }),
      );
    },
    onSuccess: async () => {
      setMessage("List order saved.");
      await onChange();
    },
  });
  const busy = loading || change.isPending || reorder.isPending || stale;
  function remove(ids: string[]) {
    setMessage("");
    change.mutate({
      body: {
        action: "remove",
        work_ids: ids,
        expected_revision: selected.length
          ? selectionRevision
          : list.content_revision,
      },
      key: crypto.randomUUID(),
    });
  }
  return (
    <section className="list-books" aria-label="List books">
      {editable && (
        <>
          <div className="button-row list-curation-toolbar">
            <button onClick={() => setAdding(!adding)} aria-expanded={adding}>
              {adding ? "Close catalog picker" : "Add books from catalog"}
            </button>
            {list.items.length > 0 && (
              <>
                <button
                  disabled={
                    busy ||
                    Boolean(change.error) ||
                    new Set([...selected, ...shown.map((work) => work.id)])
                      .size > 100
                  }
                  onClick={() =>
                    select([
                      ...new Set([
                        ...selected,
                        ...shown.map((work) => work.id),
                      ]),
                    ])
                  }
                >
                  Select this page
                </button>
                <button
                  disabled={
                    !selected.length || change.isPending || reorder.isPending
                  }
                  onClick={() => setSelection([])}
                >
                  Clear selection
                </button>
                <button
                  disabled={!selected.length || busy || Boolean(change.error)}
                  onClick={() => remove(selected)}
                >
                  Remove selected ({selected.length})
                </button>
              </>
            )}
          </div>
          <p className="muted">
            Select up to 100 books. Removing entries keeps library files and
            other lists; synced entries stay excluded from this list.
          </p>
          {stale && (
            <p role="alert">
              This list changed. Clear your selection and review the current
              books.
            </p>
          )}
          {adding && <CatalogPicker list={list} onChange={onChange} />}
          <Notice error={change.error || reorder.error} />
          {change.error && (
            <div className="button-row">
              <button
                disabled={change.isPending}
                onClick={() => change.mutate(change.variables!)}
              >
                Retry same edit
              </button>
              <button
                disabled={change.isPending}
                onClick={async () => {
                  await onChange();
                  change.reset();
                  setSelection([]);
                }}
              >
                Refresh and clear selection
              </button>
            </div>
          )}
          {reorder.error && (
            <button
              onClick={async () => {
                await onChange();
                reorder.reset();
              }}
            >
              Refresh list order
            </button>
          )}
          {message && <p role="status">{message}</p>}
        </>
      )}
      {shown.length ? (
        <div className="book-grid">
          {shown.map((work, position) => (
            <div key={work.id}>
              {editable && (
                <label className="check-label list-book-selection">
                  <input
                    type="checkbox"
                    aria-label={`Select ${work.title}`}
                    checked={selected.includes(work.id)}
                    disabled={
                      busy ||
                      Boolean(change.error) ||
                      (!selected.includes(work.id) && selected.length >= 100)
                    }
                    onChange={(event) =>
                      select(
                        event.target.checked
                          ? [...selected, work.id]
                          : selected.filter((id) => id !== work.id),
                      )
                    }
                  />
                  Select
                </label>
              )}
              <EnrichedBookCard work={work} />
              {editable && (
                <div className="card-actions">
                  <button
                    className="icon-button"
                    aria-label={`Move ${work.title} earlier`}
                    disabled={
                      filtered ||
                      pageOffset + position === 0 ||
                      busy ||
                      Boolean(change.error)
                    }
                    onClick={() =>
                      reorder.mutate({ id: work.id, direction: -1 })
                    }
                  >
                    <ArrowUp size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Move ${work.title} later`}
                    disabled={
                      filtered ||
                      pageOffset + position === list.count - 1 ||
                      busy ||
                      Boolean(change.error)
                    }
                    onClick={() =>
                      reorder.mutate({ id: work.id, direction: 1 })
                    }
                  >
                    <ArrowDown size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Remove ${work.title} from list`}
                    disabled={busy || Boolean(change.error)}
                    onClick={() => remove([work.id])}
                  >
                    <X size={15} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty
          title={
            filtered
              ? "No matching list books"
              : "This list is ready for a story"
          }
        >
          Add books from your catalog, or find new titles in Discover.
        </Empty>
      )}
      {filtered && editable && (
        <p className="muted">Clear the search to change book order.</p>
      )}
      {list.matched > 50 && (
        <div className="pagination" aria-label="List book pages">
          <button
            disabled={pageOffset === 0 || busy}
            onClick={() => onPage(pageOffset - 50)}
          >
            Previous books
          </button>
          <span role="status">
            {pageOffset + 1}–{pageOffset + shown.length} of {list.matched}
          </span>
          <button
            disabled={pageOffset + 50 >= list.matched || busy}
            onClick={() => onPage(pageOffset + 50)}
          >
            Next books
          </button>
        </div>
      )}
    </section>
  );
}

function CatalogPicker({
  list,
  onChange,
}: {
  list: Detail;
  onChange: () => Promise<unknown>;
}) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const query = useQuery({
    queryKey: ["curation-catalog", list.id, search, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/catalog", {
          params: {
            path: { list_id: list.id },
            query: { q: search, offset, limit: 20 },
          },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
  });
  const existing = new Set(query.data?.member_ids || []);
  const save = useMutation({
    mutationFn: async ({ body, key }: { body: Input; key: string }) =>
      result(
        await api.POST("/api/lists/{list_id}/curation", {
          params: {
            path: { list_id: list.id },
            header: { "idempotency-key": key },
          },
          body,
        }),
      ),
    onSuccess: async (receipt) => {
      setSelected([]);
      setMessage(
        `Added ${receipt.changed} ${receipt.changed === 1 ? "book" : "books"} to this list.`,
      );
      await onChange();
    },
  });
  return (
    <section className="panel editor" aria-label="Add catalog books">
      <h2>Add books from your catalog</h2>
      <p className="muted">
        Adding books to a list with an active automatic policy can acquire
        missing media under that policy.
      </p>
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(text.trim());
          setOffset(0);
        }}
      >
        <label className="grow">
          Find catalog books
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={200}
          />
        </label>
        <button>Search catalog</button>
      </form>
      <Notice error={query.error || save.error} />
      {query.isPending && <Loading />}
      {!query.error && query.data && (
        <>
          {query.data.items.length ? (
            <ul className="list-catalog-results">
              {query.data.items.map((work) => (
                <li key={work.id}>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      aria-label={`Add ${work.title}`}
                      checked={
                        existing.has(work.id) || selected.includes(work.id)
                      }
                      disabled={
                        existing.has(work.id) ||
                        save.isPending ||
                        Boolean(save.error) ||
                        (!selected.includes(work.id) && selected.length >= 100)
                      }
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? [...selected, work.id]
                            : selected.filter((id) => id !== work.id),
                        )
                      }
                    />
                    <span>
                      <strong>{work.title}</strong>
                      <small>
                        {work.authors.join(", ")}
                        {existing.has(work.id) ? " · In this list" : ""}
                        {work.availability.owned ? " · In library" : ""}
                      </small>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p>No matching catalog books. Try another title or author.</p>
          )}
          {query.data.total > 20 && (
            <div className="pagination">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(offset - 20)}
              >
                Previous catalog books
              </button>
              <span>
                {offset + 1}–{offset + query.data.items.length} of{" "}
                {query.data.total}
              </span>
              <button
                disabled={offset + 20 >= query.data.total}
                onClick={() => setOffset(offset + 20)}
              >
                Next catalog books
              </button>
            </div>
          )}
        </>
      )}
      <div className="button-row">
        <button
          className="primary"
          disabled={!selected.length || save.isPending || Boolean(save.error)}
          onClick={() =>
            save.mutate({
              body: { action: "add", work_ids: selected },
              key: crypto.randomUUID(),
            })
          }
        >
          Add selected catalog books ({selected.length})
        </button>
        <button
          disabled={!selected.length || save.isPending}
          onClick={() => setSelected([])}
        >
          Clear catalog selection
        </button>
        {save.error && (
          <>
            <button
              disabled={save.isPending}
              onClick={() => save.mutate(save.variables!)}
            >
              Retry same addition
            </button>
            <button
              disabled={save.isPending}
              onClick={async () => {
                await onChange();
                save.reset();
                setSelected([]);
              }}
            >
              Refresh and clear additions
            </button>
          </>
        )}
      </div>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
