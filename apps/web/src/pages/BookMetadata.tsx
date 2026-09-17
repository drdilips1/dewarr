import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Work } from "../api/client";
import type { components } from "../api/schema";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import ProviderSearch, { providerName } from "./ProviderSearch";
import { fieldLabel } from "./MetadataSettings";

type Edit = components["schemas"]["EditValues"];
type Field =
  | "title"
  | "authors"
  | "description"
  | "publication_year"
  | "language"
  | "cover_url";

export default function BookMetadata({
  work,
  admin,
}: {
  work: Work;
  admin: boolean;
}) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [matching, setMatching] = useState(false);
  const [editing, setEditing] = useState(false);
  const metadata = useQuery({
    queryKey: ["work-metadata", work.id, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/works/{work_id}", {
          params: { path: { work_id: work.id }, query: { offset, limit: 20 } },
        }),
      ),
  });
  const updated = () => {
    client.invalidateQueries({ queryKey: ["work", work.id] });
    client.invalidateQueries({ queryKey: ["work-metadata", work.id] });
    client.invalidateQueries({ queryKey: ["works"] });
  };
  const refresh = useMutation({
    mutationFn: async (source: {
      provider: "hardcover" | "openlibrary";
      external_id: string;
    }) =>
      result(
        await api.POST("/api/metadata/works/{work_id}/source", {
          params: { path: { work_id: work.id } },
          body: { ...source, confirm_match: false },
        }),
      ),
    onSuccess: updated,
  });
  const edit = useMutation({
    mutationFn: async (body: { values?: Edit; unlock?: Field[] }) =>
      result(
        await api.PATCH("/api/metadata/works/{work_id}", {
          params: { path: { work_id: work.id } },
          body,
        }),
      ),
    onSuccess: () => {
      updated();
      setEditing(false);
    },
  });
  const more = useMutation({
    mutationFn: async (source: {
      provider: "hardcover" | "openlibrary";
      external_id: string;
    }) =>
      result(
        await api.POST("/api/metadata/works/{work_id}/source/editions", {
          params: { path: { work_id: work.id } },
          body: { ...source, confirm_match: false },
        }),
      ),
    onSuccess: updated,
  });
  return (
    <section className="library-access">
      <div className="section-heading">
        <h2>Editions and recordings</h2>
        {admin && (
          <button onClick={() => setMatching(!matching)}>
            {matching ? "Close catalog matching" : "Match a catalog source"}
          </button>
        )}
      </div>
      <Notice
        error={metadata.error || refresh.error || edit.error || more.error}
      />
      {matching && (
        <div className="panel">
          <ProviderSearch
            canEdit
            matchWorkId={work.id}
            onMatched={() => {
              updated();
              setMatching(false);
            }}
          />
        </div>
      )}
      {metadata.isPending && <Loading />}
      {metadata.data && (
        <>
          {metadata.data.versions.length === 0 && (
            <p className="muted">
              No catalog editions have been linked yet. Library copies appear
              below.
            </p>
          )}
          <div className="edition-grid">
            {metadata.data.versions.map((version) => (
              <article className="panel edition-card" key={version.id}>
                <div className="section-heading">
                  <strong>
                    {version.medium === "audio"
                      ? "Audiobook"
                      : version.medium === "ebook"
                        ? "Ebook"
                        : version.medium === "print"
                          ? "Print edition"
                          : "Format unknown"}
                  </strong>
                  {version.owned && (
                    <span className="status owned">In library</span>
                  )}
                </div>
                <h3>{version.title || work.title}</h3>
                <p>
                  {version.narrators.length
                    ? `Narrated by ${version.narrators.join(", ")}`
                    : version.medium === "audio"
                      ? "Narrator unknown"
                      : ""}
                </p>
                <p className="muted">
                  {[version.language, version.publication_year]
                    .filter(Boolean)
                    .join(" · ") || "Edition details unavailable"}
                </p>
                {version.needs_review && (
                  <p className="notice">
                    Provider details changed. The existing version was preserved
                    for review.
                  </p>
                )}
              </article>
            ))}
          </div>
          <div className="pagination">
            {offset > 0 && (
              <button onClick={() => setOffset(Math.max(0, offset - 20))}>
                Previous editions
              </button>
            )}
            {offset + 20 < metadata.data.versions_total && (
              <button onClick={() => setOffset(offset + 20)}>
                Next editions
              </button>
            )}
          </div>
          {metadata.data.sources.some((source) => source.editions_more) && (
            <p className="muted">
              This catalog contains more editions than have been loaded. Listed
              editions are not a complete catalog.
            </p>
          )}
          {metadata.data.sources.map((source) => (
            <div
              className="source-attribution"
              key={`${source.provider}:${source.external_id}`}
            >
              <span>
                <strong>{providerName(source.provider)}</strong> ·{" "}
                {source.title}
                <small>
                  Fetched {new Date(source.fetched_at).toLocaleString()}
                </small>
                {source.series.map((series) => (
                  <small key={series.external_id}>
                    {series.name}
                    {series.position ? ` · Book ${series.position}` : ""}
                  </small>
                ))}
              </span>
              {admin && (
                <button
                  disabled={refresh.isPending || more.isPending}
                  onClick={() => refresh.mutate(source)}
                >
                  Refresh {providerName(source.provider)}
                </button>
              )}
              {admin && source.editions_more && (
                <button
                  disabled={more.isPending || refresh.isPending}
                  onClick={() => more.mutate(source)}
                >
                  {more.isPending
                    ? "Loading editions…"
                    : `Load more ${providerName(source.provider)} editions`}
                </button>
              )}
            </div>
          ))}
          <details className="panel provenance">
            <summary>Metadata sources and protected edits</summary>
            {Object.entries(metadata.data.fields).length === 0 && (
              <p className="muted">No provider metadata has been selected.</p>
            )}
            {Object.entries(metadata.data.fields).map(([field, raw]) => {
              const value = raw as {
                provider?: string;
                reason?: string;
                locked?: boolean;
              };
              return (
                <div className="source-attribution" key={field}>
                  <span>
                    <strong>{fieldLabel(field)}</strong>
                    <small>
                      {value.provider === "manual"
                        ? "Your edit"
                        : providerName(value.provider || "")}
                      {value.locked ? " · Protected" : ""}
                    </small>
                    <small>{value.reason}</small>
                  </span>
                  {admin && value.locked && (
                    <button
                      onClick={() => edit.mutate({ unlock: [field as Field] })}
                      disabled={edit.isPending}
                    >
                      Use provider {fieldLabel(field).toLowerCase()}
                    </button>
                  )}
                </div>
              );
            })}
            {admin && (
              <>
                <div className="button-row">
                  <button onClick={() => setEditing(!editing)}>
                    {editing ? "Close editor" : "Edit book details"}
                  </button>
                </div>
                {editing && (
                  <EditForm
                    work={work}
                    pending={edit.isPending}
                    save={(values) => edit.mutate({ values })}
                  />
                )}
                {metadata.data.cover_choices.length > 0 && (
                  <>
                    <h3>Choose a cover</h3>
                    <div className="cover-choices">
                      {metadata.data.cover_choices.map((cover, index) => (
                        <button
                          key={cover}
                          aria-label={`Use cover ${index + 1}`}
                          onClick={() =>
                            edit.mutate({ values: { cover_url: cover } })
                          }
                          disabled={edit.isPending}
                        >
                          <img
                            src={cover}
                            alt={`Cover option ${index + 1}`}
                            loading="lazy"
                            referrerPolicy="no-referrer"
                          />
                        </button>
                      ))}
                      <button
                        onClick={() =>
                          edit.mutate({ values: { cover_url: null } })
                        }
                        disabled={edit.isPending}
                      >
                        Hide cover
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
          </details>
        </>
      )}
    </section>
  );
}

function EditForm({
  work,
  pending,
  save,
}: {
  work: Work;
  pending: boolean;
  save: (values: Edit) => void;
}) {
  return (
    <form
      className="editor"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const proposed: Edit = {
          title: String(form.get("title")),
          authors: String(form.get("authors"))
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
          description: String(form.get("description")) || null,
          publication_year: form.get("year") ? Number(form.get("year")) : null,
          language: String(form.get("language")) || null,
        };
        const changed = Object.fromEntries(
          Object.entries(proposed).filter(
            ([key, value]) =>
              JSON.stringify(value) !== JSON.stringify(work[key as keyof Work]),
          ),
        ) as Edit;
        save(changed);
      }}
    >
      <p className="muted">
        Changed fields are protected from future provider refreshes. Your
        library files and Audiobookshelf metadata stay unchanged.
      </p>
      <label>
        Book title
        <input
          name="title"
          defaultValue={work.title}
          required
          maxLength={600}
        />
      </label>
      <label>
        Authors, one per line
        <textarea
          name="authors"
          defaultValue={work.authors.join("\n")}
          rows={3}
        />
      </label>
      <label>
        Book description
        <textarea
          name="description"
          defaultValue={work.description || ""}
          rows={5}
          maxLength={30000}
        />
      </label>
      <div className="form-row">
        <label>
          Publication year
          <input
            name="year"
            type="number"
            min={0}
            max={9999}
            defaultValue={work.publication_year ?? ""}
          />
        </label>
        <label>
          Book language
          <input
            name="language"
            defaultValue={work.language || ""}
            maxLength={20}
          />
        </label>
      </div>
      <button className="primary" disabled={pending}>
        Save protected edits
      </button>
    </form>
  );
}
