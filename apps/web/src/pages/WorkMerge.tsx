import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, result, type Work } from "../api/client";
import { Notice } from "../components";
import { useRefreshIdentity } from "./IdentityHistory";

export default function WorkMerge({ work }: { work: Work }) {
  const [open, setOpen] = useState(false);
  return open ? (
    <MergeForm work={work} close={() => setOpen(false)} />
  ) : (
    <button type="button" onClick={() => setOpen(true)}>
      Merge duplicate book
    </button>
  );
}

function MergeForm({ work, close }: { work: Work; close: () => void }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<Work | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const previewRegion = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const refresh = useRefreshIdentity();
  useEffect(() => inputRef.current?.focus(), []);
  const search = useQuery({
    queryKey: ["works", "merge-search", query],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q: query, limit: 20 } },
        }),
      ),
    enabled: !!query,
  });
  const preview = useQuery({
    queryKey: ["merge-preview", work.id, target?.id],
    queryFn: async () =>
      result(
        await api.POST("/api/identity/works/merge/preview", {
          body: { source_id: work.id, target_id: target!.id },
        }),
      ),
    enabled: !!target,
    retry: false,
  });
  useEffect(() => {
    if (preview.data) previewRegion.current?.focus();
  }, [preview.data]);
  const merge = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/identity/works/merge", {
          body: {
            source_id: work.id,
            target_id: target!.id,
            expected_revision: preview.data!.revision,
          },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      navigate(`/books/${target!.id}`);
      close();
    },
  });
  return (
    <section
      className="panel editor library-access"
      aria-label="Merge duplicate book"
    >
      <h2>Merge duplicate book</h2>
      <p>
        Combine <strong>{work.title}</strong> with another record of the same
        book. Keep the selected book's title and metadata.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(input.trim());
        }}
      >
        <label>
          Find the book to keep
          <input
            ref={inputRef}
            value={input}
            maxLength={300}
            required
            disabled={merge.isPending}
            onChange={(event) => setInput(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!input.trim() || merge.isPending}>
          Find duplicate
        </button>
      </form>
      {search.isFetching && <p className="muted">Searching your catalog…</p>}
      {search.data && (
        <div className="activity-list">
          {search.data.items
            .filter((item) => item.id !== work.id)
            .map((item) => (
              <button
                type="button"
                key={item.id}
                disabled={merge.isPending}
                onClick={() => {
                  setTarget(item);
                  setConfirmed(false);
                  merge.reset();
                }}
              >
                Keep {item.title} ·{" "}
                {item.authors.join(", ") || "Unknown author"}
              </button>
            ))}
          {!search.data.items.some((item) => item.id !== work.id) && (
            <p>
              No other matching book found. Try a different title or author.
            </p>
          )}
          {search.data.total > 20 && (
            <p className="muted">
              Showing the first matches. Refine your search to find the intended
              book.
            </p>
          )}
        </div>
      )}
      <Notice error={search.error || preview.error || merge.error} />
      {target && preview.isPending && (
        <p className="muted">Checking the affected records…</p>
      )}
      {preview.data && (
        <div
          ref={previewRegion}
          tabIndex={-1}
          role="region"
          aria-label="Merge preview"
        >
          <h3>
            {preview.data.source_title} → {preview.data.target_title}
          </h3>
          <p>
            {preview.data.counts.versions} versions,{" "}
            {preview.data.counts.library_copies} library copies,{" "}
            {preview.data.counts.list_memberships} of your list memberships and{" "}
            {preview.data.counts.requests} of your requests will join the
            selected book.
          </p>
          <p className="muted">
            Recordings stay distinct and private library access stays
            restricted. Files and playback progress stay in place. Undo in Match
            correction history restores the original book groups; later
            additions stay with the record they were added to.
          </p>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={merge.isPending}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            These records describe the same book
          </label>
          <button
            type="button"
            className="primary"
            disabled={!confirmed || preview.isFetching || merge.isPending}
            onClick={() => merge.mutate()}
          >
            {merge.isPending ? "Merging…" : "Merge into selected book"}
          </button>
        </div>
      )}
      <button type="button" disabled={merge.isPending} onClick={close}>
        Close merge
      </button>
    </section>
  );
}
