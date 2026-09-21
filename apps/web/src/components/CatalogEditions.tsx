import { useState } from "react";
import BookPagination from "./BookPagination";
import { Link } from "react-router-dom";
import { languageName } from "./LanguageSelect";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result, type Work } from "../api/client";
import { Loading, Notice } from "../components";
import type { components } from "../api/schema";
import type { WantedVersion } from "../pages/Wanted";
export default function CatalogEditions({
  work,
  request,
  readerBook,
  admin = false,
}: {
  work: Work;
  admin?: boolean;
  readerBook?: components["schemas"]["BookData"] | null;
  request?: (version: WantedVersion) => void;
}) {
  const cache = useQueryClient();
  const [page, setPage] = useState(1);
  const [providerPage, setProviderPage] = useState(1);
  const group = useQuery({
    queryKey: ["work-grouping", work.id],
    enabled: admin,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works/{work_id}/grouping", {
          params: { path: { work_id: work.id } },
        }),
      ),
  });
  const member = group.data?.members.find((item) => item.work.id === work.id);
  const primary = useMutation({
    mutationFn: async ({
      medium,
      version_id,
    }: {
      medium: string;
      version_id: string | null;
    }) =>
      result(
        await api.PATCH("/api/catalog/works/{work_id}/primary-edition", {
          params: { path: { work_id: work.id } },
          body: { medium, version_id, expected_revision: member!.revision },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries();
    },
  });
  const query = useQuery({
    queryKey: ["reader-work-metadata", work.id, "editions", page],
    queryFn: async ({ signal }) =>
      result(
        await api.GET("/api/metadata/works/{work_id}", {
          params: {
            path: { work_id: work.id },
            query: { offset: (page - 1) * 20, limit: 20, scope: "display" },
          },
          signal,
        }),
      ),
  });
  return (
    <section className="book-tab-section" aria-label="Editions and recordings">
      <div className="book-tab-heading">
        <h2>Editions & recordings</h2>
        {query.data && (
          <span className="muted">{query.data.versions_total} editions</span>
        )}
      </div>
      <Notice error={query.error || group.error || primary.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button onClick={() => query.refetch()}>Retry editions</button>
      )}
      {query.data &&
        (query.data.versions.length ? (
          <div className="book-table-scroll">
            <table className="book-data-table">
              <thead>
                <tr>
                  <th>Edition</th>
                  <th>Format</th>
                  <th>Details</th>
                  <th>Library</th>
                  {request && (
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {query.data.versions.map((version) => (
                  <tr key={version.id}>
                    <td>
                      <strong>{version.title || work.title}</strong>
                      {(version.id ===
                        work.availability.primary_audio_version_id ||
                        version.id ===
                          work.availability.primary_ebook_version_id) && (
                        <small>Primary edition</small>
                      )}
                      {admin &&
                        version.owned &&
                        ["audio", "ebook"].includes(version.medium) && (
                          <div className="button-row">
                            <button
                              disabled={!member || primary.isPending}
                              onClick={() =>
                                primary.mutate({
                                  medium: version.medium,
                                  version_id: version.id,
                                })
                              }
                            >
                              Use as primary
                            </button>
                          </div>
                        )}
                      {!!version.narrators.length && (
                        <small>
                          Narrated by {version.narrators.join(", ")}
                        </small>
                      )}
                    </td>
                    <td>
                      {(
                        {
                          audio: "Audiobook",
                          ebook: "Ebook",
                          print: "Print",
                        } as Record<string, string>
                      )[version.medium] || "Other"}
                    </td>
                    <td>
                      {[
                        version.publication_year,
                        languageName(version.language),
                        version.abridged == null
                          ? null
                          : version.abridged
                            ? "Abridged"
                            : "Unabridged",
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                      {version.needs_review && (
                        <small>Metadata needs review</small>
                      )}
                    </td>
                    <td>
                      <span
                        className={version.owned ? "status owned" : "muted"}
                      >
                        {version.owned ? "In library" : "Not owned"}
                      </span>
                    </td>
                    {request && (
                      <td>
                        {version.owned ? (
                          <Link
                            to={`/books/${version.work_id || work.id}?tab=library&format=${version.medium}`}
                          >
                            View library copies
                          </Link>
                        ) : (
                          ["audio", "ebook"].includes(version.medium) && (
                            <button onClick={() => request(version)}>
                              Request{" "}
                              {version.medium === "audio"
                                ? "recording"
                                : "edition"}
                            </button>
                          )
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            No editions are linked yet. Use Book metadata to match or refresh a
            catalog source.
          </p>
        ))}
      {query.data && (
        <BookPagination
          page={page}
          total={query.data.versions_total}
          onPage={setPage}
          busy={query.isFetching}
        />
      )}
      {admin && (
        <div className="button-row" aria-label="Reset primary editions">
          <button
            disabled={!member || primary.isPending}
            onClick={() =>
              primary.mutate({ medium: "audio", version_id: null })
            }
          >
            Reset primary audiobook
          </button>
          <button
            disabled={!member || primary.isPending}
            onClick={() =>
              primary.mutate({ medium: "ebook", version_id: null })
            }
          >
            Reset primary ebook
          </button>
        </div>
      )}
      {!!readerBook?.editions?.length && (
        <section aria-label="Hardcover editions">
          <div className="book-tab-heading">
            <h3>On Hardcover</h3>
            <span className="muted">
              {readerBook.editions.length}
              {readerBook.editions_more ? "+" : ""} editions
            </span>
          </div>
          <div className="book-table-scroll">
            <table className="book-data-table">
              <thead>
                <tr>
                  <th>Edition</th>
                  <th>Format</th>
                  <th>Published</th>
                  <th>Publisher</th>
                </tr>
              </thead>
              <tbody>
                {readerBook.editions
                  .slice((providerPage - 1) * 20, providerPage * 20)
                  .map((edition) => (
                    <tr key={edition.external_id}>
                      <td>
                        {edition.title || readerBook.title}
                        {!!edition.narrators?.length && (
                          <small>{edition.narrators.join(", ")}</small>
                        )}
                      </td>
                      <td>
                        {edition.medium === "audio"
                          ? "Audiobook"
                          : edition.medium === "ebook"
                            ? "Ebook"
                            : edition.medium === "print"
                              ? "Print"
                              : "Other"}
                      </td>
                      <td>
                        {[
                          edition.publication_year,
                          languageName(edition.language),
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </td>
                      <td>{edition.publisher || "—"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <BookPagination
            page={providerPage}
            total={readerBook.editions.length}
            onPage={setProviderPage}
            label="Hardcover editions"
          />
          {readerBook.editions_more && (
            <a
              href={`https://hardcover.app/books/${encodeURIComponent(readerBook.external_id)}`}
              target="_blank"
              rel="noreferrer"
            >
              Explore all editions on Hardcover →
            </a>
          )}
        </section>
      )}
    </section>
  );
}
