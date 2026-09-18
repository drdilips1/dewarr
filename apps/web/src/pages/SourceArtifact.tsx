import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import ReleaseSelection from "./ReleaseSelection";

export default function SourceArtifact() {
  const { id = "" } = useParams();
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
  const files = descriptor.files.slice(page * 50, (page + 1) * 50);
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">MAM RELEASE #{release.source_id}</p>
          <h1>Torrent manifest</h1>
          <p>{release.title}</p>
          <Link to={`/sources?q=${encodeURIComponent(release.title)}`}>
            Return to source search
          </Link>
        </div>
      </header>
      <Notice error={artifact.error} />
      {!current_connection && (
        <p className="notice error">
          The MAM connection changed. Inspect this release again before using it
          for a download.
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
        {descriptor.files.length > 50 && (
          <div className="button-row">
            <button
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous files
            </button>
            <span>
              Page {page + 1} of {Math.ceil(descriptor.files.length / 50)}
            </span>
            <button
              disabled={(page + 1) * 50 >= descriptor.files.length}
              onClick={() => setPage((value) => value + 1)}
            >
              More files
            </button>
          </div>
        )}
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
