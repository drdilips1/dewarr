import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Selection = components["schemas"]["GroupSelection"];

export default function ImportCollectionContents({
  selection,
  disabled,
  onChange,
}: {
  selection: Selection;
  disabled: boolean;
  onChange: (value: Selection) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [labels, setLabels] = useState<Record<string, string>>({});
  const ids = selection.contained_work_ids || [];
  const books = useQuery({
    queryKey: ["import-contained-books", search],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q: search, limit: 50 } },
        }),
      ),
    enabled: open && search.trim().length > 1,
  });
  function toggle(id: string, title: string) {
    setLabels((current) => ({ ...current, [id]: title }));
    onChange({
      ...selection,
      contained_work_ids: ids.includes(id)
        ? ids.filter((value) => value !== id)
        : [...ids, id],
      contents_confirmed: false,
    });
  }
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Books contained in this collection (optional)</summary>
      <p className="muted">
        Use the catalog edition of the whole omnibus above. Select only the
        complete books inside these files. The library will have one item; no
        child files or editions will be created.
      </p>
      <label>
        Find contained books
        <input
          value={search}
          disabled={disabled}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <Notice error={books.error} />
      {books.data && (
        <fieldset>
          <legend>Contained book results</legend>
          {books.data.items
            .filter((book) => book.id !== selection.work_id)
            .map((book) => (
              <label className="check-label" key={book.id}>
                <input
                  type="checkbox"
                  disabled={
                    disabled || (!ids.includes(book.id) && ids.length >= 100)
                  }
                  checked={ids.includes(book.id)}
                  onChange={() => toggle(book.id, book.title)}
                />
                {book.title} — {book.authors.join(", ") || "Unknown author"}
              </label>
            ))}
          {books.data.total > 50 && (
            <p>Narrow your search to see more results.</p>
          )}
        </fieldset>
      )}
      <p>Selected contents ({ids.length})</p>
      {ids.map((id) => (
        <p key={id}>
          {labels[id] || "Selected book"}{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() => toggle(id, labels[id] || "Selected book")}
          >
            Remove
          </button>
        </p>
      ))}
      {!!ids.length && (
        <label className="check-label">
          <input
            type="checkbox"
            disabled={disabled || ids.length < 2 || !selection.full_content}
            checked={!!selection.contents_confirmed}
            onChange={(event) =>
              onChange({
                ...selection,
                contents_confirmed: event.target.checked,
              })
            }
          />
          I checked these files and every selected contained book is complete.
        </label>
      )}
      {!!ids.length && (
        <p className="muted">
          Ownership appears only after Audiobookshelf confirms this item. The
          collection's narrator and edition do not identify its individual
          books.
        </p>
      )}
    </details>
  );
}
