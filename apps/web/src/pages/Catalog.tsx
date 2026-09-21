import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import { BookCard, Empty, Loading, Notice } from "../components";

export default function Catalog({ canEdit }: { canEdit: boolean }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const medium =
    params.get("medium") === "audio"
      ? "audio"
      : params.get("medium") === "ebook"
        ? "ebook"
        : "any";
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const books = usePagedQuery({
    queryKey: ["works", q, medium],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q, medium, offset, limit: 30 } },
          signal,
        }),
      ),
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const add = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const values = new FormData(form);
      return result(
        await api.POST("/api/catalog/works", {
          body: {
            title: String(values.get("title")),
            authors: String(values.get("author")).trim()
              ? [String(values.get("author")).trim()]
              : [],
            description: String(values.get("description")) || null,
          },
        }),
      );
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["works"] });
      setAdding(false);
    },
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <h2>{q ? `Results for “${q}”` : "All saved titles"}</h2>
          <p className="muted">
            Includes books saved from search and lists, even if you do not own a
            copy.
          </p>
        </div>
        {canEdit ? (
          <button className="primary" onClick={() => setAdding(!adding)}>
            {adding ? <X size={17} /> : <Plus size={17} />}
            {adding ? "Close" : "Add a title"}
          </button>
        ) : null}
      </div>
      {adding ? (
        <form
          className="panel editor"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(e.currentTarget);
          }}
        >
          <h2>Add a title</h2>
          <p className="muted">
            Creates a catalog entry. It does not mark a book as downloaded.
          </p>
          <div className="form-row">
            <label>
              Title
              <input name="title" required maxLength={600} autoFocus />
            </label>
            <label>
              Author
              <input name="author" maxLength={300} />
            </label>
          </div>
          <label>
            Description
            <textarea name="description" rows={3} maxLength={30000} />
          </label>
          <Notice error={add.error} />
          <button className="primary" disabled={add.isPending}>
            {add.isPending ? "Saving…" : "Save title"}
          </button>
        </form>
      ) : null}
      <form
        className="library-search"
        onSubmit={(event) => {
          event.preventDefault();
          const next = new URLSearchParams(params);
          const query = String(
            new FormData(event.currentTarget).get("q") || "",
          ).trim();
          if (query) next.set("q", query);
          else next.delete("q");
          next.delete("offset");
          setParams(next);
        }}
      >
        <label>
          Search saved titles
          <input
            key={q}
            name="q"
            defaultValue={q}
            type="search"
            maxLength={300}
            placeholder="Title or author"
          />
        </label>
        <button type="submit">Search saved titles</button>
      </form>
      <div className="library-filters library-shelf-filters">
        <label>
          Format
          <select
            value={medium}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set("medium", event.target.value);
              next.delete("offset");
              setParams(next);
            }}
          >
            <option value="any">Ebooks and audiobooks</option>
            <option value="ebook">Ebooks in library</option>
            <option value="audio">Audiobooks in library</option>
          </select>
        </label>
      </div>
      <Notice error={books.error} />
      {books.isPending ? <Loading /> : null}
      {books.data ? (
        <>
          <div className="section-heading">
            <h2>{q ? "Matching titles" : "All books"}</h2>
            <span className="count">
              {books.data.total} {books.data.total === 1 ? "title" : "titles"}
            </span>
          </div>
          {books.data.items.length ? (
            <div className="book-grid">
              {books.data.items.map((work) => (
                <BookCard key={work.id} work={work} medium={medium} />
              ))}
            </div>
          ) : (
            <Empty
              title={
                q ? "No matching titles" : "A shelf waiting for your first book"
              }
            >
              {q
                ? "Try another title or author."
                : "Add a title to start organizing your reading lists."}
            </Empty>
          )}
          <InfiniteScroll query={books} />
        </>
      ) : null}
    </>
  );
}
