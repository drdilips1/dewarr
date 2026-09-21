import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Search } from "lucide-react";
import { api, result, type Work } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import BookCover from "../components/BookCover";
import ProviderSearch, { Preview } from "./ProviderSearch";

type Source = components["schemas"]["SourceView"];
type Book = components["schemas"]["BookData"];

export default function BookMatch({
  work,
  source,
  admin,
  updated,
}: {
  work: Work;
  source?: Source;
  admin: boolean;
  updated: () => void;
}) {
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Book | null>(null);
  const match = useQuery({
    queryKey: ["work-reader-match", work.id],
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/works/{work_id}/reader-match", {
          params: { path: { work_id: work.id } },
        }),
      ),
    enabled: !source,
    retry: false,
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/metadata/works/{work_id}/match-hardcover", {
          params: { path: { work_id: work.id } },
        }),
      ),
    onSuccess: (value) => {
      updated();
      if (value.status !== "matched") match.refetch();
    },
  });
  const choices = match.data?.book
    ? [match.data.book]
    : match.data?.candidates || [];
  const done = () => {
    setSelected(null);
    setSearching(false);
    updated();
  };
  return (
    <section className="book-match" aria-label="Book match">
      <div className="book-match-heading">
        <div>
          <span className="eyebrow">CATALOG MATCH</span>
          <h2>{source ? "Connected to Hardcover" : "Choose the right book"}</h2>
          <p className="muted">
            {source
              ? "Description, authors and reviews come from this book."
              : "Connect your library copy to its description, authors and reviews."}
          </p>
        </div>
        {admin && (
          <button
            onClick={() => setSearching(!searching)}
            aria-expanded={searching}
          >
            <Search size={16} />{" "}
            {searching
              ? "Close search"
              : source
                ? "Change match"
                : "Search books"}
          </button>
        )}
      </div>
      {source && (
        <div className="book-match-connected">
          <Check size={18} />
          <strong>{source.title}</strong>
          <span className="muted">Hardcover · {source.external_id}</span>
        </div>
      )}
      {!source && !searching && (
        <>
          {match.isFetching && (
            <p role="status" className="muted">
              Finding matching books…
            </p>
          )}
          <Notice error={match.error || save.error} />
          {!match.isFetching && choices.length > 1 && (
            <p className="muted">
              These records may fit. Compare the details before choosing.
            </p>
          )}
          <div className="book-match-choices">
            {choices.map((book) => (
              <article
                className="book-match-choice"
                key={`${book.provider}:${book.external_id}`}
              >
                <div className="book-match-cover">
                  <BookCover title={book.title} cover={book.cover_url} />
                </div>
                <div className="book-match-copy">
                  <h3>{book.title}</h3>
                  <p>{(book.authors || []).join(", ")}</p>
                  <small className="muted">
                    {[book.publication_year, `Hardcover ${book.external_id}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                  {book.description && (
                    <p className="book-match-description">{book.description}</p>
                  )}
                  {admin &&
                    (match.data?.status === "matched" ? (
                      <button
                        className="primary"
                        disabled={save.isPending}
                        onClick={() => save.mutate()}
                      >
                        {save.isPending ? "Connecting…" : "Use verified match"}
                      </button>
                    ) : (
                      <button onClick={() => setSelected(book)}>
                        Compare this book
                      </button>
                    ))}
                </div>
              </article>
            ))}
          </div>
          {!match.isFetching && !choices.length && !match.error && (
            <p className="muted">
              {match.data?.status === "disabled"
                ? "Automatic matching is off for this book. Search to choose a match."
                : "No verified match yet. Search by title, author or ISBN to choose the correct book."}
            </p>
          )}
        </>
      )}
      {searching && (
        <div className="book-match-search">
          <ProviderSearch
            canEdit={admin}
            matchWorkId={work.id}
            initialQuery={`${work.title} ${work.authors[0] || ""}`}
            onMatched={done}
          />
        </div>
      )}
      {selected && (
        <Preview
          provider={selected.provider}
          externalId={selected.external_id}
          canEdit={admin}
          matchWorkId={work.id}
          onMatched={done}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}
