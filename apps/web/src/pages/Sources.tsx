import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Notice } from "../components";

type Query = components["schemas"]["MAMSearch"];
type Connection = components["schemas"]["MAMConnectionView"];
type Release = components["schemas"]["MAMRelease"];

export default function Sources({
  admin,
  canAcquire,
}: {
  admin: boolean;
  canAcquire: boolean;
}) {
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const [medium, setMedium] = useState<Query["medium"]>("all");
  const [sort, setSort] = useState<Query["sort"]>("relevance");
  const [language, setLanguage] = useState("1");
  const [narrator, setNarrator] = useState(false);
  const [submitted, setSubmitted] = useState<Query | null>(null);
  const [detail, setDetail] = useState<Release | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const cache = useQueryClient();
  const connection = useQuery({
    queryKey: ["mam-connection"],
    enabled: admin,
    queryFn: async () => result(await api.GET("/api/sources/mam/connection")),
  });
  const search = useMutation({
    mutationFn: async (query: Query) =>
      result(await api.POST("/api/sources/mam/search", { body: query })),
    onMutate: (query) => {
      setSubmitted(query);
      setDetail(null);
    },
    onSettled: () => {
      if (admin) cache.invalidateQueries({ queryKey: ["mam-connection"] });
    },
  });
  const fetchDetail = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.GET("/api/sources/mam/releases/{source_id}", {
          params: { path: { source_id: id } },
        }),
      ),
    onSuccess: setDetail,
  });
  const busy = search.isPending || fetchDetail.isPending;
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">DOWNLOAD SOURCES</p>
          <h1>Search MAM</h1>
          <p>
            Find source releases by title, author or series, then inspect the
            edition and recording details.
          </p>
        </div>
      </header>
      <p className="notice">
        Source browsing is available. Download dispatch will be enabled when the
        downloader and import workflow are ready.
      </p>
      {admin && (
        <details
          open={settingsOpen}
          onToggle={(event) => setSettingsOpen(event.currentTarget.open)}
        >
          <summary>
            MAM connection · {connection.data?.status || "loading"}
          </summary>
          <Notice error={connection.error} />
          {connection.data && (
            <ConnectionForm
              key={connection.data.generation}
              value={connection.data}
            />
          )}
        </details>
      )}
      <form
        className="panel editor"
        onSubmit={(event) => {
          event.preventDefault();
          search.mutate({
            q,
            medium,
            sort,
            language_ids: language.trim()
              ? language.split(",").map((item) => Number(item.trim()))
              : [],
            fields: narrator
              ? ["title", "author", "series", "narrator"]
              : ["title", "author", "series"],
            offset: 0,
            limit: 25,
          });
        }}
      >
        <label>
          Search title, author or series
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            maxLength={300}
            required
          />
        </label>
        <div className="form-grid">
          <label>
            Media
            <select
              value={medium}
              onChange={(event) =>
                setMedium(event.target.value as Query["medium"])
              }
            >
              <option value="all">Ebooks and audiobooks</option>
              <option value="ebook">Ebooks</option>
              <option value="audio">Audiobooks</option>
            </select>
          </label>
          <label>
            Source order
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value as Query["sort"])}
            >
              <option value="relevance">MAM relevance</option>
              <option value="seeders">Most seeders</option>
            </select>
          </label>
        </div>
        <details>
          <summary>Search options</summary>
          <label className="check-label">
            <input
              type="checkbox"
              checked={narrator}
              onChange={(event) => setNarrator(event.target.checked)}
            />
            Include narrator names
          </label>
          <label>
            MAM language IDs
            <input
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              pattern="[0-9, ]*"
              maxLength={120}
            />
          </label>
          <p className="muted">
            1 is English. Separate IDs with commas; leave empty for all
            languages.
          </p>
        </details>
        <button className="primary" disabled={busy || !q.trim()}>
          {search.isPending ? "Searching MAM…" : "Search source"}
        </button>
      </form>
      <Notice error={search.error || fetchDetail.error} />
      {search.data && !search.isPending && !search.isError && (
        <section aria-label="MAM results">
          <p role="status">
            {search.data.items.length} releases on this page
            {search.data.total !== null
              ? ` · ${search.data.total} matching results`
              : " · total unknown"}
          </p>
          {search.data.warnings?.map((warning) => (
            <p className="notice" key={warning}>
              {warning}
            </p>
          ))}
          {!search.data.items.length && (
            <Empty title="No matching releases">
              Try another title, author or search option.
            </Empty>
          )}
          {search.data.items.map((release) => (
            <article
              className="panel editor source-release"
              key={release.source_id}
            >
              <h2>{release.title}</h2>
              <p>{release.authors?.join(", ") || "Author unknown"}</p>
              <p className="muted">
                {release.medium === "audio"
                  ? "Audiobook"
                  : release.medium === "ebook"
                    ? "Ebook"
                    : "Medium unknown"}{" "}
                · {release.filetype_display || "Format unknown"} ·{" "}
                {release.size_display || "Size unknown"}
              </p>
              <p>
                {release.narrators?.length
                  ? `Narrated by ${release.narrators?.join(", ")} · `
                  : ""}
                {release.seeders == null
                  ? "Seeds unknown"
                  : `${release.seeders} seeders`}{" "}
                ·{" "}
                {release.snatches == null
                  ? "Popularity unknown"
                  : `${release.snatches} snatches`}
              </p>
              <button
                disabled={busy}
                onClick={() => {
                  setDetail(release);
                  fetchDetail.mutate(release.source_id);
                }}
              >
                View source details
              </button>
              {detail?.source_id === release.source_id && (
                <ReleaseDetail
                  release={detail}
                  loading={fetchDetail.isPending}
                  canAcquire={canAcquire}
                />
              )}
            </article>
          ))}
          <div className="actions">
            <button
              disabled={busy || !submitted || !submitted.offset}
              onClick={() =>
                submitted &&
                search.mutate({
                  ...submitted,
                  offset: Math.max(0, (submitted.offset || 0) - 25),
                })
              }
            >
              Previous releases
            </button>
            <button
              disabled={busy || !submitted || !search.data.has_more}
              onClick={() =>
                submitted &&
                search.mutate({
                  ...submitted,
                  offset: (submitted.offset || 0) + 25,
                })
              }
            >
              More releases
            </button>
          </div>
        </section>
      )}
    </>
  );
}

function ReleaseDetail({
  release,
  loading,
  canAcquire,
}: {
  release: Release;
  loading: boolean;
  canAcquire: boolean;
}) {
  return (
    <section aria-label={`Details for ${release.title}`}>
      {loading && <p role="status">Refreshing source details…</p>}
      <dl className="source-facts">
        <dt>Raw title</dt>
        <dd>{release.raw_title}</dd>
        <dt>Source release</dt>
        <dd>MAM #{release.source_id}</dd>
        <dt>Category</dt>
        <dd>{release.category || "Unknown"}</dd>
        <dt>Language</dt>
        <dd>
          {release.language ||
            (release.language_id
              ? `MAM language ${release.language_id}`
              : "Unknown")}
        </dd>
        <dt>Series</dt>
        <dd>
          {release.series
            ?.map(
              (series) =>
                `${series.name}${series.position ? ` · ${series.position}` : ""}`,
            )
            .join("; ") || "Not supplied"}
        </dd>
        <dt>Tags</dt>
        <dd>{release.tags?.join(", ") || "Not supplied"}</dd>
        <dt>ISBN</dt>
        <dd>{release.isbn || "Not supplied"}</dd>
        <dt>Source flags</dt>
        <dd>
          Freeleech:{" "}
          {release.freeleech == null
            ? "unknown"
            : release.freeleech
              ? "yes"
              : "no"}{" "}
          · VIP: {release.vip == null ? "unknown" : release.vip ? "yes" : "no"}
        </dd>
        <dt>Uploaded</dt>
        <dd>{release.uploaded_at || "Unknown"}</dd>
      </dl>
      <p className="source-description">
        {release.description || "No source description supplied."}
      </p>
      {release.media_info && (
        <details>
          <summary>Media information</summary>
          <pre className="source-description">{release.media_info}</pre>
        </details>
      )}
      <p className="muted">
        Source metadata describes this release; it does not confirm a catalog
        edition, collection coverage or library ownership.
      </p>
      {canAcquire && !loading && (
        <TorrentInspection
          key={release.source_id}
          sourceId={release.source_id}
        />
      )}
    </section>
  );
}

function TorrentInspection({ sourceId }: { sourceId: string }) {
  const cache = useQueryClient();
  const inspect = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/sources/mam/releases/{source_id}/artifact", {
          params: { path: { source_id: sourceId } },
        }),
      ),
    onSuccess: (artifact) =>
      cache.setQueryData(["source-artifact", artifact.id], artifact),
    onSettled: () => cache.invalidateQueries({ queryKey: ["mam-connection"] }),
  });
  return (
    <div>
      <button disabled={inspect.isPending} onClick={() => inspect.mutate()}>
        {inspect.isPending ? "Inspecting torrent…" : "Inspect torrent manifest"}
      </button>
      <Notice error={inspect.error} />
      {inspect.data && (
        <p role="status">
          {inspect.data.descriptor.files.length} file entries inspected.{" "}
          <Link to={`/sources/artifacts/${inspect.data.id}`}>
            View saved manifest
          </Link>
        </p>
      )}
      <p className="muted">
        Fetches the torrent metadata through your MAM connection. Does not start
        a download.
      </p>
    </div>
  );
}

function ConnectionForm({ value }: { value: Connection }) {
  const cache = useQueryClient();
  const [base, setBase] = useState(value.base_url);
  const [proxy, setProxy] = useState(value.proxy_url || "");
  const [cookie, setCookie] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [clearAuth, setClearAuth] = useState(false);
  const [enabled, setEnabled] = useState(
    value.configured ? value.enabled : true,
  );
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/sources/mam/connection", {
          body: {
            base_url: base,
            proxy_url: proxy || null,
            mam_id: cookie || null,
            proxy_username: username || null,
            proxy_password: password || null,
            clear_proxy_credentials: clearAuth,
            enabled,
            expected_generation: value.generation,
          },
        }),
      ),
    onSuccess: (connection) => {
      setCookie("");
      setUsername("");
      setPassword("");
      cache.setQueryData(["mam-connection"], connection);
    },
  });
  const test = useMutation({
    mutationFn: async () =>
      result(await api.POST("/api/sources/mam/connection/test")),
    onSuccess: (connection) =>
      cache.setQueryData(["mam-connection"], connection),
    onSettled: () => cache.invalidateQueries({ queryKey: ["mam-connection"] }),
  });
  return (
    <form
      className="panel editor"
      aria-label="MAM connection settings"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label>
        MAM URL
        <input
          type="url"
          value={base}
          onChange={(event) => setBase(event.target.value)}
          required
          maxLength={2000}
        />
      </label>
      <label>
        mam_id
        <input
          type="password"
          value={cookie}
          onChange={(event) => setCookie(event.target.value)}
          autoComplete="new-password"
          placeholder={
            value.has_session
              ? "Saved; leave blank to keep"
              : "Session cookie value"
          }
          maxLength={8192}
        />
      </label>
      <label>
        Gluetun HTTP proxy URL
        <input
          type="url"
          value={proxy}
          onChange={(event) => setProxy(event.target.value)}
          placeholder="http://gluetun:8888"
          maxLength={2000}
        />
      </label>
      <p className="muted">
        {proxy
          ? "Proxy required: a failed proxy will never fall back to a direct request."
          : "MAM requests use a direct connection."}{" "}
        This setting routes source HTTP requests; torrent traffic is configured
        separately.
      </p>
      <details>
        <summary>
          Proxy authentication
          {value.has_proxy_credentials ? " · credentials saved" : ""}
        </summary>
        <label>
          Proxy username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
            maxLength={300}
          />
        </label>
        <label>
          Proxy password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            maxLength={1000}
          />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={clearAuth}
            onChange={(event) => setClearAuth(event.target.checked)}
          />
          Clear saved proxy credentials
        </label>
      </details>
      <label className="check-label">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable MAM
      </label>
      <Notice error={save.error || test.error} />
      {value.last_error && <p className="notice">{value.last_error}</p>}
      <p role="status">Connection: {value.status}</p>
      <div className="actions">
        <button className="primary" disabled={save.isPending || test.isPending}>
          Save MAM connection
        </button>
        <button
          type="button"
          disabled={
            !value.configured ||
            !value.enabled ||
            save.isPending ||
            test.isPending
          }
          onClick={() => test.mutate()}
        >
          Test saved connection
        </button>
      </div>
    </form>
  );
}
