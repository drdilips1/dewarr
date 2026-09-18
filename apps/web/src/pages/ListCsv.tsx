import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Preview = components["schemas"]["CsvPreview"];
const fields = [
  ["title", "Title column"],
  ["author", "Author column"],
  ["goodreads_id", "Goodreads ID column"],
  ["isbn", "ISBN column"],
  ["isbn13", "ISBN-13 column"],
  ["shelves", "Shelves column"],
  ["exclusive_shelf", "Exclusive shelf column"],
] as const;

export default function ListCsv({ listId }: { listId: string }) {
  const client = useQueryClient();
  const path = { list_id: listId };
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState<"auto" | "utf-8-sig" | "cp1252">(
    "auto",
  );
  const [delimiter, setDelimiter] = useState<"," | ";" | "\t">(",");
  const [mapping, setMapping] = useState<Record<string, string> | undefined>();
  const [id, setId] = useState<string | null>(null);
  const [unmapped, setUnmapped] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<number[] | null>(null);
  const [shelf, setShelf] = useState("");
  const [page, setPage] = useState(0);
  const [dirty, setDirty] = useState(false);
  const history = useQuery({
    queryKey: ["csv-history", listId],
    queryFn: async () =>
      result(await api.GET("/api/lists/{list_id}/csv", { params: { path } })),
  });
  const saved = useQuery({
    queryKey: ["csv-preview", listId, id],
    enabled: Boolean(id),
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/csv/{import_id}", {
          params: { path: { ...path, import_id: id! } },
        }),
      ),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state || "")
        ? 1000
        : false,
  });
  const value = id ? saved.data : unmapped;
  const busy = ["queued", "running"].includes(value?.state || "");
  const rows =
    selected ??
    value?.selected_rows ??
    value?.records.filter((r) => !r.issue).map((r) => r.row_number) ??
    [];
  const chosen = new Set(rows);
  const filtered =
    value?.records.filter((r) => !shelf || r.shelves.includes(shelf)) ?? [];
  const frozen = value?.selected_rows != null;
  const preview = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a CSV file first");
      if (file.size > 4 * 1024 * 1024)
        throw new Error("CSV files must be no larger than 4 MiB");
      return result(
        await api.POST("/api/lists/{list_id}/csv/preview", {
          params: {
            path,
            query: {
              encoding,
              delimiter,
              mapping: mapping ? JSON.stringify(mapping) : undefined,
            },
          },
          headers: { "Content-Type": "text/csv" },
          body: "",
          bodySerializer: () => file,
        }),
      );
    },
    onSuccess: (data) => {
      setMapping(data.mapping);
      setSelected(null);
      setShelf("");
      setPage(0);
      setDirty(false);
      setId(data.id);
      setUnmapped(data.id ? null : data);
      if (data.id) client.setQueryData(["csv-preview", listId, data.id], data);
      client.invalidateQueries({ queryKey: ["csv-history", listId] });
    },
  });
  const commit = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/csv/{import_id}/commit", {
          params: { path: { ...path, import_id: id! } },
          body: { rows },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["csv-preview", listId, id] });
      client.invalidateQueries({ queryKey: ["csv-history", listId] });
    },
  });
  useEffect(() => {
    if (value?.state === "completed") {
      client.invalidateQueries({ queryKey: ["list", listId] });
      client.invalidateQueries({ queryKey: ["lists"] });
      client.invalidateQueries({ queryKey: ["catalog"] });
      client.invalidateQueries({ queryKey: ["csv-history", listId] });
    }
  }, [client, listId, value?.state]);
  return (
    <section className="panel" aria-label="CSV list import">
      <h2>Import a CSV snapshot</h2>
      <p className="muted">
        Add books to this list from a Goodreads export or mapped CSV. Existing
        books stay in place. This does not start downloads or mark books as read
        or owned.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          preview.mutate();
        }}
      >
        <label>
          CSV file
          <input
            type="file"
            accept=".csv,text/csv,text/tab-separated-values"
            disabled={busy || preview.isPending}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setId(null);
              setUnmapped(null);
              setMapping(undefined);
              setSelected(null);
              setDirty(true);
              commit.reset();
              preview.reset();
            }}
          />
        </label>
        <p className="muted">
          Up to 4 MiB and 2,000 rows per snapshot. UTF-8 and UTF-16 with a
          byte-order mark are detected automatically.
        </p>
        <details>
          <summary>File format and columns</summary>
          <label>
            File encoding
            <select
              value={encoding}
              disabled={busy}
              onChange={(e) => {
                setEncoding(e.target.value as typeof encoding);
                setDirty(true);
              }}
            >
              <option value="auto">Automatic (UTF-8 / UTF-16)</option>
              <option value="utf-8-sig">UTF-8</option>
              <option value="cp1252">Windows-1252</option>
            </select>
          </label>
          <label>
            Column separator
            <select
              value={delimiter}
              disabled={busy}
              onChange={(e) => {
                setDelimiter(e.target.value as typeof delimiter);
                setDirty(true);
              }}
            >
              <option value=",">Comma</option>
              <option value=";">Semicolon</option>
              <option value={"\t"}>Tab</option>
            </select>
          </label>
          {value?.headers.length
            ? fields.map(([field, label]) => (
                <label key={field}>
                  {label}
                  <select
                    value={(mapping ?? value.mapping)[field] ?? ""}
                    disabled={busy}
                    onChange={(e) => {
                      const next = { ...(mapping ?? value.mapping) };
                      if (e.target.value) next[field] = e.target.value;
                      else delete next[field];
                      setMapping(next);
                      setDirty(true);
                    }}
                  >
                    <option value="">
                      {field === "title"
                        ? "Choose a title column"
                        : "Not imported"}
                    </option>
                    {value.headers.map((header) => (
                      <option key={header} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                </label>
              ))
            : null}
        </details>
        <button disabled={!file || busy || preview.isPending}>
          {preview.isPending ? "Reading CSV…" : "Preview CSV"}
        </button>
      </form>
      <Notice
        error={preview.error || saved.error || commit.error || history.error}
      />
      {id && saved.isPending ? <Loading /> : null}
      {value ? (
        <>
          <p role="status">{value.message}</p>
          {value.needs_mapping ? (
            <p>
              Open File format and columns, choose the title column, then
              preview again.
            </p>
          ) : (
            <>
              <p className="muted">
                {value.records.length} unique rows · {value.duplicates}{" "}
                duplicate rows combined. Reviews, ratings, notes and owned-copy
                counts are not imported.
              </p>
              {dirty ? (
                <p>Preview the changed file or columns before importing.</p>
              ) : null}
              {value.receipt ? (
                <p>
                  {value.receipt.added} books added;{" "}
                  {value.receipt.already_listed} already in this list. No
                  existing books were removed.
                </p>
              ) : (
                <>
                  <label>
                    Filter CSV shelf
                    <select
                      value={shelf}
                      disabled={busy}
                      onChange={(e) => {
                        setShelf(e.target.value);
                        setPage(0);
                      }}
                    >
                      <option value="">All shelves</option>
                      {value.shelves.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="card-actions">
                    <button
                      disabled={frozen || busy}
                      onClick={() =>
                        setSelected(
                          filtered
                            .filter((r) => !r.issue)
                            .map((r) => r.row_number),
                        )
                      }
                    >
                      {shelf ? "Select this shelf only" : "Select all books"}
                    </button>
                    <button
                      disabled={frozen || busy}
                      onClick={() => setSelected([])}
                    >
                      Clear selection
                    </button>
                  </div>
                  <p>{rows.length} books selected across all shelves.</p>
                  {filtered.slice(page * 20, page * 20 + 20).map((row) => (
                    <div className="panel" key={row.row_number}>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          aria-label={`Import ${row.title}`}
                          checked={chosen.has(row.row_number)}
                          disabled={Boolean(row.issue) || frozen || busy}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...rows, row.row_number]
                                : rows.filter((n) => n !== row.row_number),
                            )
                          }
                        />
                        {row.title}
                      </label>
                      <p className="muted">
                        {row.authors.join(", ") || "Author not supplied"} · CSV
                        row {row.row_number}
                      </p>
                      {row.issue ? (
                        <p>{row.issue}</p>
                      ) : row.work_id ? (
                        <p>
                          <Link to={`/books/${row.work_id}`}>
                            Matched catalog book
                          </Link>{" "}
                          ·{" "}
                          {row.availability?.owned
                            ? "In your library"
                            : "Not confirmed in library"}
                        </p>
                      ) : (
                        <p className="muted">
                          New provisional catalog book; no library ownership
                          assumed.
                        </p>
                      )}
                    </div>
                  ))}
                  {filtered.length > 20 ? (
                    <div className="card-actions">
                      <button
                        disabled={page === 0}
                        onClick={() => setPage(page - 1)}
                      >
                        Previous CSV rows
                      </button>
                      <span>
                        Page {page + 1} of {Math.ceil(filtered.length / 20)}
                      </span>
                      <button
                        disabled={(page + 1) * 20 >= filtered.length}
                        onClick={() => setPage(page + 1)}
                      >
                        Next CSV rows
                      </button>
                    </div>
                  ) : null}
                  <button
                    className="primary"
                    disabled={
                      !id || !rows.length || dirty || busy || commit.isPending
                    }
                    onClick={() => commit.mutate()}
                  >
                    {busy
                      ? "Importing selected books…"
                      : value.state === "failed"
                        ? "Retry saved CSV import"
                        : `Import ${rows.length} selected books`}
                  </button>
                </>
              )}
            </>
          )}
        </>
      ) : null}
      {history.data?.length ? (
        <details>
          <summary>Recent CSV previews and imports</summary>
          <ul>
            {history.data.map((item) => (
              <li key={item.id}>
                <button
                  disabled={busy}
                  onClick={() => {
                    setId(item.id);
                    setUnmapped(null);
                    setSelected(null);
                    setMapping(undefined);
                    setShelf("");
                    setPage(0);
                    setDirty(false);
                    commit.reset();
                  }}
                >
                  {item.message} · {item.state}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
