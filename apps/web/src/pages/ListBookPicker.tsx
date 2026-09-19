import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";

export default function ListBookPicker({
  listId,
  selected,
  onChange,
  maximum,
  label,
  onValidityChange,
  onRevisionChange,
}: {
  listId: string;
  selected: string[];
  onChange: (ids: string[]) => void;
  maximum: number;
  label: string;
  onValidityChange: (valid: boolean) => void;
  onRevisionChange: (revision: string | undefined) => void;
}) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState<string>();
  const books = useQuery({
    queryKey: ["list-books", listId, search, offset, revision],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}", {
          params: {
            path: { list_id: listId },
            query: {
              q: search,
              offset,
              limit: 25,
              expected_revision: revision,
            },
          },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    refetchInterval: 15_000,
  });
  const valid = books.isSuccess && !books.isFetching;
  useEffect(() => {
    onValidityChange(valid);
  }, [valid, onValidityChange]);
  useEffect(() => {
    onRevisionChange(revision);
  }, [revision, onRevisionChange]);
  const combined = [
    ...new Set([...selected, ...(books.data?.items.map((w) => w.id) || [])]),
  ];
  const change = (ids: string[]) => {
    if (!revision && ids.length) setRevision(books.data?.content_revision);
    if (!ids.length) setRevision(undefined);
    onChange(ids);
  };
  return (
    <section aria-label={label}>
      <label>
        {label}
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <p>
        {selected.length} selected · {books.data?.matched ?? "…"} matching books
      </p>
      <div className="button-row">
        <button
          type="button"
          disabled={
            !valid || !books.data?.items.length || combined.length > maximum
          }
          onClick={() => change(combined)}
        >
          Select this page
        </button>
        <button
          type="button"
          disabled={!selected.length}
          onClick={() => change([])}
        >
          Clear selection
        </button>
      </div>
      <Notice error={books.error} />
      {books.error && (
        <button
          type="button"
          onClick={() => {
            change([]);
            setOffset(0);
            void books.refetch();
          }}
        >
          Refresh books and clear selection
        </button>
      )}
      {books.isPending && <Loading />}
      {!books.error && books.data && (
        <>
          {books.data.items.map((work) => (
            <label className="check-label" key={work.id}>
              <input
                type="checkbox"
                checked={selected.includes(work.id)}
                disabled={
                  !valid ||
                  (!selected.includes(work.id) && selected.length >= maximum)
                }
                onChange={(event) =>
                  change(
                    event.target.checked
                      ? [...selected, work.id]
                      : selected.filter((id) => id !== work.id),
                  )
                }
              />
              {work.title} {work.availability.owned ? "· In library" : ""}
            </label>
          ))}
          {!books.data.items.length && <p>No matching books in this list.</p>}
          <div className="pagination">
            <button
              type="button"
              disabled={!offset || !valid}
              onClick={() => setOffset(offset - 25)}
            >
              Previous books
            </button>
            <span>
              Page {Math.floor(offset / 25) + 1} of{" "}
              {Math.max(1, Math.ceil(books.data.matched / 25))}
            </span>
            <button
              type="button"
              disabled={offset + 25 >= books.data.matched || !valid}
              onClick={() => setOffset(offset + 25)}
            >
              Next books
            </button>
          </div>
        </>
      )}
    </section>
  );
}
