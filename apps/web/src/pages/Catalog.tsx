import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import { BookCard, Empty, Loading, Notice } from "../components";

export default function Catalog({ canEdit }: { canEdit: boolean }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const books = useQuery({
    queryKey: ["works", q, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q, offset, limit: 30 } },
        }),
      ),
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
          <p className="eyebrow">BOOKS, IN ONE PLACE</p>
          <h1>{q ? `Results for “${q}”` : "Your catalog"}</h1>
          <p className="muted">
            Keep the titles you love close, and your next read closer.
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
                <BookCard key={work.id} work={work} />
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
          <div className="pagination">
            {offset > 0 ? (
              <button
                onClick={() =>
                  setParams({ q, offset: String(Math.max(0, offset - 30)) })
                }
              >
                Previous
              </button>
            ) : null}
            {offset + 30 < books.data.total ? (
              <button
                onClick={() => setParams({ q, offset: String(offset + 30) })}
              >
                Next
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  );
}
