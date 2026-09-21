import SettingHelp from "../components/SettingHelp";
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
  const cache = useQueryClient();

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
          <Link to={`/sources/prowlarr?${params.toString()}`}>
            Search Prowlarr indexers
          </Link>
          <Link to={`/sources/audiobookbay?${params.toString()}`}>
            Search AudiobookBay
          </Link>
          <p>
            Find source releases by title, author or series, then inspect the
            edition and recording details.
          </p>
        </div>
      </header>
      {admin && (
        <Link className="back-link" to="/settings#sources">
          Source settings →
        </Link>
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
  const [params] = useSearchParams();
  const context = new URLSearchParams();
  if (params.get("request")) context.set("request", params.get("request")!);
  if (params.get("slot")) context.set("slot", params.get("slot")!);
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
          <Link to={`/sources/artifacts/${inspect.data.id}?${context}`}>
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

export function MamConnectionForm({ value }: { value: Connection }) {
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
  const dirty =
    base !== value.base_url ||
    proxy !== (value.proxy_url || "") ||
    Boolean(cookie || username || password || clearAuth) ||
    enabled !== value.enabled;
  const persist = async () =>
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
    );
  const save = useMutation({
    mutationFn: persist,
    onSuccess: (connection) => {
      setCookie("");
      setUsername("");
      setPassword("");
      cache.setQueryData(["mam-connection"], connection);
    },
  });
  const network = useQuery<components["schemas"]["MAMNetworkView"] | null>({
    queryKey: ["mam-network", value.generation],
    queryFn: async () => null,
    enabled: false,
  });
  const test = useMutation({
    mutationFn: async () => {
      if (dirty) await persist();
      return result(await api.POST("/api/sources/mam/network/test"));
    },
    onMutate: () => cache.setQueryData(["mam-network", value.generation], null),
    onSuccess: (diagnostics) => {
      cache.setQueryData(
        ["mam-network", diagnostics.connection.generation],
        diagnostics,
      );
      cache.setQueryData(["mam-connection"], diagnostics.connection);
      setCookie("");
      setUsername("");
      setPassword("");
      setClearAuth(false);
    },
    onError: () => cache.invalidateQueries({ queryKey: ["mam-connection"] }),
  });
  const health = !dirty && enabled ? network.data : null;
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
          placeholder={value.has_session ? "••••••••" : "Session cookie value"}
          maxLength={8192}
        />
      </label>
      <details open={Boolean(value.proxy_url) || value.status === "route"}>
        <summary>Proxy options</summary>{" "}
        <label>
          <span className="setting-subheading">
            HTTP proxy URL
            <SettingHelp label="connection options">
              {proxy
                ? "Proxy required: a failed proxy will never fall back to a direct request."
                : "MAM requests use a direct connection."}{" "}
              This setting routes source HTTP requests; torrent traffic is
              configured separately.
            </SettingHelp>
          </span>
          <input
            type="url"
            value={proxy}
            onChange={(event) => setProxy(event.target.value)}
            placeholder="http://gluetun:8888"
            maxLength={2000}
          />
        </label>
        <p className="muted">
          Supports HTTP and HTTPS proxies. Enter authentication in the separate
          username and password fields below.
        </p>
        <div className="settings-fields">
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
              placeholder={
                value.has_proxy_credentials &&
                !clearAuth &&
                proxy === (value.proxy_url || "")
                  ? "••••••••"
                  : undefined
              }
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
        </div>
      </details>
      <section
        className="mam-network"
        data-health={health?.status || "unknown"}
        aria-label="MAM network status"
        aria-live="polite"
      >
        <div className="mam-network-heading">
          <div className="mam-network-title">
            <h3>Network checks</h3>
            <SettingHelp label="network checks">
              Tests the MAM cookie and checks public IPs through the proxy and
              direct server connection. IP checks never send your MAM cookie.
              MAM requests never fall back to direct when a proxy is configured.
            </SettingHelp>
          </div>
          <span className="mam-network-badge">
            {test.isPending
              ? "Testing…"
              : health
                ? health.status
                : "Not tested"}
          </span>
        </div>
        {health?.status !== "healthy" && (
          <p className="mam-network-description">
            {health?.message || "Test connection to refresh these checks."}
          </p>
        )}
        <dl>
          <div>
            <dt>Current route</dt>
            <dd>
              {!enabled ? "Disabled" : proxy ? "Proxy (required)" : "Direct"}
              {dirty ? " · unsaved" : ""}
            </dd>
          </div>
          <div>
            <dt>MAM cookie</dt>
            <dd>{health?.cookie_status || "Unverified"}</dd>
          </div>
          <div>
            <dt>Proxy health</dt>
            <dd>
              {health?.proxy_status ||
                (proxy ? "Not tested" : "Not configured")}
            </dd>
          </div>
          <div className="mam-network-address">
            <dt>Proxy IP</dt>
            <dd>
              {health?.proxy?.ip ||
                health?.proxy?.error ||
                (proxy ? "Not tested" : "Not configured")}
            </dd>
          </div>
          <div className="mam-network-address">
            <dt>Direct server IP</dt>
            <dd>{health?.direct.ip || health?.direct.error || "Not tested"}</dd>
          </div>
        </dl>
        {health && (
          <p className="mam-network-checked">
            Last checked{" "}
            <time dateTime={health.checked_at}>
              {new Date(health.checked_at).toLocaleString()}
            </time>
          </p>
        )}
        {health?.proxy?.ip && health.proxy.ip === health.direct.ip && (
          <p className="notice">
            The proxy and direct server report the same public IP. Check the
            proxy's VPN routing if you expect different addresses.
          </p>
        )}
      </section>
      <label className="check-label">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable MAM
      </label>
      <Notice error={save.error || test.error} />
      {value.last_error && !test.error && !save.error && (
        <p className="notice">{value.last_error}</p>
      )}
      <p role="status">Connection: {value.status}</p>
      <div className="actions">
        <button className="primary" disabled={save.isPending || test.isPending}>
          Save connection
        </button>
        <button
          type="button"
          disabled={
            (!value.has_session && !cookie) ||
            !enabled ||
            save.isPending ||
            test.isPending
          }
          onClick={(event) => {
            if (event.currentTarget.form?.reportValidity()) test.mutate();
          }}
        >
          {test.isPending
            ? "Testing…"
            : dirty
              ? "Save & test connection"
              : "Test connection"}
        </button>
      </div>
    </form>
  );
}
