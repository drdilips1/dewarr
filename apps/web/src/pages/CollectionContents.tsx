import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import IdentityHistory from "./IdentityHistory";

type Asset = components["schemas"]["AssetView"];

export default function CollectionContents({
  asset,
  close,
}: {
  asset: Asset;
  close: () => void;
}) {
  const cache = useQueryClient();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(
    () =>
      new Map((asset.contents || []).map((book) => [book.work_id, book.title])),
  );
  const [confirmed, setConfirmed] = useState(false);
  const books = useQuery({
    queryKey: ["collection-search", search],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q: search, limit: 50 } },
        }),
      ),
    enabled: search.trim().length > 1,
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/library/assets/{asset_id}/contents", {
          params: { path: { asset_id: asset.id } },
          body: {
            work_ids: [...selected.keys()],
            expected_revision: asset.match_revision!,
            complete_books_confirmed: true,
          },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries();
      close();
    },
  });
  function toggle(id: string, title: string) {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(id)) next.delete(id);
      else next.set(id, title);
      return next;
    });
    setConfirmed(false);
  }
  return (
    <form
      className="panel editor"
      aria-label="Collection contents review"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Contents of {asset.title}</h2>
      <p className="muted">
        Verify the complete books in this single Audiobookshelf item. They will
        share its Open link. This does not split files or identify a separate
        edition or narrator for each book.
      </p>
      <p>
        <a href={asset.open_url} target="_blank" rel="noreferrer">
          Open collection in Audiobookshelf
        </a>
      </p>
      <Notice error={books.error || save.error} />
      <label>
        Find a book in your catalog
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {books.data && (
        <fieldset>
          <legend>Search results</legend>
          {books.data.items.map((book) => (
            <label className="check-label" key={book.id}>
              <input
                type="checkbox"
                checked={selected.has(book.id)}
                onChange={() => toggle(book.id, book.title)}
              />
              {book.title} — {book.authors.join(", ") || "Unknown author"}
            </label>
          ))}
          {!books.data.items.length && <p>No matching catalog books.</p>}
          {books.data.total > 50 && (
            <p>Narrow the search to see more matches.</p>
          )}
        </fieldset>
      )}
      <h3>Selected books ({selected.size})</h3>
      {[...selected].map(([id, title]) => (
        <p key={id}>
          {title}{" "}
          <button
            type="button"
            onClick={() => toggle(id, title)}
            aria-label={`Remove ${title}`}
          >
            Remove
          </button>
        </p>
      ))}
      <label className="check-label">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I checked this item and each selected book is complete, not an excerpt,
        sample or companion.
      </label>
      <p className="muted">
        File or metadata changes require a new review. Standalone and
        exact-version requests remain separate.
      </p>
      <div className="button-row">
        <button
          className="primary"
          disabled={
            !confirmed ||
            selected.size < 2 ||
            selected.size > 100 ||
            !asset.match_revision ||
            save.isPending
          }
        >
          Confirm collection contents
        </button>
        <button type="button" onClick={close} disabled={save.isPending}>
          Cancel
        </button>
      </div>
      <IdentityHistory entityId={asset.id} onChanged={close} />
    </form>
  );
}
