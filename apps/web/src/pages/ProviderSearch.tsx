import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, Search } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { BookCard, Empty, Loading, Notice } from "../components";

type Book = components["schemas"]["BookData"];
type Provider = "hardcover" | "openlibrary";
export const providerName = (provider: string) =>
  provider === "hardcover" ? "Hardcover" : "Open Library";

export default function ProviderSearch({
  canEdit,
  matchWorkId,
  onMatched,
}: {
  canEdit: boolean;
  matchWorkId?: string;
  onMatched?: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const selectedProvider = params.get("provider");
  const provider =
    selectedProvider === "hardcover" || selectedProvider === "openlibrary"
      ? selectedProvider
      : "automatic";
  const page = Math.max(1, Math.min(100, Number(params.get("page")) || 1));
  const [input, setInput] = useState(q);
  const [selected, setSelected] = useState<Book | null>(null);
  const selectedButton = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    setInput(q);
    setSelected(null);
  }, [q, provider, page]);
  const local = useQuery({
    queryKey: ["works", "global-search", q],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q, limit: 6 } },
        }),
      ),
    enabled: !matchWorkId && Boolean(q.trim()),
  });
  const query = useQuery({
    queryKey: ["provider-search", q, provider, page],
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/search", {
          params: { query: { q, provider, page } },
        }),
      ),
    enabled: Boolean(q.trim()),
    retry: false,
  });
  const localIds = new Set(
    ((!matchWorkId && local.data?.items) || []).map((work) => work.id),
  );
  const providerItems =
    query.data?.items.filter((book) => {
      const known = query.data?.known_works?.[book.external_id];
      return matchWorkId || !known || !localIds.has(known.id);
    }) || [];
  return (
    <>
      {!matchWorkId && (
        <div className="page-heading">
          <div>
            <p className="eyebrow">FIND YOUR NEXT BOOK</p>
            <h1>Search books</h1>
            <p className="muted">
              Find books in your collection and discover new titles. Your
              library status stays visible as you browse.
            </p>
          </div>
          <Link to="/metadata">Metadata settings</Link>
        </div>
      )}
      {matchWorkId && <h3>Find the correct catalog record</h3>}
      <form
        className="panel library-filters catalog-search-form"
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(null);
          setParams({ q: input, provider });
        }}
      >
        <label className="grow">
          Title, author or identifier
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            required
            maxLength={300}
          />
          {!matchWorkId && (
            <small>
              Local search also includes known series, ISBNs, ASINs, and IDs
              such as hardcover:42.
            </small>
          )}
        </label>
        <label>
          Catalog provider
          <select
            value={provider}
            onChange={(e) => {
              setSelected(null);
              setParams({ q, provider: e.target.value });
            }}
          >
            <option value="automatic">Automatic</option>
            <option value="hardcover">Hardcover</option>
            <option value="openlibrary">Open Library</option>
          </select>
        </label>
        <button className="primary" disabled={!input.trim()}>
          <Search size={16} />
          Search books
        </button>
      </form>
      {!matchWorkId && q.trim() ? (
        <section className="search-local" aria-label="Matches in your catalog">
          <div className="section-heading">
            <h2>In your catalog</h2>
            {local.data?.total ? (
              <Link to={`/?q=${encodeURIComponent(q)}`}>
                View all {local.data.total} catalog matches →
              </Link>
            ) : null}
          </div>
          <Notice error={local.error} />
          {local.isPending ? <Loading /> : null}
          {local.data?.items.length ? (
            <div className="book-grid">
              {local.data.items.map((work) => (
                <BookCard key={work.id} work={work} />
              ))}
            </div>
          ) : local.data ? (
            <p className="muted">
              No matching titles in your accessible catalog.
            </p>
          ) : null}
        </section>
      ) : null}
      {query.data?.warning && (
        <p className="notice" role="status">
          {query.data.warning}
        </p>
      )}
      <Notice error={query.error} />
      {q && query.isFetching && <Loading />}
      {!q && (
        <Empty title="A title is just the beginning">
          Search by book, author or ISBN. Automatic uses your connected catalog
          with a fallback when needed.
        </Empty>
      )}
      {query.data && (
        <>
          <div className="section-heading">
            <h2>{providerName(query.data.provider)} results</h2>
            <span className="muted">Page {page}</span>
          </div>
          {providerItems.length ? (
            <div className="provider-results">
              {providerItems.map((book) => {
                const known = query.data.known_works?.[book.external_id];
                const content = (
                  <>
                    {book.cover_url ? (
                      <img
                        src={book.cover_url}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <div className="mini-cover">
                        <BookOpen size={24} />
                      </div>
                    )}
                    <span>
                      <strong>{book.title}</strong>
                      <small>
                        {(book.authors || []).join(", ") || "Author unknown"}
                      </small>
                      <small>{book.publication_year || "Year unknown"}</small>
                      {known ? (
                        <SearchAvailability work={known} />
                      ) : (
                        <small>Library match not established</small>
                      )}
                    </span>
                  </>
                );
                return known && !matchWorkId ? (
                  <Link
                    className="provider-result"
                    key={`${book.provider}:${book.external_id}`}
                    to={`/books/${known.id}`}
                  >
                    {content}
                  </Link>
                ) : (
                  <button
                    className="provider-result"
                    key={`${book.provider}:${book.external_id}`}
                    onClick={(event) => {
                      selectedButton.current = event.currentTarget;
                      setSelected(book);
                    }}
                    aria-pressed={
                      selected?.external_id === book.external_id &&
                      selected.provider === book.provider
                    }
                  >
                    {content}
                  </button>
                );
              })}
            </div>
          ) : query.data.items.length ? (
            <p className="muted">
              These results are already shown in your catalog matches above.
            </p>
          ) : (
            <Empty title="No matching books">
              Try a shorter title, another author spelling or a different
              catalog.
            </Empty>
          )}
          <div className="pagination">
            {page > 1 && (
              <button
                onClick={() => {
                  setSelected(null);
                  setParams({ q, provider, page: String(page - 1) });
                }}
              >
                Previous results
              </button>
            )}
            {query.data.has_more && page < 100 && (
              <button
                onClick={() => {
                  setSelected(null);
                  setParams({ q, provider, page: String(page + 1) });
                }}
              >
                Next results
              </button>
            )}
          </div>
        </>
      )}
      {selected && (
        <Preview
          key={`${selected.provider}:${selected.external_id}`}
          provider={selected.provider}
          externalId={selected.external_id}
          canEdit={canEdit}
          matchWorkId={matchWorkId}
          onMatched={onMatched}
          onClose={() => {
            setSelected(null);
            selectedButton.current?.focus();
          }}
        />
      )}
    </>
  );
}

function SearchAvailability({
  work,
}: {
  work: components["schemas"]["WorkView"];
}) {
  return (
    <span className="media-badges">
      <span className={work.availability.owned ? "status owned" : "status"}>
        {work.availability.owned ? (
          <Check size={12} aria-hidden="true" />
        ) : null}
        {work.availability.owned ? "In library" : "In catalog"}
      </span>
      {work.availability.ebook ? <span>Ebook</span> : null}
      {work.availability.audio ? <span>Audio</span> : null}
      {work.availability.stale ? <span>Last known availability</span> : null}
      {work.availability.in_collection ? <span>In collection</span> : null}
    </span>
  );
}

export function Preview({
  provider,
  externalId,
  canEdit,
  matchWorkId,
  onMatched,
  onClose,
}: {
  provider: Provider;
  externalId: string;
  canEdit: boolean;
  matchWorkId?: string;
  onMatched?: () => void;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const previewElement = useRef<HTMLElement | null>(null);
  useEffect(() => {
    previewElement.current?.focus({ preventScroll: true });
    previewElement.current?.scrollIntoView({ block: "start" });
  }, []);
  const client = useQueryClient();
  const preview = useQuery({
    queryKey: ["provider-book", provider, externalId],
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/books/{provider}/{external_id}", {
          params: { path: { provider, external_id: externalId } },
        }),
      ),
    retry: false,
  });
  const save = useMutation({
    mutationFn: async () =>
      matchWorkId
        ? result(
            await api.POST("/api/metadata/works/{work_id}/source", {
              params: { path: { work_id: matchWorkId } },
              body: { provider, external_id: externalId, confirm_match: true },
            }),
          )
        : result(
            await api.POST(
              "/api/metadata/books/{provider}/{external_id}/import",
              { params: { path: { provider, external_id: externalId } } },
            ),
          ),
    onSuccess: (work) => {
      client.invalidateQueries({ queryKey: ["works"] });
      client.invalidateQueries({ queryKey: ["discovery"] });
      client.invalidateQueries({ queryKey: ["provider-search"] });
      client.invalidateQueries({ queryKey: ["provider-book"] });
      if (matchWorkId) {
        onMatched?.();
        onClose();
      } else navigate(`/books/${work.id}`);
    },
  });
  const book = preview.data?.book;
  return (
    <section
      ref={previewElement}
      tabIndex={-1}
      className="panel catalog-preview"
      aria-label="Catalog preview"
    >
      <div className="section-heading">
        <p className="eyebrow">{providerName(provider)} · PREVIEW</p>
        <button onClick={onClose}>Close preview</button>
      </div>
      <Notice error={preview.error || save.error} />
      {preview.isPending && <Loading />}
      {preview.data?.warning && (
        <p className="notice">{preview.data.warning}</p>
      )}
      {book && (
        <>
          <h2>{book.title}</h2>
          <p>{(book.authors || []).join(", ")}</p>
          <p className="description">
            {book.description || "No description provided."}
          </p>
          {(book.series || []).length > 0 && (
            <p className="muted">
              {(book.series || [])
                .map(
                  (series) =>
                    `${series.name}${series.position ? ` · Book ${series.position}` : ""}`,
                )
                .join("; ")}
            </p>
          )}
          <p>
            {(book.editions || []).length} catalog editions loaded
            {book.editions_more ? " · More editions exist at the provider" : ""}
            .
          </p>
          <p className="muted">
            Adding a catalog title does not download it or mark it as owned.
          </p>
          {preview.data?.work && !matchWorkId ? (
            <>
              <SearchAvailability work={preview.data.work} />
              <Link className="back-link" to={`/books/${preview.data.work.id}`}>
                Open existing book →
              </Link>
            </>
          ) : null}
          {canEdit && (matchWorkId || !preview.data?.work) && (
            <button
              className="primary"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending
                ? "Saving…"
                : matchWorkId
                  ? "Confirm catalog match"
                  : "Add to catalog"}
            </button>
          )}
        </>
      )}
    </section>
  );
}
