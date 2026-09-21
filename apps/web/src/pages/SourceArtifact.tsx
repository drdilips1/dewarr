import InfiniteScroll from "../components/InfiniteScroll";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import ReleaseSelection from "./ReleaseSelection";

export default function SourceArtifact() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const workId = params.get("work");
  const bookContext = new URLSearchParams(params);
  bookContext.set("tab", "sources");
  const [page, setPage] = useState(0);
  const artifact = useQuery({
    queryKey: ["source-artifact", id],
    queryFn: async () =>
      result(
        await api.GET("/api/source-artifacts/{artifact_id}", {
          params: { path: { artifact_id: id } },
        }),
      ),
  });
  if (artifact.isPending) return <Loading />;
  if (!artifact.data) return <Notice error={artifact.error} />;
  const { descriptor, release, current_connection, created_at } = artifact.data;
  const files = descriptor.files.slice(0, (page + 1) * 50);
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">
            {release.source === "mam"
              ? "MAM"
              : release.source === "audiobookbay"
                ? "AUDIOBOOKBAY"
                : "PROWLARR"}{" "}
            RELEASE
          </p>
          <h1>Torrent manifest</h1>
          <p>{release.title}</p>
          <Link
            to={
              workId
                ? `/books/${encodeURIComponent(workId)}?${bookContext}`
                : `/search?q=${encodeURIComponent(release.title)}`
            }
          >
            {workId ? "Return to book sources" : "Find book"}
          </Link>
        </div>
      </header>
      <Notice error={artifact.error} />
      {!current_connection && (
        <p className="notice error">
          The source connection changed. Inspect this release again before using
          it for a download.
        </p>
      )}
      <section className="panel" aria-label="Inspected torrent">
        <h2>{descriptor.name}</h2>
        <p>
          {descriptor.files.length} files ·{" "}
          {descriptor.content_bytes.toLocaleString()} bytes of content ·{" "}
          {descriptor.private ? "Private tracker" : "Public torrent"}
        </p>
        <p className="muted">
          Inspected {new Date(created_at).toLocaleString()}. These are torrent
          file entries; book and edition matches are reviewed after download.
        </p>
        <p className="notice">
          Torrent metadata is saved privately. No download has been started.
        </p>
        <ul className="artifact-files" aria-label="Torrent files">
          {files.map((file) => (
            <li key={file.index}>
              <span className="break-text">{file.path}</span>
              <span className="muted">
                {file.size_bytes.toLocaleString()} B
              </span>
            </li>
          ))}
        </ul>
        <InfiniteScroll
          query={{
            hasNextPage: (page + 1) * 50 < descriptor.files.length,
            isFetching: false,
            isFetchNextPageError: false,
            fetchNextPage: async () => setPage((n) => n + 1),
          }}
        />
        <details>
          <summary>Torrent identity</summary>
          <dl className="source-facts">
            <dt>v1 info hash</dt>
            <dd className="break-text">
              {descriptor.infohash_v1 || "Not present"}
            </dd>
            <dt>v2 info hash</dt>
            <dd className="break-text">
              {descriptor.infohash_v2 || "Not present"}
            </dd>
            <dt>Metadata checksum</dt>
            <dd className="break-text">{descriptor.artifact_sha256}</dd>
            <dt>Padding</dt>
            <dd>
              {descriptor.padding_bytes.toLocaleString()} B (not library
              content)
            </dd>
          </dl>
        </details>
      </section>
      <ReleaseSelection key={id} artifact={artifact.data} />
    </>
  );
}
